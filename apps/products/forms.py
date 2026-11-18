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
    barcode = forms.CharField(required=False, strip=False)

    class Meta:
        model = Product
        fields = (
            "name", "description", "category", "sku", "manufacturer", "has_manufacturer_barcode", "barcode", "image", "base_unit",
            "cost_price", "selling_price", "discount_percent",
            "low_stock_threshold", "is_online",
        )
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}
        help_texts = {
            "sku": "Generated automatically when left blank.",
            "manufacturer": "Enter the manufacturer to use its printed barcode.",
            "barcode": "Enter the exact barcode printed on the package. Leave blank to generate one when no manufacturer is set.",
            "cost_price": "Updated automatically when purchases are received. Edit only to correct it.",
            "selling_price": "Price for one base unit. Purchase receipts update this from the purchase line.",
            "discount_percent": "0 to 100.",
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["category"].queryset = Category.objects.filter(is_active=True)
        self.fields["has_manufacturer_barcode"].widget = forms.HiddenInput()
        if self.instance.pk and not self.instance.has_manufacturer_barcode:
            self.initial["barcode"] = ""
        self.fields["base_unit"].required = False
        self.fields["base_unit"].initial = self.instance.base_unit or Product.Unit.PCS
        style(self)

    def clean_sku(self):
        return self.cleaned_data["sku"].strip().upper()

    def save(self, commit=True):
        product = super().save(commit=False)
        product.has_manufacturer_barcode = bool(self.cleaned_data.get("manufacturer") or self.cleaned_data.get("has_manufacturer_barcode"))
        if commit:
            product.save()
            self.save_m2m()
        return product

    def clean_barcode(self):
        barcode = self.cleaned_data.get("barcode")
        if barcode == "":
            barcode = None
        if (self.cleaned_data.get("manufacturer") or self.cleaned_data.get("has_manufacturer_barcode")) and not barcode:
            raise forms.ValidationError("Enter the barcode printed on the product.")
        if not (self.cleaned_data.get("manufacturer") or self.cleaned_data.get("has_manufacturer_barcode")):
            if self.instance.pk and self.instance.has_manufacturer_barcode and not self.instance.manufacturer:
                return self.instance.barcode
            return self.instance.barcode if self.instance.pk and not self.instance.has_manufacturer_barcode else None
        return barcode

    def clean(self):
        data = super().clean()
        manufacturer = (data.get("manufacturer") or "").strip()
        data["manufacturer"] = manufacturer
        data["has_manufacturer_barcode"] = bool(manufacturer or data.get("has_manufacturer_barcode"))
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


class BarcodeSheetForm(forms.Form):
    label_width = forms.DecimalField(min_value=20, max_value=70, max_digits=4, decimal_places=1, initial=50)
    label_height = forms.DecimalField(min_value=12, max_value=90, max_digits=4, decimal_places=1, initial=30)
    margin_x = forms.DecimalField(min_value=0, max_value=20, max_digits=4, decimal_places=1, initial=5)
    margin_y = forms.DecimalField(min_value=0, max_value=20, max_digits=4, decimal_places=1, initial=5)
    gap_x = forms.DecimalField(min_value=0, max_value=20, max_digits=4, decimal_places=1, initial=2)
    gap_y = forms.DecimalField(min_value=0, max_value=20, max_digits=4, decimal_places=1, initial=2)
    show_price = forms.BooleanField(required=False)
    show_sku = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style(self)


class ThermalLabelForm(forms.Form):
    printer = forms.ChoiceField(choices=(("tspl", "TSPL (TSC and compatible)"), ("zpl", "ZPL II (Zebra and compatible)")))
    thermal_width = forms.DecimalField(min_value=20, max_value=104, max_digits=4, decimal_places=1, initial=50)
    thermal_height = forms.DecimalField(min_value=10, max_value=150, max_digits=4, decimal_places=1, initial=30)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style(self)
