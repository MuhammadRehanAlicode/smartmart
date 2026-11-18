from django.db.models import F, Q
from django.http import JsonResponse
from django.urls import reverse
from django.views import View
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


class BarcodeLookupView(StaffRequiredMixin, View):
    def get(self, request):
        barcode = request.GET.get("barcode", "").strip()[:64]
        if not barcode:
            return JsonResponse({"error": "Enter or scan a barcode."}, status=400)
        product = Product.objects.filter(barcode=barcode, is_archived=False).first()
        if not product:
            return JsonResponse({"error": f"No active product found for barcode {barcode}."}, status=404)
        return JsonResponse({
            "id": product.pk, "name": product.name, "sku": product.sku, "barcode": product.barcode,
            "stock": str(product.stock_quantity), "base_unit": product.base_unit,
            "detail_url": reverse("products:detail", args=[product.pk]),
            "adjust_url": reverse("products:adjust", args=[product.pk]) if request.user.is_owner else "",
            "cached": False,
        })


class BarcodeInventoryView(StaffRequiredMixin, TemplateView):
    template_name = "inventory/barcode_lookup.html"
