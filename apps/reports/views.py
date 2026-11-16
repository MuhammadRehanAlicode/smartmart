from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.permissions import OwnerRequiredMixin, StaffRequiredMixin
from apps.accounts.models import User
from apps.inventory.models import StockMovement
from apps.orders.models import Order
from apps.products.models import Product
from apps.finance.calculations import day_range

from .csv_utils import report_to_csv
from .services import REPORTS, dashboard_stats, dashboard_top_products, parse_range


class DashboardView(StaffRequiredMixin, TemplateView):
    template_name = "dashboard/home.html"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        full = self.request.user.is_owner
        preset = self.request.GET.get("days")
        params = self.request.GET
        if preset in ("7", "30", "90"):
            params = {}
        start, end, error = parse_range(params, int(preset) if preset in ("7", "30", "90") else 30)
        ctx.update(full=full, range_start=start, range_end=end, range_error=error, **dashboard_stats(start, end, full))
        ctx["dashboard_top_products"] = dashboard_top_products(start, end)
        ctx["sales_period_total"] = sum((row["net"] for row in ctx.get("series", [])), start=0)
        ctx["transactions_period_count"] = sum((row["count"] for row in ctx.get("series", [])), start=0)
        period_start, period_end = day_range(start, end)
        ctx["orders_period_count"] = Order.objects.filter(created_at__gte=period_start, created_at__lt=period_end).count()
        ctx["active_product_count"] = Product.objects.filter(is_archived=False, is_online=True).count()
        status_counts = dict(Order.objects.values("status").annotate(count=Count("pk")).values_list("status", "count"))
        delivered = status_counts.get(Order.Status.DELIVERED, 0)
        cancelled = status_counts.get(Order.Status.CANCELLED, 0)
        in_progress = sum(status_counts.get(status, 0) for status in (
            Order.Status.PENDING, Order.Status.CONFIRMED, Order.Status.PROCESSING, Order.Status.OUT_FOR_DELIVERY,
        ))
        order_total = delivered + in_progress + cancelled
        delivered_percent = round(delivered * 100 / order_total, 1) if order_total else 0
        progress_percent = round(in_progress * 100 / order_total, 1) if order_total else 0
        ctx.update(
            order_status_total=order_total,
            order_status_groups=[
                {"name": "Delivered", "count": delivered, "percentage": delivered_percent, "color": "#0b8f53"},
                {"name": "In progress", "count": in_progress, "percentage": progress_percent, "color": "#ffb83f"},
                {"name": "Cancelled", "count": cancelled,
                 "percentage": max(0, 100 - delivered_percent - progress_percent) if order_total else 0, "color": "#91a2aa"},
            ],
            dashboard_today=timezone.localdate(),
        )
        if full:
            ctx["chart_data"] = {
                "labels": [r["date"].isoformat() for r in ctx["series"]],
                "revenue": [float(r["net"]) for r in ctx["series"]],
                "gross": [float(r["gross"]) for r in ctx["series"]],
                "currency": "Rs.",
            }
            ctx["series_nonzero"] = [r for r in ctx["series"] if r["count"] or r["refunds"]]
        return ctx


class DashboardSearchView(StaffRequiredMixin, TemplateView):
    template_name = "dashboard/search.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get("q", "").strip()[:100]
        context["query"] = query
        context["product_results"] = []
        context["order_results"] = []
        context["customer_results"] = []
        if query:
            context["product_results"] = Product.objects.filter(is_archived=False).filter(
                Q(name__icontains=query) | Q(sku__icontains=query) | Q(barcode__icontains=query)
            )[:8]
            context["order_results"] = Order.objects.filter(
                Q(customer_name__icontains=query) | Q(phone__icontains=query)
                | Q(customer__username__icontains=query) | Q(customer__email__icontains=query)
            ).select_related("customer")[:8]
            context["customer_results"] = User.objects.filter(role=User.Role.CUSTOMER).filter(
                Q(username__icontains=query) | Q(first_name__icontains=query)
                | Q(last_name__icontains=query) | Q(phone__icontains=query) | Q(email__icontains=query)
            ).order_by("first_name", "last_name")[:8]
        return context


class ReportIndexView(OwnerRequiredMixin, TemplateView):
    template_name = "reports/index.html"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["reports"] = [(slug, title) for slug, (title, _, _) in REPORTS.items()]
        return ctx


class ReportView(OwnerRequiredMixin, View):
    def get(self, request, slug):
        if slug not in REPORTS:
            raise Http404
        title, func, uses_dates = REPORTS[slug]
        start, end, error = parse_range(request.GET)
        report = func(start, end, request.GET)
        if request.GET.get("format") == "csv":
            name = f"{slug}_{start.isoformat()}_{end.isoformat()}.csv" if uses_dates else f"{slug}_{timezone.localdate().isoformat()}.csv"
            return report_to_csv(report, name)
        return render(request, "reports/report.html", {
            "slug": slug, "report": report, "uses_dates": uses_dates, "range_start": start, "range_end": end,
            "range_error": error, "movement_types": StockMovement.Type.choices,
            "group": request.GET.get("group", "day"), "type": request.GET.get("type", ""),
        })
