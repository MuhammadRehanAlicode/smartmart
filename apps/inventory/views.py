from django.db.models import F, Q
from django.views.generic import ListView, TemplateView

from apps.accounts.permissions import StaffRequiredMixin
from apps.products.models import Product

from .models import StockMovement


class MovementListView(StaffRequiredMixin, ListView):
    template_name = "inventory/movements.html"
    paginate_by = 30
    context_object_name = "movements"

    def get_queryset(self):
        qs = StockMovement.objects.select_related("product", "created_by")
        q = self.request.GET.get("q", "").strip()
        t = self.request.GET.get("type", "")
        if q:
            qs = qs.filter(Q(product__name__icontains=q) | Q(product__sku__icontains=q))
        if t in StockMovement.Type.values:
            qs = qs.filter(movement_type=t)
        return qs

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["types"] = StockMovement.Type.choices
        return ctx


class StockAlertsView(StaffRequiredMixin, TemplateView):
    template_name = "inventory/alerts.html"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        live = Product.objects.filter(is_archived=False)
        ctx["out_of_stock"] = live.filter(stock_quantity=0)
        ctx["low_stock"] = live.filter(stock_quantity__gt=0, stock_quantity__lte=F("low_stock_threshold"))
        return ctx
