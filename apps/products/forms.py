import secrets

from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils.text import slugify

from .models import Category, Product, ProductUnit


def style(form):
    for f in form.fields.values():
        if isinstance(f.widget, forms.CheckboxInput):
            continue
        f.widget.attrs.setdefault("class", "input")


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name",)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        style(self)


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = (
            "name", "description", "category", "sku", "base_unit", "has_manufacturer_barcode", "barcode", "image",
            "cost_price", "selling_price", "discount_percent",
            "low_stock_threshold", "is_online",
        )
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}
        help_texts = {
            "sku": "Generated automatically when left blank.",
            "has_manufacturer_barcode": "Select this when entering the barcode printed by the manufacturer. Otherwise an internal barcode is assigned automatically.",
            "barcode": "Required for a manufacturer barcode. Internal barcodes are generated automatically.",
            "cost_price": "Updated automatically when purchases are received. Edit only to correct it.",
            "selling_price": "Price for one base unit. Set separate carton prices in the unit settings below.",
            "discount_percent": "0 to 100.",
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["category"].queryset = Category.objects.filter(is_active=True)
        self.fields["base_unit"].required = False
        self.fields["base_unit"].initial = self.instance.base_unit or Product.Unit.PCS
        style(self)

    def clean_sku(self):
        return self.cleaned_data["sku"].strip().upper()

    def clean_barcode(self):
        barcode = (self.cleaned_data.get("barcode") or "").strip() or None
        if self.cleaned_data.get("has_manufacturer_barcode") and not barcode:
            raise forms.ValidationError("Enter the barcode printed on the product.")
        if not self.cleaned_data.get("has_manufacturer_barcode"):
            if self.instance.pk and self.instance.has_manufacturer_barcode:
                return None
            return self.instance.barcode if self.instance.pk else None
        return barcode

    def clean(self):
        data = super().clean()
        if not data.get("base_unit"):
            data["base_unit"] = self.instance.base_unit or Product.Unit.PCS
        if self.instance.pk and data.get("base_unit") and data["base_unit"] != self.instance.base_unit:
            has_history = (
                self.instance.stock_quantity != 0
                or self.instance.movements.exists()
                or self.instance.purchase_items.exists()
                or self.instance.sale_items.exists()
            )
            if has_history:
                self.add_error("base_unit", "Base unit cannot change after stock or transaction history exists.")
        return data


class ProductCreateForm(ProductForm):
    opening_stock = forms.DecimalField(min_value=0, max_digits=14, decimal_places=6, initial=0, required=False,
                                       help_text="Units already on the shelf today.")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["sku"].required = False
        self.fields["barcode"].required = False
        style(self)

    def clean_sku(self):
        sku = (self.cleaned_data.get("sku") or "").strip().upper()
        if sku:
            return sku
        base = slugify(self.cleaned_data["name"]).replace("-", "").upper()[:40] or "ITEM"
        while True:
            candidate = f"{base}-{secrets.token_hex(3).upper()}"
            if not Product.objects.filter(sku=candidate).exists():
                return candidate

    def clean_opening_stock(self):
        return self.cleaned_data.get("opening_stock") or 0


class ProductUnitForm(forms.ModelForm):
    unit_code = forms.ChoiceField(choices=[("", "Choose unit")] + list(Product.Unit.choices), required=False)

    class Meta:
        model = ProductUnit
        fields = ("unit_code", "conversion_factor", "purchase_enabled", "sales_enabled", "selling_price")
        widgets = {"conversion_factor": forms.NumberInput(attrs={"step": "0.000001", "min": "0.000001"}),
                   "selling_price": forms.NumberInput(attrs={"step": "0.01", "min": "0"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["conversion_factor"].required = False
        self.fields["selling_price"].required = False
        style(self)

    def clean(self):
        data = super().clean()
        if not data.get("unit_code"):
            if data.get("purchase_enabled") or data.get("sales_enabled"):
                raise ValidationError("Choose a unit for enabled purchase or sales options.")
            return data
        if not data.get("conversion_factor") or data["conversion_factor"] <= 0:
            self.add_error("conversion_factor", "Enter how many base units this unit contains.")
        return data


class BaseProductUnitFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        units = {}
        for form in self.forms:
            data = getattr(form, "cleaned_data", {})
            if not data or data.get("DELETE") or not data.get("unit_code"):
                continue
            code = data["unit_code"]
            if code not in (self.instance.base_unit, Product.Unit.CTN):
                raise ValidationError("Configure only the product's base unit and optional carton unit.")
            if code in units:
                raise ValidationError(f"{code} can only be configured once.")
            units[code] = form
            if data.get("sales_enabled") and data.get("selling_price") is None:
                data["selling_price"] = self.instance.selling_price * data.get("conversion_factor", 1)
        base = units.get(self.instance.base_unit)
        if not base:
            raise ValidationError("The product's base unit must be configured.")
        base.cleaned_data["conversion_factor"] = 1
        base.cleaned_data["purchase_enabled"] = True
        base.cleaned_data["sales_enabled"] = True
        base.cleaned_data["selling_price"] = self.instance.selling_price


ProductUnitFormSet = inlineformset_factory(
    Product, ProductUnit, form=ProductUnitForm, formset=BaseProductUnitFormSet,
    extra=2, can_delete=True, max_num=3, validate_max=True,
)
