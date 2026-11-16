from django.db import transaction
from decimal import Decimal

from django.utils import timezone

from apps.core.audit import log_action
from apps.inventory.models import StockMovement
from apps.inventory.services import change_stock

from .models import Purchase


class PurchaseError(Exception):
    pass


@transaction.atomic
def receive_purchase(purchase_id, user):
    """Stock increases here and ONLY here. Locks the purchase so it cannot be received twice."""
    purchase = Purchase.objects.select_for_update().get(pk=purchase_id)
    if purchase.status != Purchase.Status.PENDING:
        raise PurchaseError("Only pending purchases can be received.")
    items = list(purchase.items.select_related("product"))
    if not items:
        raise PurchaseError("This purchase has no items.")
    for item in items:
        conversion = item.conversion_factor or Decimal("1")
        base_qty = item.converted_quantity or item.quantity * conversion
        effective_unit_cost = item.line_total / base_qty if base_qty else item.unit_cost / conversion
        change_stock(item.product, base_qty, StockMovement.Type.PURCHASE, user=user,
                     reason=f"Purchase from {purchase.supplier.name}", reference=f"PUR-{purchase.pk}",
                     unit_cost=effective_unit_cost)
    purchase.status = Purchase.Status.RECEIVED
    purchase.received_at = timezone.now()
    purchase.save(update_fields=["status", "received_at"])
    log_action(user, "purchase.received", f"PUR-{purchase.pk}", total=str(purchase.total))
    return purchase


@transaction.atomic
def cancel_purchase(purchase_id, user):
    purchase = Purchase.objects.select_for_update().get(pk=purchase_id)
    if purchase.status != Purchase.Status.PENDING:
        raise PurchaseError("Only pending purchases can be cancelled.")
    purchase.status = Purchase.Status.CANCELLED
    purchase.save(update_fields=["status"])
    log_action(user, "purchase.cancelled", f"PUR-{purchase.pk}")
    return purchase
