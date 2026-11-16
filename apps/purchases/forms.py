from decimal import Decimal

from django import forms
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

    class Meta:
        model = PurchaseItem
        fields = ("product", "quantity", "unit_code", "unit_cost", "box_cost")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["product"].queryset = Product.objects.filter(is_archived=False)
        self.fields["product"].widget.attrs["style"] = "display:none"
        self.fields["quantity"].widget.attrs.update({"step": "0.000001", "min": "0.000001"})
        for f in self.fields.values():
            f.widget.attrs["class"] = "input"

    def clean(self):
        data = super().clean()
        product, code = data.get("product"), data.get("unit_code")
        if product and not code:
            code = product.base_unit
            data["unit_code"] = code
        if product and code:
            if code not in (product.base_unit, Product.Unit.CTN):
                self.add_error("unit_code", "Choose the product's base unit or its configured carton unit.")
            unit = ProductUnit.objects.filter(product=product, unit_code=code, purchase_enabled=True).first()
            if unit is None and code == product.base_unit:
                # Backward-compatible fallback for products created outside the dashboard.
                self.instance.conversion_factor = 1
                self.instance.converted_quantity = data.get("quantity") or 0
            elif unit is None:
                self.add_error("unit_code", "This purchase unit is not configured for the selected product.")
            else:
                qty = data.get("quantity") or 0
                self.instance.conversion_factor = unit.conversion_factor
                self.instance.converted_quantity = (qty * unit.conversion_factor).quantize(Decimal("0.000001"))
                if self.instance.converted_quantity <= 0:
                    self.add_error("quantity", "This quantity is too small to convert into the product's base unit.")
        return data

    def save(self, commit=True):
        item = super().save(commit=False)
        if commit:
            item.save()
            self.save_m2m()
        return item


PurchaseItemFormSet = inlineformset_factory(
    Purchase, PurchaseItem, form=PurchaseItemForm,
    extra=0, can_delete=True, min_num=1, validate_min=True,
)
