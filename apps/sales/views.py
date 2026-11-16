import json
import uuid
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import IntegrityError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from apps.accounts.permissions import OwnerRequiredMixin, StaffRequiredMixin
from apps.inventory.services import InsufficientStock
from apps.products.models import Product

from .models import Sale
from .services import SaleError, create_return, create_sale


class PosView(StaffRequiredMixin, TemplateView):
    template_name = "sales/pos.html"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["methods"] = Sale.Method.choices
        return ctx


class ProductSearchApi(StaffRequiredMixin, View):
    def get(self, request):
        q = request.GET.get("q", "").strip()
        if not q:
            return JsonResponse({"results": []})
        qs = Product.objects.filter(is_archived=False).filter(barcode=q)
        if not qs.exists() and request.GET.get("scan") != "1":
            qs = Product.objects.filter(is_archived=False).filter(
                Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode__icontains=q) | Q(product_code__icontains=q)
            ).order_by("name")[:10]
        return JsonResponse({"results": [
            {"id": p.pk, "name": p.name, "sku": p.sku, "barcode": p.barcode or "", "product_code": p.product_code,
             "price": str(p.discounted_price), "list_price": str(p.selling_price), "stock": str(p.stock_quantity),
             "base_unit": p.base_unit, "units": [
                 {"code": unit.unit_code, "label": unit.get_unit_code_display(),
                 "factor": str(unit.conversion_factor), "price": str(unit.selling_price),
                 "sale_price": str(unit.selling_price * (Decimal("100") - p.discount_percent) / Decimal("100"))}
                 for unit in p.unit_options.filter(sales_enabled=True)
             ] or [{"code": p.base_unit, "label": p.get_base_unit_display(), "factor": "1",
                    "price": str(p.selling_price), "sale_price": str(p.discounted_price)}]}
            for p in qs
        ]})


class CheckoutApi(StaffRequiredMixin, View):
    def post(self, request):
        try:
            payload = json.loads(request.body or b"{}")
            raw_items = payload["items"]
            items = [(int(i["product_id"]), i["quantity"], i.get("unit_code")) for i in raw_items]
            key = uuid.UUID(payload["idempotency_key"]) if payload.get("idempotency_key") else None
            tendered = payload.get("amount_tendered")
            tendered = Decimal(str(tendered)) if tendered not in (None, "") else None
            if tendered is not None and (not tendered.is_finite() or tendered < 0):
                raise ValueError
        except (ValueError, KeyError, TypeError, InvalidOperation, json.JSONDecodeError):
            return JsonResponse({"error": "The sale could not be read. Please refresh and try again."}, status=400)
        try:
            sale = create_sale(user=request.user, items=items, payment_method=payload.get("payment_method", ""),
                               amount_tendered=tendered, idempotency_key=key)
        except (SaleError, InsufficientStock) as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        except IntegrityError:  # same key submitted twice at once: return the first sale
            sale = get_object_or_404(Sale, idempotency_key=key)
        return JsonResponse({"ok": True, "receipt_url": reverse("sales:receipt", args=[sale.pk])}, status=201)


class SaleListView(StaffRequiredMixin, ListView):
    template_name = "sales/list.html"
    paginate_by = 25
    context_object_name = "sales"

    def get_queryset(self):
        qs = Sale.objects.select_related("cashier")
        g = self.request.GET
        if g.get("date_from"):
            qs = qs.filter(created_at__date__gte=g["date_from"]) if _valid_date(g["date_from"]) else qs
        if g.get("date_to"):
            qs = qs.filter(created_at__date__lte=g["date_to"]) if _valid_date(g["date_to"]) else qs
        if g.get("q", "").strip().upper().lstrip("S-").isdigit():
            qs = qs.filter(pk=int(g["q"].strip().upper().lstrip("S-")))
        return qs


def _valid_date(value):
    from datetime import date
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


class ReceiptView(StaffRequiredMixin, DetailView):
    model = Sale
    template_name = "sales/receipt.html"

    def get_queryset(self):
        return Sale.objects.select_related("cashier").prefetch_related("items", "returns")


class ReturnView(OwnerRequiredMixin, View):
    """Returns change stock and money, so they are owner-only."""

    def _sale(self, pk):
        return get_object_or_404(Sale.objects.prefetch_related("items"), pk=pk)

    def get(self, request, pk):
        return render(request, "sales/return_form.html", {"sale": self._sale(pk)})

    def post(self, request, pk):
        sale = self._sale(pk)
        quantities = {}
        try:
            for item in sale.items.all():
                raw = request.POST.get(f"qty_{item.pk}", "").strip()
                quantities[item.pk] = Decimal(raw) if raw else Decimal("0")
                if not quantities[item.pk].is_finite() or quantities[item.pk] < 0:
                    raise ValueError
            create_return(sale_id=sale.pk, user=request.user, quantities=quantities,
                          reason=request.POST.get("reason", ""), restock=request.POST.get("restock") == "on")
        except (ValueError, InvalidOperation):
            messages.error(request, "Enter valid non-negative quantities (up to 6 decimal places).")
            return render(request, "sales/return_form.html", {"sale": sale}, status=400)
        except (SaleError, InsufficientStock) as exc:
            messages.error(request, str(exc))
            return render(request, "sales/return_form.html", {"sale": sale}, status=400)
        messages.success(request, "Return recorded.")
        return redirect("sales:receipt", pk=sale.pk)
