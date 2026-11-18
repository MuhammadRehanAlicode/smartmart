from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import ValidationError

from .models import User


class TwoFactorAdminAuthenticationForm(AdminAuthenticationForm):
    """Keep superusers on the SmartMart login flow, which enforces TOTP."""

    def confirm_login_allowed(self, user):
        if user.is_superuser:
            raise ValidationError("Use the SmartMart sign-in page to access this account.")
        super().confirm_login_allowed(user)


admin.site.login_form = TwoFactorAdminAuthenticationForm


@admin.register(User)
class StoreUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "is_active")
    list_filter = ("role", "is_active")
    fieldsets = UserAdmin.fieldsets + (("Store", {"fields": ("role", "phone")}),)
