"""All money figures come from database records through these functions (see docs/ACCOUNTING.md).

Definitions (cash basis, per date range):
  revenue            = in-store sale totals created in the range + online orders DELIVERED in the range
                       (online revenue is recognised on delivery, when cash on delivery is collected;
                        delivery fees are counted as revenue; courier costs belong in expenses)
  refunds            = sum of refunds recorded in the range
  net_revenue        = revenue - refunds
  cogs               = cost snapshot of units sold (in-store + delivered online) in the range
                       - cost of units returned *and restocked* in the range
  gross_profit       = net_revenue - cogs
  expenses           = recorded expenses dated in the range (purchases of stock are NOT expenses)
  net_profit         = gross_profit - expenses
  purchase_spend     = value of purchases marked received in the range (cash going to stock, not a cost until sold)
  inventory_value    = sum(stock_quantity x weighted-average cost) right now
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone

from apps.orders.models import Order, OrderItem
from apps.products.models import Product
from apps.purchases.models import PurchaseItem
from apps.sales.models import Sale, SaleItem, SaleReturn, SaleReturnItem

from .models import Expense

ZERO = Decimal("0.00")
DEC = DecimalField(max_digits=16, decimal_places=2)


def day_range(start, end):
    """Inclusive local dates -> aware [start, end) datetimes."""
    tz = timezone.get_current_timezone()
    return (
        timezone.make_aware(datetime.combine(start, time.min), tz),
        timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz),
    )


def _sum(qs, expr):
    return qs.aggregate(v=Sum(expr, output_field=DEC))["v"] or ZERO


@dataclass
class FinancialSummary:
    revenue: Decimal
    refunds: Decimal
    net_revenue: Decimal
    cogs: Decimal
    gross_profit: Decimal
    expenses: Decimal
    net_profit: Decimal
    purchase_spend: Decimal
    inventory_value: Decimal
    sales_count: int
    instore_revenue: Decimal
    online_revenue: Decimal
    instore_cogs: Decimal
    online_cogs: Decimal
    instore_count: int
    online_count: int


def inventory_value():
    return _sum(Product.objects.all(), ExpressionWrapper(F("stock_quantity") * F("cost_price"), output_field=DEC))


def summary(start_date, end_date):
    start, end = day_range(start_date, end_date)
    sales = Sale.objects.filter(created_at__gte=start, created_at__lt=end)
    revenue = _sum(sales, F("total"))
    refunds = _sum(SaleReturn.objects.filter(created_at__gte=start, created_at__lt=end), F("refund_total"))
    sold_cost = _sum(
        SaleItem.objects.filter(sale__created_at__gte=start, sale__created_at__lt=end),
        ExpressionWrapper(F("quantity") * F("unit_cost"), output_field=DEC),
    )
    returned_cost = _sum(
        SaleReturnItem.objects.filter(sale_return__created_at__gte=start, sale_return__created_at__lt=end,
                                      sale_return__restock=True),
        F("cost_amount"),
    )
    expenses = _sum(Expense.objects.filter(date__gte=start_date, date__lte=end_date), F("amount"))
    purchase_spend = _sum(
        PurchaseItem.objects.filter(purchase__status="received", purchase__received_at__gte=start,
                                    purchase__received_at__lt=end),
        ExpressionWrapper(F("quantity") * F("unit_cost") + F("box_cost"), output_field=DEC),
    )
    online = Order.objects.filter(status="delivered", delivered_at__gte=start, delivered_at__lt=end)
    online_revenue = _sum(online, F("total"))
    online_cogs = _sum(
        OrderItem.objects.filter(order__status="delivered", order__delivered_at__gte=start, order__delivered_at__lt=end),
        ExpressionWrapper(F("quantity") * F("unit_cost"), output_field=DEC),
    )
    instore_cogs = sold_cost - returned_cost
    instore_revenue = revenue
    revenue = instore_revenue + online_revenue
    net_revenue = revenue - refunds
    cogs = instore_cogs + online_cogs
    gross = net_revenue - cogs
    instore_count, online_count = sales.count(), online.count()
    return FinancialSummary(
        revenue=revenue, refunds=refunds, net_revenue=net_revenue, cogs=cogs, gross_profit=gross,
        expenses=expenses, net_profit=gross - expenses, purchase_spend=purchase_spend,
        inventory_value=inventory_value(), sales_count=instore_count + online_count,
        instore_revenue=instore_revenue, online_revenue=online_revenue, instore_cogs=instore_cogs,
        online_cogs=online_cogs, instore_count=instore_count, online_count=online_count,
    )
