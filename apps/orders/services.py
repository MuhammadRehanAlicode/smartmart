from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.audit import log_action
from apps.inventory.models import StockMovement
from apps.inventory.services import change_stock
from apps.payments.services import PaymentError, cancel_pending_payments, create_payment, mark_cash_collected
from apps.products.models import Product

from .models import Cart, CartItem, Order, OrderEvent, OrderItem

S = Order.Status
MAX_LINE_QTY = 100
ALLOWED = {
    S.PENDING: {S.CONFIRMED, S.CANCELLED},
    S.CONFIRMED: {S.PROCESSING, S.CANCELLED},
    S.PROCESSING: {S.OUT_FOR_DELIVERY, S.CANCELLED},
    S.OUT_FOR_DELIVERY: {S.DELIVERED, S.CANCELLED},
    S.DELIVERED: set(),
    S.CANCELLED: set(),
}


class OrderError(Exception):
    """Safe-to-show, user-correctable problem."""


# ---------------- cart ----------------
def storefront_products():
    return Product.objects.filter(is_archived=False, is_online=True).filter(
        Q(category__isnull=True) | Q(category__is_active=True)
    )


def get_cart(user):
    return Cart.objects.get_or_create(user=user)[0]


def cart_add(user, product_id, quantity):
    try:
        product = storefront_products().get(pk=product_id)
    except Product.DoesNotExist:
        raise OrderError("That product is not available.")
    if product.stock_quantity < 1:
        raise OrderError(f"{product.name} is out of stock.")
    cart = get_cart(user)
    item, _ = CartItem.objects.get_or_create(cart=cart, product=product, defaults={"quantity": 0})
    item.quantity = min(item.quantity + max(quantity, 1), product.stock_quantity, MAX_LINE_QTY)
    item.save(update_fields=["quantity"])
    return item


def cart_set(user, item_id, quantity):
    item = CartItem.objects.filter(cart__user=user, pk=item_id).select_related("product").first()
    if item is None:
        raise OrderError("That item is not in your cart.")
    if quantity <= 0:
        item.delete()
        return None
    item.quantity = min(quantity, max(item.product.stock_quantity, 1), MAX_LINE_QTY)
    item.save(update_fields=["quantity"])
    return item


def cart_totals(items):
    subtotal = sum((i.quantity * i.product.selling_price for i in items), Decimal("0.00"))
    goods = sum((i.quantity * i.product.discounted_price for i in items), Decimal("0.00"))
    fee = delivery_fee_for(goods) if items else Decimal("0.00")
    return {"subtotal": subtotal, "discount": subtotal - goods, "goods": goods, "delivery_fee": fee, "total": goods + fee}


def delivery_fee_for(goods_total):
    return Decimal("0.00") if goods_total >= settings.FREE_DELIVERY_THRESHOLD else settings.DELIVERY_FEE


# ---------------- placing orders ----------------
@transaction.atomic
def place_order(*, user, name, phone, address, instructions, idempotency_key):
    """Reserves stock and creates the order atomically. Returns (order, created)."""
    existing = Order.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.customer_id != user.pk:
            raise OrderError("This order could not be placed. Please refresh and try again.")
        return existing, False
    cart = Cart.objects.select_for_update().filter(user=user).first()
    existing = Order.objects.filter(idempotency_key=idempotency_key, customer=user).first()
    if existing:  # a concurrent identical submit finished while we waited for the cart lock
        return existing, False
    items = list(cart.items.select_related("product")) if cart else []
    if not items:
        raise OrderError("Your cart is empty.")

    order = Order.objects.create(customer=user, customer_name=name, phone=phone, address=address,
                                 delivery_instructions=instructions, idempotency_key=idempotency_key)
    subtotal = discount = Decimal("0.00")
    for item in sorted(items, key=lambda i: i.product_id):  # fixed lock order avoids deadlocks
        product = Product.objects.select_for_update().select_related("category").get(pk=item.product_id)
        if (product.is_archived or not product.is_online
                or (product.category_id and not product.category.is_active)):
            raise OrderError(f"“{product.name}” is no longer available online. Please remove it from your cart.")
        OrderItem.objects.create(
            order=order, product=product, product_name=product.name, sku=product.sku, quantity=item.quantity,
            unit_price=product.selling_price, discount_percent=product.discount_percent,
            sold_price=product.discounted_price, unit_cost=product.cost_price)
        change_stock(product, -item.quantity, StockMovement.Type.ONLINE_ORDER, user=user, reference=order.number)
        subtotal += product.selling_price * item.quantity
        discount += (product.selling_price - product.discounted_price) * item.quantity
    goods = subtotal - discount
    order.subtotal, order.discount_total = subtotal, discount
    order.delivery_fee = delivery_fee_for(goods)
    order.total = goods + order.delivery_fee
    order.save(update_fields=["subtotal", "discount_total", "delivery_fee", "total"])
    create_payment(order, order.payment_method)
    OrderEvent.objects.create(order=order, to_status=S.PENDING, changed_by=user, note="Order placed")
    cart.items.all().delete()
    log_action(user, "order.placed", order.number, total=str(order.total))
    return order, True


# ---------------- status changes ----------------
@transaction.atomic
def update_order_status(*, order_id, new_status, user, note="", by_customer=False):
    order = Order.objects.select_for_update().get(pk=order_id)
    if by_customer:
        if order.customer_id != user.pk or new_status != S.CANCELLED or not order.customer_can_cancel:
            raise OrderError("This order can no longer be cancelled online. Please contact the store.")
    if new_status not in ALLOWED[order.status]:
        raise OrderError(f"An order that is “{order.get_status_display()}” cannot be changed to that status.")
    note = (note or "").strip()[:200]
    old = order.status
    if new_status == S.CANCELLED:
        if not note and not by_customer:
            raise OrderError("Please give a reason for cancelling.")
        note = note or "Cancelled by customer"
        for item in order.items.select_related("product"):
            change_stock(item.product, item.quantity, StockMovement.Type.CANCELLATION, user=user,
                         reference=order.number, reason=note)
        cancel_pending_payments(order)
        order.cancel_reason, order.cancelled_at = note, timezone.now()
    elif new_status == S.DELIVERED:
        try:
            mark_cash_collected(order)
        except PaymentError as exc:
            raise OrderError(str(exc))
        order.delivered_at = timezone.now()
    order.status = new_status
    order.save()
    OrderEvent.objects.create(order=order, from_status=old, to_status=new_status, changed_by=user, note=note)
    log_action(user, "order.status_changed", order.number, old=old, new=new_status)
    return order
