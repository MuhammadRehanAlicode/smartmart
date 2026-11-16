from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction

from apps.core.audit import log_action
from apps.inventory.models import StockMovement
from apps.inventory.services import change_stock
from apps.products.models import Product

from .models import Sale, SaleItem, SaleReturn, SaleReturnItem


class SaleError(Exception):
    """A user-correctable problem (message is safe to show)."""


@transaction.atomic
def create_sale(*, user, items, payment_method, amount_tendered=None, idempotency_key=None):
    """Create unit-priced lines while tracking deductions in each product's base unit."""
    if idempotency_key:
        existing = Sale.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing
    if payment_method not in Sale.Method.values:
        raise SaleError("Choose a valid payment method.")

    merged = defaultdict(Decimal)
    for entry in items:
        product_id, qty = entry[0], entry[1]
        unit_code = entry[2] if len(entry) > 2 and entry[2] else ""
        try:
            quantity = Decimal(str(qty))
        except (InvalidOperation, ValueError, TypeError):
            raise SaleError("Enter a valid quantity.")
        if not quantity.is_finite() or quantity <= 0 or quantity > 10000 or quantity != quantity.quantize(Decimal("0.000001")):
            raise SaleError("Quantities must be greater than zero, up to 6 decimal places.")
        merged[(int(product_id), unit_code)] += quantity
    if not merged:
        raise SaleError("The cart is empty.")

    sale = Sale.objects.create(cashier=user, payment_method=payment_method, idempotency_key=idempotency_key)
    subtotal = discount = Decimal("0.00")
    for product_id, unit_code in sorted(merged):  # fixed lock order avoids deadlocks
        qty = merged[(product_id, unit_code)]
        try:
            product = Product.objects.select_for_update().get(pk=product_id, is_archived=False)
        except Product.DoesNotExist:
            raise SaleError("A product in the cart is no longer available.")
        selected_unit = unit_code or product.base_unit
        if selected_unit not in (product.base_unit, Product.Unit.CTN):
            raise SaleError(f"{selected_unit} is not compatible with {product.base_unit} inventory for {product.name}.")
        option = product.unit_options.filter(unit_code=selected_unit, sales_enabled=True).first()
        if option is None:
            if selected_unit == product.base_unit:
                factor, unit_price = Decimal("1"), product.selling_price
            else:
                raise SaleError(f"{selected_unit} is not an enabled sales unit for {product.name}.")
        else:
            factor, unit_price = option.conversion_factor, option.selling_price
        converted = (qty * factor).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        if converted <= 0:
            raise SaleError("This quantity is too small to convert into the product's base unit.")
        sold_price = (unit_price * (Decimal("100") - product.discount_percent) / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        SaleItem.objects.create(
            sale=sale, product=product, product_name=product.name, sku=product.sku, quantity=qty,
            unit_code=selected_unit, conversion_factor=factor, converted_quantity=converted,
            unit_price=unit_price, discount_percent=product.discount_percent,
            sold_price=sold_price, unit_cost=product.cost_price,
        )
        change_stock(product, -converted, StockMovement.Type.SALE, user=user, reference=sale.receipt_number)
        subtotal += (unit_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        discount += ((unit_price - sold_price) * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    total = subtotal - discount
    if amount_tendered is not None and amount_tendered < total:
        raise SaleError("The amount received is less than the total.")
    sale.subtotal, sale.discount_total, sale.total = subtotal, discount, total
    sale.amount_tendered = amount_tendered
    sale.save(update_fields=["subtotal", "discount_total", "total", "amount_tendered"])
    log_action(user, "sale.created", sale.receipt_number, total=str(total))
    return sale


@transaction.atomic
def create_return(*, sale_id, user, quantities, reason, restock=True):
    """quantities: {sale_item_id: quantity}. Refund = quantity x the price actually paid."""
    reason = (reason or "").strip()
    if not reason:
        raise SaleError("Please give a reason for the return.")
    lines = {}
    for key, value in quantities.items():
        try:
            quantity = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise SaleError("Enter a valid return quantity.")
        if not quantity.is_finite() or quantity > 10000 or quantity != quantity.quantize(Decimal("0.000001")):
            raise SaleError("Return quantities must be up to 6 decimal places.")
        if quantity > 0:
            lines[int(key)] = quantity
    if not lines:
        raise SaleError("Choose at least one item to return.")

    sale = Sale.objects.select_for_update().get(pk=sale_id)
    ret = SaleReturn.objects.create(sale=sale, created_by=user, reason=reason[:200], restock=restock)
    refund = Decimal("0.00")
    for item_id in sorted(lines):
        qty = lines[item_id]
        try:
            item = SaleItem.objects.select_for_update().get(pk=item_id, sale=sale)
        except SaleItem.DoesNotExist:
            raise SaleError("That item is not part of this sale.")
        if qty > item.returnable:
            raise SaleError(f"Only {item.returnable} of {item.product_name} can still be returned.")
        item.quantity_returned += qty
        item.save(update_fields=["quantity_returned"])
        converted = (qty * item.conversion_factor).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        amount = (qty * item.sold_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        SaleReturnItem.objects.create(sale_return=ret, sale_item=item, quantity=qty,
                                      converted_quantity=converted, refund_amount=amount, cost_amount=converted * item.unit_cost)
        if restock:
            change_stock(item.product, converted, StockMovement.Type.RETURN, user=user,
                         reference=sale.receipt_number, reason=reason[:200])
        refund += amount
    ret.refund_total = refund
    ret.save(update_fields=["refund_total"])
    log_action(user, "sale.returned", sale.receipt_number, refund=str(refund), restock=restock)
    return ret
