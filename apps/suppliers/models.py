from decimal import Decimal

from django.db import models

from apps.accounts.models import phone_validator


class Supplier(models.Model):
    name = models.CharField(max_length=150, unique=True)
    phone = models.CharField(max_length=16, blank=True, validators=[phone_validator])
    address = models.CharField(max_length=250, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def balance(self):
        """Amount we still owe: received purchase totals minus amounts paid."""
        received = self.purchases.filter(status="received").prefetch_related("items")
        return sum((p.total - p.amount_paid for p in received), Decimal("0.00"))
