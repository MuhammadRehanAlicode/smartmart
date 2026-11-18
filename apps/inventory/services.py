"""The ONLY place product stock may change.

Every change locks the product row (SELECT ... FOR UPDATE on PostgreSQL) inside a
transaction, refuses to go below zero, and writes a StockMovement ledger row.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction

from apps.products.models import Product

from .models import StockMovement


class InsufficientStock(Exception):
    pass


@transaction.atomic
def change_stock(product, delta, movement_type, *, user=None, reason="", reference="", unit_cost=None):
    try:
        delta = Decimal(str(delta)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Stock change must be a valid quantity.")
    if delta == 0:
        raise ValueError("Stock change must be non-zero.")
    locked = Product.objects.select_for_update().get(pk=product.pk)
    new_qty = locked.stock_quantity + delta
    if new_qty < 0:
        raise InsufficientStock(f"Only {locked.stock_quantity} of {locked.name} in stock.")

    fields = ["stock_quantity", "updated_at"]
    locked.stock_quantity = new_qty
    locked.save(update_fields=fields)

    movement = StockMovement.objects.create(
        product=locked, movement_type=movement_type, quantity_change=delta,
        balance_after=new_qty, unit_cost=unit_cost, reason=reason[:200],
        reference=reference[:64], created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    product.stock_quantity, product.cost_price = locked.stock_quantity, locked.cost_price
    return movement


def adjust_stock(product, delta, reason, user):
    if not (reason or "").strip():
        raise ValueError("A reason is required for stock adjustments.")
    return change_stock(product, delta, StockMovement.Type.ADJUSTMENT, user=user, reason=reason.strip())
