"""Offline-first order synchronisation.

A device that was offline stores the order locally (IndexedDB) under a client-generated UUID and sends it here once
the connection returns. Nothing the client says about money or stock is trusted: prices, totals, availability and
stock are all recomputed from the database inside one transaction with the product rows locked.

Idempotency: the client UUID is stored as Order.idempotency_key (unique) and in OfflineOrderSync (unique), so
sending the same order any number of times creates one order and deducts stock once.

Answers (OfflineResult.body["status"]):
  confirmed           order exists (created now, or earlier - ``created`` tells which)
  rejected            final "no": product gone / out of stock / invalid. Nothing was written except a ledger row.
  requires_attention  not final: the customer must act (price went up, online payment needed, wrong account).
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.core.audit import log_action
from apps.inventory.models import StockMovement
from apps.inventory.services import InsufficientStock, change_stock
from apps.payments.services import create_payment
from apps.products.models import Product

from .models import Cart, CartItem, Order, OrderEvent, OrderItem, OfflineOrderSync
from .services import MAX_LINE_QTY, delivery_fee_for, get_cart, storefront_products

S = Order.Status
OFFLINE = "offline"


@dataclass
class OfflineResult:
    http_status: int
    body: dict


class _Stop(Exception):
    """Raised inside the transaction to roll everything back and answer with a business outcome."""

    def __init__(self, status, code, message, http_status=409, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.http_status, self.extra = status, code, message, http_status, extra

    def body(self, client_order_id):
        return {"status": self.status, "client_order_id": str(client_order_id), "reason_code": self.code,
                "reason": self.message, **self.extra}


def _confirmed(order, created):
    return OfflineResult(201 if created else 200, {
        "status": "confirmed", "client_order_id": str(order.idempotency_key), "order_id": order.pk,
        "order_number": order.number, "total": str(order.total), "created": created})


def _already_processed(user, cid):
    """The answer to an order we have seen before, or None."""
    sync = OfflineOrderSync.objects.select_related("order").filter(client_order_id=cid).first()
    if sync is not None:
        if sync.customer_id != user.pk:
            return _wrong_account(cid)
        if sync.outcome == OfflineOrderSync.Outcome.CONFIRMED and sync.order is not None:
            return _confirmed(sync.order, created=False)
        return OfflineResult(409, {"status": "rejected", "client_order_id": str(cid), "reason_code": sync.reason_code,
                                   "reason": sync.reason, **(sync.details or {})})
    order = Order.objects.filter(idempotency_key=cid).first()  # same id used by an online checkout
    if order is not None:
        return _confirmed(order, created=False) if order.customer_id == user.pk else _wrong_account(cid)
    return None


def _wrong_account(cid):
    return OfflineResult(403, {"status": "requires_attention", "client_order_id": str(cid),
                               "reason_code": "wrong_account",
                               "reason": "This order was saved by a different account. Sign in with that account to send it."})


def process_offline_order(*, user, data):
    """Validate, price and create one offline order. ``data`` is a validated OfflineOrderSerializer dict."""
    cid = data["client_order_id"]
    if data.get("customer_ref") not in (None, user.pk):
        return _wrong_account(cid)
    done = _already_processed(user, cid)
    if done is not None:
        return done
    try:
        with transaction.atomic():
            return _create(user, data)
    except _Stop as stop:
        if stop.status == "rejected":
            return _record_rejection(user, data, stop)
        return OfflineResult(stop.http_status, stop.body(cid))
    except IntegrityError:  # a concurrent request with the same UUID won the race
        done = _already_processed(user, cid)
        if done is not None:
            return done
        raise


def _record_rejection(user, data, stop):
    cid = data["client_order_id"]
    try:
        with transaction.atomic():
            OfflineOrderSync.objects.create(
                client_order_id=cid, customer=user, outcome=OfflineOrderSync.Outcome.REJECTED, reason_code=stop.code,
                reason=stop.message[:500], details=stop.extra, client_created_at=data.get("created_at"))
            log_action(user, "order.offline_rejected", str(cid), reason=stop.code)
    except IntegrityError:
        done = _already_processed(user, cid)
        if done is not None:
            return done
        raise
    return OfflineResult(stop.http_status, stop.body(cid))


def _create(user, data):
    cid = data["client_order_id"]
    if data["payment_method"] != "cod":
        raise _Stop("requires_attention", "payment_required",
                    "Online payment cannot be completed offline. Please place this order again while online.")

    wanted = {}
    for line in data["items"]:  # the same product listed twice is one line
        wanted[line["product_id"]] = wanted.get(line["product_id"], 0) + line["quantity"]
    if any(q > MAX_LINE_QTY for q in wanted.values()):
        raise _Stop("rejected", "invalid_quantity", f"You can order at most {MAX_LINE_QTY} of one product.")
    client_prices = {line["product_id"]: line.get("unit_price") for line in data["items"]}

    # Fixed lock order (by id) avoids deadlocks between concurrent syncs. of=("self",) locks only product rows.
    products = {p.pk: p for p in Product.objects.select_for_update(of=("self",)).select_related("category")
                .filter(pk__in=wanted.keys()).order_by("pk")}

    problems = []
    for pid in sorted(wanted):
        product = products.get(pid)
        if product is None:
            problems.append({"product_id": pid, "code": "unavailable", "message": "A product in this order no longer exists."})
        elif (product.is_archived or not product.is_online
              or (product.category_id and not product.category.is_active)):
            problems.append({"product_id": pid, "code": "unavailable",
                             "message": f"“{product.name}” is no longer available online."})
        elif product.stock_quantity < wanted[pid]:
            left = product.stock_quantity
            problems.append({"product_id": pid, "code": "insufficient_stock", "available": left,
                             "message": (f"“{product.name}” is out of stock." if left == 0
                                         else f"Only {left} of “{product.name}” in stock (you ordered {wanted[pid]}).")})
    if problems:
        raise _Stop("rejected", problems[0]["code"], " ".join(p["message"] for p in problems), items=problems)

    subtotal = discount = Decimal("0.00")
    for pid, qty in wanted.items():
        product = products[pid]
        subtotal += product.selling_price * qty
        discount += (product.selling_price - product.discounted_price) * qty
    goods = subtotal - discount
    fee = delivery_fee_for(goods)
    total = goods + fee

    limit = data.get("accepted_total")
    if limit is None:
        limit = data.get("client_total")
    if limit is not None and total > limit:  # a price rose: the customer must agree to the new total first
        changes = [{"product_id": pid, "name": products[pid].name, "unit_price": str(products[pid].discounted_price),
                    "client_unit_price": None if client_prices.get(pid) is None else str(client_prices[pid])}
                   for pid in sorted(wanted) if client_prices.get(pid) != products[pid].discounted_price]
        raise _Stop("requires_attention", "price_changed",
                    f"Prices changed since you ordered. The new total is Rs. {total}.",
                    server_total=str(total), items=changes)

    order = Order.objects.create(
        customer=user, customer_name=data["customer_name"].strip(), phone=data["phone"],
        address=data["address"].strip(), delivery_instructions=data.get("delivery_instructions", ""),
        payment_method="cod", idempotency_key=cid, source=OFFLINE, client_created_at=data.get("created_at"))
    for pid in sorted(wanted):
        product, qty = products[pid], wanted[pid]
        OrderItem.objects.create(
            order=order, product=product, product_name=product.name, sku=product.sku, quantity=qty,
            unit_price=product.selling_price, discount_percent=product.discount_percent,
            sold_price=product.discounted_price, unit_cost=product.cost_price)
        try:
            change_stock(product, -qty, StockMovement.Type.ONLINE_ORDER, user=user, reference=order.number)
        except InsufficientStock as exc:  # cannot happen after the check above; rolls everything back if it does
            raise _Stop("rejected", "insufficient_stock", str(exc))
    order.subtotal, order.discount_total, order.delivery_fee, order.total = subtotal, discount, fee, total
    order.save(update_fields=["subtotal", "discount_total", "delivery_fee", "total"])
    create_payment(order, "cod")
    OrderEvent.objects.create(order=order, to_status=S.PENDING, changed_by=user, note="Order placed offline, synced")
    OfflineOrderSync.objects.create(client_order_id=cid, customer=user, outcome=OfflineOrderSync.Outcome.CONFIRMED,
                                    order=order, client_created_at=data.get("created_at"))
    log_action(user, "order.placed", order.number, total=str(total), source=OFFLINE)
    return _confirmed(order, created=True)


# ---------------- cart helpers for the offline cart ----------------
def cart_snapshot(user):
    """The customer's server cart in the shape the offline cart stores. Also used to refresh the local copy."""
    from apps.store.templatetags.store_extras import product_art_url  # local import: store depends on orders

    items = list(get_cart(user).items.select_related("product__category"))
    return {"items": [{
        "product_id": i.product_id, "name": i.product.name, "sku": i.product.sku,
        "price": str(i.product.discounted_price), "list_price": str(i.product.selling_price),
        "image": i.product.image.url if i.product.image else product_art_url(i.product),
        "stock": i.product.stock_quantity, "quantity": i.quantity,
        "available": bool(i.product.is_online and not i.product.is_archived
                          and not (i.product.category_id and not i.product.category.is_active)),
    } for i in items]}


@transaction.atomic
def replace_cart(user, lines):
    """Make the server cart equal to what the customer built offline (clamped to real stock).

    Idempotent: sending the same lines twice leaves the same cart. Unavailable products are skipped and reported.
    """
    cart = Cart.objects.select_for_update().get_or_create(user=user)[0]
    wanted = {}
    for line in lines:
        wanted[line["product_id"]] = wanted.get(line["product_id"], 0) + line["quantity"]
    skipped = []
    keep = set()
    for pid, qty in wanted.items():
        product = storefront_products().filter(pk=pid).first()
        if product is None or product.stock_quantity < 1:
            skipped.append(pid)
            continue
        qty = min(qty, product.stock_quantity, MAX_LINE_QTY)
        item, _ = CartItem.objects.get_or_create(cart=cart, product=product, defaults={"quantity": qty})
        if item.quantity != qty:
            item.quantity = qty
            item.save(update_fields=["quantity"])
        keep.add(pid)
    cart.items.exclude(product_id__in=keep).delete()
    return skipped
