from django.db import models


class Payment(models.Model):
    class Method(models.TextChoices):
        COD = "cod", "Cash on delivery"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="payments")
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.COD)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    provider_reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
