from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from apps.products.models import Product


class Purchase(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT, related_name="purchases")
    invoice_reference = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"),
                                      validators=[MinValueValidator(Decimal("0"))])
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"PUR-{self.pk}"

    @property
    def total(self):
        return sum((i.line_total for i in self.items.all()), Decimal("0.00"))

    @property
    def balance_due(self):
        return self.total - self.amount_paid


class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("products.Product", on_delete=models.PROTECT, related_name="purchase_items")
    quantity = models.DecimalField(max_digits=14, decimal_places=6, validators=[MinValueValidator(Decimal("0.000001"))])
    unit_code = models.CharField(max_length=3, choices=Product.Unit.choices, default=Product.Unit.PCS)
    conversion_factor = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("1.000000"))
    converted_quantity = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal("0.000000"))
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.01"), validators=[MinValueValidator(Decimal("0.01"))])
    box_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True,
                                   validators=[MinValueValidator(Decimal("0"))])

    def save(self, *args, **kwargs):
        if self._state.adding and self.selling_price == Decimal("0.01"):
            self.selling_price = self.product.selling_price
        super().save(*args, **kwargs)

    @property
    def line_total(self):
        return (self.quantity * self.unit_cost + self.box_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def base_unit_label(self):
        return self.product.get_base_unit_display()
