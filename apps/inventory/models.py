from django.conf import settings
from django.db import models


class StockMovement(models.Model):
    class Type(models.TextChoices):
        OPENING = "opening", "Opening stock"
        PURCHASE = "purchase", "Purchase received"
        SALE = "sale", "In-store sale"
        ONLINE_ORDER = "online_order", "Online order"
        RETURN = "return", "Return"
        CANCELLATION = "cancellation", "Order cancelled"
        ADJUSTMENT = "adjustment", "Adjustment"

    product = models.ForeignKey("products.Product", on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=16, choices=Type.choices, db_index=True)
    quantity_change = models.DecimalField(max_digits=14, decimal_places=6)
    balance_after = models.DecimalField(max_digits=14, decimal_places=6)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    reason = models.CharField(max_length=200, blank=True)
    reference = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.product_id} {self.quantity_change:+d} ({self.movement_type})"
