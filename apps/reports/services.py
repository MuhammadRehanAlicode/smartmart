"""Report and dashboard queries. Everything is aggregated from database records."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, IntegerField, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.finance.calculations import DEC, ZERO, day_range, inventory_value, summary
from apps.finance.models import Expense
from apps.inventory.models import StockMovement
from apps.orders.models import Order, OrderItem
from apps.products.models import Product
from apps.purchases.models import Purchase, PurchaseItem
from apps.sales.models import Sale, SaleItem, SaleReturn, SaleReturnItem

MAX_DAYS = 366
ROW_LIMIT = 5000


@dataclass
class Section:
    title: str
    headers: list
    rows: list
    total: list = None
    empty: str = "No data for this period."


@dataclass
class ReportData:
    title: str
    sections: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def _q(qty_expr_a, qty_expr_b):
    return ExpressionWrapper(F(qty_expr_a) * F(qty_expr_b), output_field=DEC)


NET_UNITS = ExpressionWrapper(F("quantity") - F("quantity_returned"), output_field=IntegerField())
NET_REVENUE = ExpressionWrapper((F("quantity") - F("quantity_returned")) * F("sold_price"), output_field=DEC)


def daily_series(start, end):
    """One row per local day (zeros filled in): count, revenue, refunds, net, cogs, gross."""
    s, e = day_range(start, end)
    sales = {r["d"]: r for r in Sale.objects.filter(created_at__gte=s, created_at__lt=e)
             .annotate(d=TruncDate("created_at")).values("d").annotate(total=Sum("total"), n=Count("id")).order_by()}
    cost = {r["d"]: r["c"] for r in SaleItem.objects.filter(sale__created_at__gte=s, sale__created_at__lt=e)
            .annotate(d=TruncDate("sale__created_at")).values("d")
            .annotate(c=Sum(_q("quantity", "unit_cost"))).order_by()}
    refunds = {r["d"]: r["t"] for r in SaleReturn.objects.filter(created_at__gte=s, created_at__lt=e)
               .annotate(d=TruncDate("created_at")).values("d").annotate(t=Sum("refund_total")).order_by()}
    back = {r["d"]: r["c"] for r in SaleReturnItem.objects
            .filter(sale_return__created_at__gte=s, sale_return__created_at__lt=e, sale_return__restock=True)
            .annotate(d=TruncDate("sale_return__created_at")).values("d").annotate(c=Sum("cost_amount")).order_by()}
    orders = {r["d"]: r for r in Order.objects.filter(status="delivered", delivered_at__gte=s, delivered_at__lt=e)
              .annotate(d=TruncDate("delivered_at")).values("d").annotate(total=Sum("total"), n=Count("id")).order_by()}
    ocost = {r["d"]: r["c"] for r in OrderItem.objects.filter(order__status="delivered", order__delivered_at__gte=s, order__delivered_at__lt=e)
             .annotate(d=TruncDate("order__delivered_at")).values("d").annotate(c=Sum(_q("quantity", "unit_cost"))).order_by()}
    rows, d = [], start
    while d <= end:
        rev = ((sales.get(d) or {}).get("total") or ZERO) + ((orders.get(d) or {}).get("total") or ZERO)
        n = ((sales.get(d) or {}).get("n") or 0) + ((orders.get(d) or {}).get("n") or 0)
        ref = refunds.get(d) or ZERO
        cogs = (cost.get(d) or ZERO) + (ocost.get(d) or ZERO) - (back.get(d) or ZERO)
        rows.append({"date": d, "count": n, "revenue": rev, "refunds": ref, "net": rev - ref,
                     "cogs": cogs, "gross": rev - ref - cogs})
        d += timedelta(days=1)
    return rows


def _bucket(d, group):
    if group == "week":
        return d - timedelta(days=d.weekday())
    if group == "month":
        return d.replace(day=1)
    return d


def sales_report(start, end, params):
    group = params.get("group") if params.get("group") in ("day", "week", "month") else "day"
    buckets = {}
    for r in daily_series(start, end):
        b = buckets.setdefault(_bucket(r["date"], group), dict.fromkeys(("count", "revenue", "refunds", "net", "cogs", "gross"), 0))
        for k in b:
            b[k] += r[k]
    rows = [[k.isoformat(), v["count"], v["revenue"], v["refunds"], v["net"], v["cogs"], v["gross"]]
            for k, v in sorted(buckets.items()) if v["count"] or v["refunds"]]
    tot = [sum(r[i] for r in rows) if rows else 0 for i in range(1, 7)]
    label = {"day": "Day", "week": "Week starting", "month": "Month starting"}[group]
    return ReportData("Sales report", [Section(
        "", [label, "Sales", "Revenue", "Refunds", "Net revenue", "Cost of goods", "Gross profit"], rows,
        ["Total"] + tot)], ["Includes in-store sales and online orders (counted when delivered)."])


def profit_report(start, end, params):
    s = summary(start, end)
    rows = [
        ["Revenue", s.revenue, "Sale totals after product discounts"],
        ["Refunds", s.refunds, "Returns recorded in the period"],
        ["Net revenue", s.net_revenue, "Revenue − refunds"],
        ["Cost of goods sold", s.cogs, "Cost snapshot of units sold, minus restocked returns"],
        ["Gross profit", s.gross_profit, "Net revenue − cost of goods sold"],
        ["Expenses", s.expenses, "Recorded expenses (stock purchases are not expenses)"],
        ["Net profit", s.net_profit, "Gross profit − expenses"],
        ["Purchase expenditure", s.purchase_spend, "Stock purchases received in the period (not a cost until sold)"],
        ["Inventory value (now)", s.inventory_value, "Stock × latest purchase cost"],
    ]
    return ReportData("Profit report", [Section("", ["Measure", "Amount", "How it is calculated"], rows)],
                      ["Valuation uses the latest received purchase cost per base unit. See docs/ACCOUNTING.md and docs/VALUATION.md."])


def purchases_report(start, end, params):
    s, e = day_range(start, end)
    by_supplier = (PurchaseItem.objects.filter(purchase__status="received", purchase__received_at__gte=s, purchase__received_at__lt=e)
                   .values("purchase__supplier__name").annotate(
                       total=Sum(ExpressionWrapper(F("quantity") * F("unit_cost") + F("box_cost"), output_field=DEC)),
                       n=Count("purchase", distinct=True))
                   .order_by("-total"))
    sup_rows = [[r["purchase__supplier__name"], r["n"], r["total"]] for r in by_supplier]
    purchases = (Purchase.objects.filter(status="received", received_at__gte=s, received_at__lt=e)
                 .select_related("supplier").prefetch_related("items").order_by("-received_at"))
    rows = [[f"PUR-{p.pk}", timezone.localtime(p.received_at).strftime("%Y-%m-%d"), p.supplier.name,
             p.invoice_reference, p.total, p.amount_paid, p.balance_due] for p in purchases]
    return ReportData("Purchases report", [
        Section("By supplier", ["Supplier", "Purchases", "Total"], sup_rows, ["Total", sum(r[1] for r in sup_rows), sum((r[2] for r in sup_rows), ZERO)]),
        Section("Received purchases", ["No.", "Received", "Supplier", "Invoice", "Total", "Paid", "Due"], rows,
                ["Total", "", "", "", sum((r[4] for r in rows), ZERO), sum((r[5] for r in rows), ZERO), sum((r[6] for r in rows), ZERO)]),
    ])


def _net_sold(start, end):
    s, e = day_range(start, end)
    return {r["product_id"]: r for r in SaleItem.objects.filter(sale__created_at__gte=s, sale__created_at__lt=e)
            .values("product_id", "product_name").annotate(units=Sum(NET_UNITS), revenue=Sum(NET_REVENUE)).order_by()}


def best_sellers(start, end, limit=10):
    data = [r for r in _net_sold(start, end).values() if r["units"] and r["units"] > 0]
    return sorted(data, key=lambda r: (-r["units"], r["product_name"]))[:limit]


def dashboard_top_products(start, end, limit=5):
    """Top units sold across POS and delivered online orders for the selected dates."""
    s, e = day_range(start, end)
    combined = {}
    names = {}
    pos_rows = (SaleItem.objects.filter(sale__created_at__gte=s, sale__created_at__lt=e)
                .values("product_id", "product_name").annotate(units=Sum(NET_UNITS)))
    online_rows = (OrderItem.objects.filter(order__status=Order.Status.DELIVERED,
                                             order__delivered_at__gte=s, order__delivered_at__lt=e)
                   .values("product_id", "product_name").annotate(units=Sum("quantity")))
    for row in list(pos_rows) + list(online_rows):
        if row["units"] and row["units"] > 0:
            product_id = row["product_id"]
            combined[product_id] = combined.get(product_id, 0) + row["units"]
            names.setdefault(product_id, row["product_name"])
    product_map = Product.objects.in_bulk(combined)
    ranked = sorted(combined, key=lambda pk: (-combined[pk], names[pk].lower()))[:limit]
    return [{"product": product_map.get(pk), "product_name": names[pk], "units": combined[pk]}
            for pk in ranked]


def products_report(start, end, params):
    sold = _net_sold(start, end)
    best = [[r["product_name"], r["units"], r["revenue"]] for r in best_sellers(start, end, 20)]
    slow = []
    for p in Product.objects.filter(is_archived=False, stock_quantity__gt=0):
        units = (sold.get(p.pk) or {}).get("units") or 0
        slow.append([p.name, p.sku, p.stock_quantity, units, p.stock_value])
    slow.sort(key=lambda r: (r[3], -r[4]))
    return ReportData("Best-selling and slow-moving products", [
        Section("Best sellers (net of returns)", ["Product", "Units sold", "Revenue"], best),
        Section("Slow-moving (in stock, fewest sales first)", ["Product", "SKU", "In stock", "Units sold", "Stock value"], slow[:20]),
    ])


def stock_valuation_report(start, end, params):
    prods = Product.objects.filter(stock_quantity__gt=0).order_by("name")
    rows = [[p.name, p.sku, p.stock_quantity, p.cost_price, p.stock_value, "Archived" if p.is_archived else ""] for p in prods]
    return ReportData("Stock valuation (current)", [Section(
        "", ["Product", "SKU", "Quantity", "Latest cost", "Value", "Note"], rows,
        ["Total", "", sum(r[2] for r in rows), "", inventory_value(), ""])],
        ["Latest received purchase cost method. This report shows stock as it is now; dates are ignored."])


def movements_report(start, end, params):
    s, e = day_range(start, end)
    qs = StockMovement.objects.filter(created_at__gte=s, created_at__lt=e).select_related("product")
    if params.get("type") in StockMovement.Type.values:
        qs = qs.filter(movement_type=params["type"])
    rows = [[timezone.localtime(m.created_at).strftime("%Y-%m-%d %H:%M"), m.product.name, m.product.sku,
             m.get_movement_type_display(), m.quantity_change, m.balance_after, m.reason, m.reference]
            for m in qs[:ROW_LIMIT]]
    notes = [f"Showing the first {ROW_LIMIT} movements; narrow the dates."] if len(rows) == ROW_LIMIT else []
    return ReportData("Inventory movements", [Section("", ["When", "Product", "SKU", "Type", "Change", "Balance", "Reason", "Reference"], rows)], notes)


def expenses_report(start, end, params):
    qs = Expense.objects.filter(date__gte=start, date__lte=end)
    by_cat = {c.label: ZERO for c in Expense.Category}
    labels = dict(Expense.Category.choices)
    rows = []
    for x in qs:
        by_cat[labels[x.category]] += x.amount
        rows.append([x.date.isoformat(), labels[x.category], x.description, x.amount])
    cat_rows = [[k, v] for k, v in by_cat.items() if v]
    total = sum((r[3] for r in rows), ZERO)
    return ReportData("Expenses report", [
        Section("By category", ["Category", "Total"], cat_rows, ["Total", total]),
        Section("All expenses", ["Date", "Category", "Description", "Amount"], rows, ["Total", "", "", total]),
    ])


def channels_report(start, end, params):
    s = summary(start, end)
    ins_net = s.instore_revenue - s.refunds
    rows = [
        ["In-store", s.instore_count, s.instore_revenue, s.refunds, ins_net, s.instore_cogs, ins_net - s.instore_cogs],
        ["Online (delivered)", s.online_count, s.online_revenue, Decimal("0.00"), s.online_revenue, s.online_cogs, s.online_revenue - s.online_cogs],
    ]
    total = ["Total"] + [sum((r[i] for r in rows), ZERO) for i in range(1, 7)]
    return ReportData("Online vs in-store sales", [Section("", ["Channel", "Sales / orders", "Revenue", "Refunds", "Net revenue", "Cost of goods", "Gross profit"], rows, total)],
                      ["Online orders count when delivered. Cancelled or undelivered orders are not revenue. Refunds shown are POS returns."])


def returns_report(start, end, params):
    s, e = day_range(start, end)
    qs = SaleReturn.objects.filter(created_at__gte=s, created_at__lt=e).select_related("sale", "created_by")
    rows = [[r.sale.receipt_number, timezone.localtime(r.created_at).strftime("%Y-%m-%d"), r.reason,
             "Yes" if r.restock else "No", r.created_by.username if r.created_by else "", r.refund_total] for r in qs]
    return ReportData("Returns report", [Section("", ["Receipt", "Date", "Reason", "Restocked", "By", "Refund"], rows,
                                                 ["Total", "", "", "", "", sum((r[5] for r in rows), ZERO)])])


REPORTS = {
    "sales": ("Sales (daily, weekly, monthly)", sales_report, True),
    "profit": ("Gross and net profit", profit_report, True),
    "purchases": ("Purchases", purchases_report, True),
    "products": ("Best-selling and slow-moving products", products_report, True),
    "stock-valuation": ("Stock valuation", stock_valuation_report, False),
    "movements": ("Inventory movements", movements_report, True),
    "expenses": ("Expenses", expenses_report, True),
    "returns": ("Returns", returns_report, True),
    "channels": ("Online vs in-store sales", channels_report, True),
}


def parse_range(params, default_days=30):
    """Returns (start, end, error). Falls back to the last N days on bad input."""
    today = timezone.localdate()
    default = (today - timedelta(days=default_days - 1), today)
    try:
        start = date.fromisoformat(params["date_from"]) if params.get("date_from") else default[0]
        end = date.fromisoformat(params["date_to"]) if params.get("date_to") else default[1]
    except ValueError:
        return default[0], default[1], "Those dates were not understood, so the last 30 days are shown."
    if start > end:
        return default[0], default[1], "The start date is after the end date, so the last 30 days are shown."
    if (end - start).days >= MAX_DAYS:
        return default[0], default[1], "Please choose a range of at most one year; the last 30 days are shown."
    return start, end, None


def dashboard_stats(start, end, full):
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    live = Product.objects.filter(is_archived=False)
    stats = {
        "product_count": live.count(),
        "low_stock": list(live.filter(stock_quantity__gt=0, stock_quantity__lte=F("low_stock_threshold")).order_by("stock_quantity")[:8]),
        "out_of_stock": list(live.filter(stock_quantity=0).order_by("name")[:8]),
        "low_stock_count": live.filter(stock_quantity__gt=0, stock_quantity__lte=F("low_stock_threshold")).count(),
        "out_of_stock_count": live.filter(stock_quantity=0).count(),
        "recent_sales": list(Sale.objects.select_related("cashier")[:8]),
        "recent_orders": list(Order.objects.all()[:8]),
        "open_orders_count": Order.objects.exclude(status__in=["delivered", "cancelled"]).count(),
    }
    if full:
        stats.update(
            today=summary(today, today), week=summary(week_start, today), month=summary(month_start, today),
            best_sellers=best_sellers(start, end, 5), series=daily_series(start, end),
        )
    return stats
