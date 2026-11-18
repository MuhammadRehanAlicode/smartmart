from decimal import Decimal

from django import forms
from django.core.validators import MinValueValidator
from django.forms import inlineformset_factory

from apps.products.models import Product, ProductUnit
from apps.suppliers.models import Supplier

from .models import Purchase, PurchaseItem


class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Purchase
        fields = ("supplier", "invoice_reference", "amount_paid", "notes")
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True)
        for f in self.fields.values():
            f.widget.attrs["class"] = "input"


class PurchaseItemForm(forms.ModelForm):
    unit_code = forms.ChoiceField(choices=[("", "Choose unit")] + list(Product.Unit.choices), required=False)
    conversion_factor = forms.DecimalField(required=False, min_value=Decimal("0.000001"), max_digits=12, decimal_places=6)

    class Meta:
        model = PurchaseItem
        fields = ("product", "quantity", "unit_code", "conversion_factor", "unit_cost", "selling_price")

    opening_stock = forms.DecimalField(required=False, disabled=True, decimal_places=6, max_digits=14)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["product"].queryset = Product.objects.filter(is_archived=False)
        self.fields["product"].widget.attrs["style"] = "display:none"
        self.fields["selling_price"].validators.append(MinValueValidator(Decimal("0.01")))
        self.fields["selling_price"].required = False
        self.fields["selling_price"].widget.attrs.update({"min": "0.01", "step": "0.01", "required": "required"})
        self.fields["quantity"].widget.attrs.update({"step": "0.000001", "min": "0.000001"})
        self.fields["conversion_factor"].widget.attrs.update({"step": "0.000001", "min": "0.000001"})
        if not self.instance.pk and not self.is_bound:
            self.initial["conversion_factor"] = ""
        for f in self.fields.values():
            f.widget.attrs["class"] = "input"

    def clean(self):
        data = super().clean()
        product, code = data.get("product"), data.get("unit_code")
        if product and not data.get("selling_price"):
            data["selling_price"] = product.selling_price
        if product and data.get("selling_price") is not None and data["selling_price"] <= 0:
            self.add_error("selling_price", "Selling price must be greater than zero.")
        if product and not code:
            code = product.base_unit
            data["unit_code"] = code
        if product and code:
            if code not in (product.base_unit, Product.Unit.CTN, Product.Unit.PACK):
                self.add_error("unit_code", "Choose the product's base unit, configured carton, or pack unit.")
                return data
            unit = ProductUnit.objects.filter(product=product, unit_code=code).first()
            factor = None
            if code == product.base_unit and unit is None:
                # Backward-compatible fallback for products created outside the dashboard.
                factor = Decimal("1")
            elif unit and unit.purchase_enabled:
                factor = unit.conversion_factor
            elif unit and not unit.purchase_enabled:
                self.add_error("unit_code", "This purchase unit is not enabled for the selected product.")
            elif code == Product.Unit.PACK:
                factor = data.get("conversion_factor")
                if factor is None or factor <= 0:
                    self.add_error("conversion_factor", "Enter how many base units are in one pack.")
            else:
                self.add_error("unit_code", "This purchase unit is not configured for the selected product.")
            if factor is not None and factor > 0:
                qty = data.get("quantity") or 0
                data["conversion_factor"] = factor
                self.instance.conversion_factor = factor
                self.instance.converted_quantity = (qty * factor).quantize(Decimal("0.000001"))
                if self.instance.converted_quantity <= 0:
                    self.add_error("quantity", "This quantity is too small to convert into the product's base unit.")
        return data

    def save(self, commit=True):
        item = super().save(commit=False)
        # Retain the legacy database column for older received purchase history,
        # while new and edited pending purchases no longer accept an extra cost.
        item.box_cost = Decimal("0.00")
        if commit:
            item.save()
            self.save_m2m()
        return item


PurchaseItemFormSet = inlineformset_factory(
    Purchase, PurchaseItem, form=PurchaseItemForm,
    extra=0, can_delete=True, min_num=1, validate_min=True,
)
