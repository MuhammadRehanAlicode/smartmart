from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from apps.accounts.models import User, phone_validator
from apps.core.audit import log_action
from apps.inventory.models import StockMovement
from apps.inventory.services import change_stock
from apps.orders.models import Order, OrderEvent
from apps.payments.models import Payment
from apps.products.models import Category, Product
from apps.purchases.models import Purchase, PurchaseItem
from apps.sales.models import Sale, SaleItem
from apps.suppliers.models import Supplier


def _is_owner(serializer):
    request = serializer.context.get("request")
    return bool(request and request.user.is_authenticated and request.user.role == "owner")


MONEY = {"max_digits": 12, "decimal_places": 2}


# ---------- users ----------
class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "first_name", "last_name", "email", "phone", "role")
        read_only_fields = ("id", "username", "role")


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "first_name", "last_name", "email", "phone", "date_joined")
        read_only_fields = fields


# ---------- catalogue ----------
class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "slug", "is_active")
        read_only_fields = ("slug",)


class ProductSerializer(serializers.ModelSerializer):
    discounted_price = serializers.DecimalField(read_only=True, **MONEY)
    opening_stock = serializers.IntegerField(write_only=True, required=False, min_value=0, default=0)
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.filter(is_active=True), allow_null=True, required=False)

    class Meta:
        model = Product
        fields = ("id", "name", "description", "category", "sku", "barcode", "image", "cost_price", "selling_price",
                  "has_manufacturer_barcode", "product_code", "discount_percent", "discounted_price", "stock_quantity", "low_stock_threshold", "is_online",
                  "is_archived", "opening_stock", "created_at", "updated_at")
        read_only_fields = ("product_code", "stock_quantity", "created_at", "updated_at")

    def validate_sku(self, value):
        value = value.strip().upper()
        qs = Product.objects.filter(sku=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A product with this SKU already exists.")
        return value

    def validate_barcode(self, value):
        value = (value or "").strip() or None
        if value:
            qs = Product.objects.filter(barcode=value)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError("A product with this barcode already exists.")
        return value

    def validate(self, attrs):
        if "has_manufacturer_barcode" not in attrs and attrs.get("barcode"):
            # Older API clients submit only a barcode; keep treating that value as
            # an explicit manufacturer barcode.
            attrs["has_manufacturer_barcode"] = True
        manufacturer = attrs.get("has_manufacturer_barcode", getattr(self.instance, "has_manufacturer_barcode", False))
        barcode = attrs.get("barcode", getattr(self.instance, "barcode", None))
        if manufacturer and not barcode:
            raise serializers.ValidationError({"barcode": "Enter the barcode printed on the product."})
        if not manufacturer and not self.instance:
            attrs["barcode"] = None
        elif not manufacturer and self.instance and self.instance.has_manufacturer_barcode:
            attrs["barcode"] = None
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not _is_owner(self):
            data.pop("cost_price", None)
        return data

    def create(self, validated_data):
        opening = validated_data.pop("opening_stock", 0)
        user = self.context["request"].user
        with transaction.atomic():
            product = super().create(validated_data)
            if opening:
                change_stock(product, opening, StockMovement.Type.OPENING, user=user, reason="Opening stock",
                             unit_cost=product.cost_price)
            log_action(user, "product.created", product.sku, via="api")
        return product

    def update(self, instance, validated_data):
        validated_data.pop("opening_stock", None)  # stock never changes through a plain update
        changed = {f: [str(getattr(instance, f)), str(validated_data[f])]
                   for f in ("cost_price", "selling_price", "discount_percent")
                   if f in validated_data and validated_data[f] != getattr(instance, f)}
        product = super().update(instance, validated_data)
        if changed:
            log_action(self.context["request"].user, "product.price_changed", product.sku, changes=changed, via="api")
        return product


class StockAdjustSerializer(serializers.Serializer):
    quantity_change = serializers.IntegerField()
    reason = serializers.CharField(max_length=200)

    def validate_quantity_change(self, v):
        if v == 0:
            raise serializers.ValidationError("Must not be zero.")
        return v


class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    movement_type_display = serializers.CharField(source="get_movement_type_display", read_only=True)

    class Meta:
        model = StockMovement
        fields = ("id", "product", "product_name", "movement_type", "movement_type_display", "quantity_change",
                  "balance_after", "reason", "reference", "created_at")
        read_only_fields = fields


# ---------- suppliers & purchases ----------
class SupplierSerializer(serializers.ModelSerializer):
    balance = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Supplier
        fields = ("id", "name", "phone", "address", "notes", "is_active", "balance", "created_at")
        read_only_fields = ("created_at",)


class PurchaseItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    line_total = serializers.DecimalField(read_only=True, **MONEY)

    class Meta:
        model = PurchaseItem
        fields = ("id", "product", "product_name", "quantity", "unit_cost", "line_total")


class PurchaseSerializer(serializers.ModelSerializer):
    items = PurchaseItemSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    balance_due = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Purchase
        fields = ("id", "supplier", "supplier_name", "invoice_reference", "status", "amount_paid", "total",
                  "balance_due", "notes", "items", "created_at", "received_at")
        read_only_fields = fields


class PurchaseItemInput(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_archived=False))
    quantity = serializers.IntegerField(min_value=1, max_value=1_000_000)
    unit_cost = serializers.DecimalField(min_value=Decimal("0.01"), **MONEY)


class PurchaseCreateSerializer(serializers.Serializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.filter(is_active=True))
    invoice_reference = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    amount_paid = serializers.DecimalField(min_value=Decimal("0"), default=Decimal("0.00"), **MONEY)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    items = PurchaseItemInput(many=True, allow_empty=False)

    def validate(self, data):
        total = sum((i["quantity"] * i["unit_cost"] for i in data["items"]), Decimal("0.00"))
        if data["amount_paid"] > total:
            raise serializers.ValidationError({"amount_paid": "Amount paid cannot exceed the purchase total."})
        return data

    def create(self, validated_data):
        items = validated_data.pop("items")
        with transaction.atomic():
            purchase = Purchase.objects.create(created_by=self.context["request"].user, **validated_data)
            PurchaseItem.objects.bulk_create([PurchaseItem(purchase=purchase, **i) for i in items])
            log_action(self.context["request"].user, "purchase.saved", f"PUR-{purchase.pk}", via="api")
        return purchase


# ---------- sales ----------
class SaleItemSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(read_only=True, **MONEY)

    class Meta:
        model = SaleItem
        fields = ("id", "product", "product_name", "sku", "quantity", "quantity_returned", "unit_price",
                  "discount_percent", "sold_price", "unit_cost", "line_total")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not _is_owner(self):
            data.pop("unit_cost", None)
        return data


class SaleSerializer(serializers.ModelSerializer):
    receipt_number = serializers.CharField(read_only=True)
    items = SaleItemSerializer(many=True, read_only=True)
    cashier = serializers.SerializerMethodField()
    change_due = serializers.DecimalField(read_only=True, allow_null=True, **MONEY)
    refunded_total = serializers.DecimalField(read_only=True, max_digits=14, decimal_places=2)

    class Meta:
        model = Sale
        fields = ("id", "receipt_number", "payment_method", "subtotal", "discount_total", "total", "amount_tendered",
                  "change_due", "refunded_total", "cashier", "items", "created_at")
        read_only_fields = fields

    def get_cashier(self, obj):
        return obj.cashier.username if obj.cashier else None


class SaleLineInput(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=10000)


class SaleCreateSerializer(serializers.Serializer):
    items = SaleLineInput(many=True, allow_empty=False, max_length=200)
    payment_method = serializers.ChoiceField(choices=Sale.Method.choices, default=Sale.Method.CASH)
    amount_tendered = serializers.DecimalField(min_value=Decimal("0"), required=False, allow_null=True, **MONEY)
    idempotency_key = serializers.UUIDField(required=False)


class ReturnLineInput(serializers.Serializer):
    sale_item_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=10000)


class ReturnCreateSerializer(serializers.Serializer):
    items = ReturnLineInput(many=True, allow_empty=False)
    reason = serializers.CharField(max_length=200)
    restock = serializers.BooleanField(default=True)


# ---------- orders ----------
class OrderItemSerializer(serializers.Serializer):
    product = serializers.IntegerField(source="product_id")
    product_name = serializers.CharField()
    sku = serializers.CharField()
    quantity = serializers.IntegerField()
    sold_price = serializers.DecimalField(**MONEY)
    line_total = serializers.DecimalField(**MONEY)


class OrderEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderEvent
        fields = ("from_status", "to_status", "note", "created_at")


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ("method", "status", "amount", "paid_at")


class OrderSerializer(serializers.ModelSerializer):
    number = serializers.CharField(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    events = OrderEventSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ("id", "number", "customer", "status", "status_display", "customer_name", "phone", "address",
                  "delivery_instructions", "payment_method", "subtotal", "discount_total", "delivery_fee", "total",
                  "items", "events", "payments", "cancel_reason", "created_at", "delivered_at")
        read_only_fields = fields


class OrderStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.Status.choices)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class OrderCancelSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class CartAddSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=100, default=1)


class CartQuantitySerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=0, max_value=100)


class CheckoutSerializer(serializers.Serializer):
    customer_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=16, validators=[phone_validator])
    address = serializers.CharField(min_length=8, max_length=500)
    delivery_instructions = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    idempotency_key = serializers.UUIDField()


# ---------- offline order sync ----------
class OfflineOrderItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=100)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)  # informational only
    currency = serializers.CharField(max_length=8, required=False, allow_blank=True)


class OfflineOrderSerializer(serializers.Serializer):
    """What a device sends for an order it saved while offline. Prices/totals are *claims*, never trusted."""
    client_order_id = serializers.UUIDField()
    customer_ref = serializers.IntegerField(required=False, allow_null=True)
    created_at = serializers.DateTimeField(required=False, allow_null=True)
    payment_method = serializers.CharField(max_length=10, default="cod")
    customer_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=16, validators=[phone_validator])
    address = serializers.CharField(min_length=8, max_length=500)
    delivery_instructions = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    items = OfflineOrderItemSerializer(many=True, allow_empty=False, max_length=100)
    client_total = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    accepted_total = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)


class OfflineCartLineSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=100)


class OfflineCartSerializer(serializers.Serializer):
    items = OfflineCartLineSerializer(many=True, allow_empty=True, max_length=200)
