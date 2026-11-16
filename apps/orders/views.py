from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import DetailView, ListView

from apps.accounts.permissions import StaffRequiredMixin

from .models import Order
from .services import ALLOWED, OrderError, update_order_status


class OrderListView(StaffRequiredMixin, ListView):
    template_name = "orders/list.html"
    paginate_by = 25
    context_object_name = "orders"

    def get_queryset(self):
        qs = Order.objects.select_related("customer")
        g = self.request.GET
        if g.get("status") in Order.Status.values:
            qs = qs.filter(status=g["status"])
        q = g.get("q", "").strip()
        if q:
            digits = q.upper().replace("ORD-", "").lstrip("0")
            cond = (Q(customer_name__icontains=q) | Q(phone__icontains=q)
                    | Q(customer__username__icontains=q) | Q(customer__email__icontains=q))
            if digits.isdigit():
                cond |= Q(pk=int(digits))
            qs = qs.filter(cond)
        return qs

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["statuses"] = Order.Status.choices
        return ctx


class OrderDetailView(StaffRequiredMixin, DetailView):
    model = Order
    template_name = "orders/detail.html"

    def get_queryset(self):
        return Order.objects.select_related("customer").prefetch_related("items", "events__changed_by", "payments")

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        labels = dict(Order.Status.choices)
        ctx["next_statuses"] = [(s, labels[s]) for s in Order.Status.values if s in ALLOWED[self.object.status] and s != "cancelled"]
        ctx["can_cancel"] = "cancelled" in ALLOWED[self.object.status]
        return ctx


class OrderStatusView(StaffRequiredMixin, View):
    def post(self, request, pk):
        get_object_or_404(Order, pk=pk)
        try:
            update_order_status(order_id=pk, new_status=request.POST.get("status", ""), user=request.user,
                                note=request.POST.get("note", ""))
            messages.success(request, "Order updated.")
        except OrderError as exc:
            messages.error(request, str(exc))
        return redirect("orders:detail", pk=pk)
