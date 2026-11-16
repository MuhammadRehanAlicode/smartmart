from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User


class StyledFormMixin:
    def _style(self):
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input")


class LoginForm(StyledFormMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class CustomerRegistrationForm(StyledFormMixin, UserCreationForm):
    phone = forms.CharField(max_length=16, required=True, help_text="e.g. 03001234567")

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "phone")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["phone"].validators.extend(User._meta.get_field("phone").validators)
        self._style()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.CUSTOMER  # never taken from user input
        if commit:
            user.save()
        return user


class StaffCreateForm(StyledFormMixin, UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "phone", "duty")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["duty"].required = True
        self.fields["duty"].help_text = "For example: Cashier, Stock manager, or Sales assistant."
        self._style()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.STAFF
        if commit:
            user.save()
        return user


class StaffEditForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "phone", "duty")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["duty"].required = True
        self.fields["duty"].help_text = "For example: Cashier, Stock manager, or Sales assistant."
        self._style()
