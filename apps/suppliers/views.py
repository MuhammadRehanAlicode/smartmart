from django.contrib import messages
from django.db.models import Q
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.accounts.permissions import OwnerRequiredMixin
from apps.core.audit import log_action

from .forms import SupplierForm
from .models import Supplier


class SupplierListView(OwnerRequiredMixin, ListView):
    model = Supplier
    template_name = "suppliers/list.html"
    context_object_name = "suppliers"

    def get_queryset(self):
        qs = super().get_queryset()
        if q := self.request.GET.get("q", "").strip():
            qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q))
        return qs


class SupplierDetailView(OwnerRequiredMixin, DetailView):
    model = Supplier
    template_name = "suppliers/detail.html"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["purchases"] = self.object.purchases.prefetch_related("items")[:50]
        return ctx


class SupplierCreateView(OwnerRequiredMixin, CreateView):
    form_class = SupplierForm
    template_name = "dashboard/generic_form.html"
    extra_context = {"title": "Add supplier", "back_url": reverse_lazy("suppliers:list")}

    def form_valid(self, form):
        r = super().form_valid(form)
        log_action(self.request.user, "supplier.created", self.object.name)
        messages.success(self.request, "Supplier added.")
        return r

    def get_success_url(self):
        return reverse("suppliers:detail", args=[self.object.pk])


class SupplierUpdateView(OwnerRequiredMixin, UpdateView):
    model = Supplier
    form_class = SupplierForm
    template_name = "dashboard/generic_form.html"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx.update(title=f"Edit {self.object.name}", back_url=reverse("suppliers:detail", args=[self.object.pk]))
        return ctx

    def form_valid(self, form):
        r = super().form_valid(form)
        messages.success(self.request, "Supplier saved.")
        return r

    def get_success_url(self):
        return reverse("suppliers:detail", args=[self.object.pk])
