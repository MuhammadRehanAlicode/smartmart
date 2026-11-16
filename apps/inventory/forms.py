from django import forms


class StockAdjustmentForm(forms.Form):
    quantity_change = forms.DecimalField(max_digits=14, decimal_places=6,
        label="Change in quantity",
        help_text="Use a positive number to add stock, negative to remove (e.g. -3 for damaged items).",
    )
    reason = forms.CharField(max_length=200, help_text="Required, e.g. “Damaged”, “Stock count correction”.")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        for f in self.fields.values():
            f.widget.attrs["class"] = "input"

    def clean_quantity_change(self):
        v = self.cleaned_data["quantity_change"]
        if v == 0:
            raise forms.ValidationError("Enter a number other than zero.")
        return v

    def clean_reason(self):
        r = self.cleaned_data["reason"].strip()
        if not r:
            raise forms.ValidationError("Please give a reason.")
        return r
