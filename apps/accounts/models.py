from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models

phone_validator = RegexValidator(
    r"^\+?[0-9]{10,15}$",
    "Enter a valid phone number (10-15 digits, optional leading +).",
)


class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        STAFF = "staff", "Cashier / Staff"
        CUSTOMER = "customer", "Customer"

    role = models.CharField(max_length=16, choices=Role.choices, default=Role.CUSTOMER, db_index=True)
    phone = models.CharField(max_length=16, blank=True, validators=[phone_validator])
    duty = models.CharField(max_length=120, blank=True, default="")
    totp_secret_encrypted = models.TextField(blank=True, default="")
    totp_confirmed_at = models.DateTimeField(null=True, blank=True)
    totp_last_step = models.BigIntegerField(null=True, blank=True)
    totp_last_verified_at = models.DateTimeField(null=True, blank=True)
    recovery_code_hashes = models.JSONField(default=list, blank=True)

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.OWNER
        super().save(*args, **kwargs)

    @property
    def is_owner(self):
        # Superusers must retain owner access even if their saved role predates
        # the role-sync logic in save().
        return self.is_superuser or self.role == self.Role.OWNER

    @property
    def is_store_staff(self):
        """Owner or cashier: may use the back-office dashboard."""
        return self.is_owner or self.role == self.Role.STAFF

    @property
    def is_customer(self):
        return self.role == self.Role.CUSTOMER
