from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.accounts.models import phone_validator

MONEY = {"max_digits": 12, "decimal_places": 2}


class Cart(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart")
    updated_at = models.DateTimeField(auto_now=True)


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("products.Product", on_delete=models.CASCADE, related_name="+")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["cart", "product"], name="one_line_per_product_in_cart")]
        ordering = ["id"]

    @property
    def line_total(self):
        return self.quantity * self.product.discounted_price


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        PROCESSING = "processing", "Processing"
        OUT_FOR_DELIVERY = "out_for_delivery", "Out for delivery"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    customer_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=16, validators=[phone_validator])
    address = models.TextField()
    delivery_instructions = models.CharField(max_length=300, blank=True)
    payment_method = models.CharField(max_length=10, default="cod")
    subtotal = models.DecimalField(**MONEY, default=Decimal("0.00"))        # at list price
    discount_total = models.DecimalField(**MONEY, default=Decimal("0.00"))
    delivery_fee = models.DecimalField(**MONEY, default=Decimal("0.00"))
    total = models.DecimalField(**MONEY, default=Decimal("0.00"))
    idempotency_key = models.UUIDField(unique=True)
    # "online" = placed through the normal checkout; "offline" = saved on the customer's device and synced later.
    source = models.CharField(max_length=10, default="online", db_index=True)
    client_created_at = models.DateTimeField(null=True, blank=True)  # when the customer pressed "Place order" offline
    cancel_reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    @property
    def number(self):
        return f"ORD-{self.pk:06d}"

    @property
    def customer_can_cancel(self):
        return self.status in (self.Status.PENDING, self.Status.CONFIRMED)

    def __str__(self):
        return self.number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("products.Product", on_delete=models.PROTECT, related_name="order_items")
    product_name = models.CharField(max_length=200)
    sku = models.CharField(max_length=50)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(**MONEY)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    sold_price = models.DecimalField(**MONEY)
    unit_cost = models.DecimalField(**MONEY)

    @property
    def line_total(self):
        return self.quantity * self.sold_price


class OrderEvent(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, choices=Order.Status.choices)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class OfflineOrderSync(models.Model):
    """Server-side record of every offline order the device has sent, so a retry always gets the same answer.

    The client-generated UUID is also the Order.idempotency_key, so a duplicate request can never create a second
    order or deduct stock twice. Only final outcomes are stored here (requires_attention answers are not final).
    """

    class Outcome(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected"

    client_order_id = models.UUIDField(unique=True)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    order = models.OneToOneField(Order, null=True, blank=True, on_delete=models.SET_NULL, related_name="offline_sync")
    reason_code = models.CharField(max_length=40, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    details = models.JSONField(default=dict, blank=True)
    client_created_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.client_order_id} {self.outcome}"
