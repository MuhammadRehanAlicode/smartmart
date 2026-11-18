from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DetailView, ListView
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone
from django.http import JsonResponse

from apps.accounts.permissions import OwnerRequiredMixin
from apps.core.audit import log_action
from apps.products.models import Product

from .forms import PurchaseForm, PurchaseItemFormSet
from .models import Purchase
from .services import PurchaseError, cancel_purchase, receive_purchase


class PurchaseListView(OwnerRequiredMixin, ListView):
    template_name = "purchases/list.html"
    paginate_by = 20
    context_object_name = "purchases"

    def get_queryset(self):
        qs = Purchase.objects.select_related("supplier").prefetch_related("items")
        s = self.request.GET.get("status", "")
        if s in Purchase.Status.values:
            qs = qs.filter(status=s)
        return qs

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["statuses"] = Purchase.Status.choices
        return ctx


class PurchaseDetailView(OwnerRequiredMixin, DetailView):
    model = Purchase
    template_name = "purchases/detail.html"

    def get_queryset(self):
        return Purchase.objects.select_related("supplier").prefetch_related("items__product")


class PurchaseProductStockView(OwnerRequiredMixin, View):
    def get(self, request, pk):
        product = get_object_or_404(Product, pk=pk, is_archived=False)
        return JsonResponse({"stock": str(product.stock_quantity), "base_unit": product.base_unit})


class PurchaseEditView(OwnerRequiredMixin, View):
    """Create (no pk) or edit (pk, pending only) a purchase with several line items."""

    def _render(self, request, form, formset, purchase):
        products = Product.objects.filter(is_archived=False).prefetch_related("unit_options")
        units = {}
        for product in products:
            configured = list(product.unit_options.filter(purchase_enabled=True))
            unit_data = [{"code": unit.unit_code, "label": unit.get_unit_code_display(),
                          "factor": str(unit.conversion_factor)} for unit in configured]
            if not any(unit["code"] == product.base_unit for unit in unit_data):
                unit_data.append({"code": product.base_unit, "label": product.get_base_unit_display(), "factor": "1"})
            units[str(product.pk)] = {"base": product.base_unit, "stock": str(product.stock_quantity), "units": unit_data}
        return render(request, "purchases/form.html", {"form": form, "formset": formset, "purchase": purchase,
            "purchase_date": purchase.created_at if purchase else timezone.localdate(),
            "product_units_json": units})

    def get(self, request, pk=None):
        purchase = get_object_or_404(Purchase, pk=pk) if pk else None
        if purchase and purchase.status != Purchase.Status.PENDING:
            messages.error(request, "Only pending purchases can be edited.")
            return redirect("purchases:detail", pk=pk)
        form = PurchaseForm(instance=purchase)
        return self._render(request, form, PurchaseItemFormSet(instance=form.instance), purchase)

    def post(self, request, pk=None):
        purchase = get_object_or_404(Purchase, pk=pk) if pk else None
        if purchase and purchase.status != Purchase.Status.PENDING:
            messages.error(request, "Only pending purchases can be edited.")
            return redirect("purchases:detail", pk=pk)
        form = PurchaseForm(request.POST, instance=purchase)
        formset = PurchaseItemFormSet(request.POST, instance=form.instance)
        if form.is_valid() and formset.is_valid():
            total = sum(
                (f.cleaned_data["quantity"] * f.cleaned_data["unit_cost"])
                    .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                for f in formset
                if f.cleaned_data and not f.cleaned_data.get("DELETE")
            )
            if form.cleaned_data["amount_paid"] > total:
                form.add_error("amount_paid", "Amount paid cannot exceed the purchase total.")
            else:
                with transaction.atomic():
                    obj = form.save(commit=False)
                    if obj.pk is None:
                        obj.created_by = request.user
                    obj.save()
                    formset.instance = obj
                    formset.save()
                log_action(request.user, "purchase.saved", f"PUR-{obj.pk}", total=str(total))
                messages.success(request, "Purchase saved. Stock increases when you mark it as received.")
                return redirect("purchases:detail", pk=obj.pk)
        return self._render(request, form, formset, purchase)


class PurchaseReceiveView(OwnerRequiredMixin, View):
    def post(self, request, pk):
        get_object_or_404(Purchase, pk=pk)
        try:
            receive_purchase(pk, request.user)
            messages.success(request, "Goods received and stock updated.")
        except PurchaseError as exc:
            messages.error(request, str(exc))
        return redirect("purchases:detail", pk=pk)


class PurchaseCancelView(OwnerRequiredMixin, View):
    def post(self, request, pk):
        get_object_or_404(Purchase, pk=pk)
        try:
            cancel_purchase(pk, request.user)
            messages.success(request, "Purchase cancelled.")
        except PurchaseError as exc:
            messages.error(request, str(exc))
        return redirect("purchases:detail", pk=pk)
