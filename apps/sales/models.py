from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from apps.products.models import Product

MONEY = {"max_digits": 12, "decimal_places": 2}


class Sale(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        WALLET = "wallet", "Mobile wallet"
        OTHER = "other", "Other"

    payment_method = models.CharField(max_length=10, choices=Method.choices, default=Method.CASH)
    subtotal = models.DecimalField(**MONEY, default=Decimal("0.00"))        # at list price
    discount_total = models.DecimalField(**MONEY, default=Decimal("0.00"))
    total = models.DecimalField(**MONEY, default=Decimal("0.00"))           # what the customer paid
    amount_tendered = models.DecimalField(**MONEY, null=True, blank=True)
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    # Stops a double-clicked / retried checkout from creating two sales.
    idempotency_key = models.UUIDField(null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    @property
    def receipt_number(self):
        return f"S-{self.pk:06d}"

    @property
    def change_due(self):
        if self.amount_tendered is None:
            return None
        return self.amount_tendered - self.total

    @property
    def refunded_total(self):
        return sum((r.refund_total for r in self.returns.all()), Decimal("0.00"))

    def __str__(self):
        return self.receipt_number


class SaleItem(models.Model):
    """Snapshot of price and cost at the moment of sale; never changes afterwards."""

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("products.Product", on_delete=models.PROTECT, related_name="sale_items")
    product_name = models.CharField(max_length=200)
    sku = models.CharField(max_length=50)
    quantity = models.DecimalField(max_digits=14, decimal_places=6, validators=[MinValueValidator(Decimal("0.000001"))])
    quantity_returned = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal("0.000000"))
    unit_code = models.CharField(max_length=3, choices=Product.Unit.choices, default=Product.Unit.PCS)
    conversion_factor = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("1.000000"))
    converted_quantity = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal("0.000000"))
    unit_price = models.DecimalField(**MONEY)           # list price at sale time
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    sold_price = models.DecimalField(**MONEY)           # price actually charged per unit
    unit_cost = models.DecimalField(**MONEY)            # weighted-average cost at sale time

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(quantity_returned__lte=F("quantity")), name="sale_item_return_lte_qty"),
        ]

    @property
    def line_total(self):
        return self.quantity * self.sold_price

    @property
    def returnable(self):
        return self.quantity - self.quantity_returned


class SaleReturn(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="returns")
    reason = models.CharField(max_length=200)
    restock = models.BooleanField(default=True, help_text="Put the items back into stock.")
    refund_total = models.DecimalField(**MONEY, default=Decimal("0.00"))
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class SaleReturnItem(models.Model):
    sale_return = models.ForeignKey(SaleReturn, on_delete=models.CASCADE, related_name="items")
    sale_item = models.ForeignKey(SaleItem, on_delete=models.PROTECT, related_name="return_items")
    quantity = models.DecimalField(max_digits=14, decimal_places=6, validators=[MinValueValidator(Decimal("0.000001"))])
    converted_quantity = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal("0.000000"))
    refund_amount = models.DecimalField(**MONEY)
    cost_amount = models.DecimalField(**MONEY)          # cost of the returned units (reversed from COGS only if restocked)
