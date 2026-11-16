from django import forms

from apps.accounts.models import User


class ProfileForm(forms.ModelForm):
    default_address = forms.CharField(label="Delivery address", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "phone")

    def __init__(self, *a, profile=None, **kw):
        super().__init__(*a, **kw)
        self.profile = profile
        if profile is not None:
            self.fields["default_address"].initial = profile.default_address
        self.fields["first_name"].required = True
        self.fields["phone"].required = True
        for f in self.fields.values():
            f.widget.attrs["class"] = "input"

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit and self.profile is not None:
            self.profile.default_address = self.cleaned_data["default_address"]
            self.profile.save()
        return user
