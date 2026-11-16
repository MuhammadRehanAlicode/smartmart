import uuid

from django import forms

from .models import HeroBanner


class HeroBannerUploadForm(forms.ModelForm):
    class Meta:
        model = HeroBanner
        fields = ("image", "alt_text", "sort_order", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image"].required = True
        self.fields["alt_text"].required = False
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input")


class HeroBannerEditForm(HeroBannerUploadForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image"].required = False

from apps.accounts.models import phone_validator


class CheckoutForm(forms.Form):
    customer_name = forms.CharField(label="Full name", max_length=150)
    phone = forms.CharField(label="Phone number", max_length=16, validators=[phone_validator],
                            help_text="So the rider can reach you, e.g. 03001234567.")
    address = forms.CharField(label="Delivery address", widget=forms.Textarea(attrs={"rows": 3}), max_length=500)
    delivery_instructions = forms.CharField(label="Delivery instructions (optional)", required=False, max_length=300)
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        for f in self.fields.values():
            if not isinstance(f.widget, forms.HiddenInput):
                f.widget.attrs["class"] = "input"

    def clean_customer_name(self):
        v = self.cleaned_data["customer_name"].strip()
        if not v:
            raise forms.ValidationError("Please enter your name.")
        return v

    def clean_address(self):
        v = self.cleaned_data["address"].strip()
        if len(v) < 8:
            raise forms.ValidationError("Please enter a full delivery address.")
        return v


class ContactForm(forms.Form):
    SUBJECT_CHOICES = [
        ("general", "General inquiry"),
        ("order", "Order support"),
        ("delivery", "Delivery issue"),
        ("product", "Product question"),
        ("returns", "Returns & refunds"),
        ("other", "Other"),
    ]

    name = forms.CharField(label="Full name", max_length=150)
    email = forms.EmailField(label="Email address", max_length=254)
    subject = forms.ChoiceField(label="Subject", choices=SUBJECT_CHOICES)
    phone = forms.CharField(label="Phone number", max_length=32, required=False)
    message = forms.CharField(label="Message", max_length=5000, widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["message"].widget.attrs["rows"] = 5
        for field in self.fields.values():
            field.widget.attrs["class"] = "sm-contact-input"
        self.fields["name"].widget.attrs.update(autocomplete="name", placeholder="Enter your full name")
        self.fields["email"].widget.attrs.update(autocomplete="email", placeholder="Enter your email address")
        self.fields["phone"].widget.attrs.update(autocomplete="tel", placeholder="Enter your phone number (optional)")
        self.fields["message"].widget.attrs["placeholder"] = "Type your message here..."
        self.fields["subject"].widget.attrs["aria-label"] = "Select a subject"

    def clean_name(self):
        value = self.cleaned_data["name"].strip()
        if not value:
            raise forms.ValidationError("Please enter your name.")
        return value

    def clean_message(self):
        value = self.cleaned_data["message"].strip()
        if len(value) < 10:
            raise forms.ValidationError("Please enter at least 10 characters.")
        return value
