from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView
from django.http import HttpResponse
from django.template.loader import render_to_string

from apps.accounts.permissions import OwnerRequiredMixin, StaffRequiredMixin
from apps.core.audit import log_action
from apps.inventory.forms import StockAdjustmentForm
from apps.inventory.models import StockMovement
from apps.inventory.services import InsufficientStock, adjust_stock, change_stock

from .forms import CategoryForm, ProductCreateForm, ProductForm, ProductUnitFormSet
from .models import Category, Product, ProductUnit

PRICE_FIELDS = {"cost_price", "selling_price", "discount_percent"}


class ProductListView(StaffRequiredMixin, ListView):
    template_name = "products/list.html"
    paginate_by = 20
    context_object_name = "products"

    def get_queryset(self):
        g = self.request.GET
        qs = Product.objects.select_related("category")
        qs = qs if g.get("archived") == "1" else qs.filter(is_archived=False)
        if q := g.get("q", "").strip():
            qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode__icontains=q) | Q(product_code__icontains=q))
        if g.get("category", "").isdigit():
            qs = qs.filter(category_id=g["category"])
        if g.get("stock") == "low":
            qs = qs.filter(stock_quantity__gt=0, stock_quantity__lte=F("low_stock_threshold"))
        elif g.get("stock") == "out":
            qs = qs.filter(stock_quantity=0)
        return qs

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["categories"] = Category.objects.all()
        return ctx


class ProductDetailView(StaffRequiredMixin, DetailView):
    model = Product
    template_name = "products/detail.html"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["movements"] = self.object.movements.select_related("created_by")[:50]
        ctx["sales_history"] = self.object.sale_items.select_related("sale").order_by("-sale__created_at")[:20]
        ctx["purchase_history"] = self.object.purchase_items.select_related("purchase").order_by("-purchase__created_at")[:20]
        return ctx


class ProductBarcodeLabelView(StaffRequiredMixin, View):
    def get(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        try:
            copies = max(1, min(100, int(request.GET.get("copies", "1"))))
        except ValueError:
            copies = 1
        show_price = request.GET.get("show_price") == "on"
        # Keep barcode values verbatim; Code 128 supports the generated internal IDs
        # and the common printable manufacturer barcode character set.
        from barcode import get as get_barcode
        from barcode.writer import SVGWriter
        svg = get_barcode("code128", product.barcode, writer=SVGWriter()).render(
            {"module_width": 0.28, "module_height": 12, "quiet_zone": 2, "write_text": False}
        ).decode("utf-8")
        html = render_to_string("products/barcode_labels.html", {
            "product": product, "copies": range(copies), "barcode_svg": svg, "show_price": show_price,
        }, request=request)
        return HttpResponse(html)


class ProductCreateView(OwnerRequiredMixin, CreateView):
    form_class = ProductCreateForm
    template_name = "products/form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = ctx["form"]
        base = form.instance.base_unit or Product.Unit.PCS
        initial = [{"unit_code": base, "conversion_factor": 1, "purchase_enabled": True,
                    "sales_enabled": True, "selling_price": form.instance.selling_price or 0}]
        ctx["unit_formset"] = kwargs.get("unit_formset") or ProductUnitFormSet(
            self.request.POST or None, instance=form.instance, initial=initial)
        ctx.update(title="Add product", back_url=reverse("products:list"))
        return ctx

    def form_valid(self, form):
        initial = [{"unit_code": form.instance.base_unit, "conversion_factor": 1,
                    "purchase_enabled": True, "sales_enabled": True,
                    "selling_price": form.instance.selling_price}]
        form.instance.base_unit = form.cleaned_data["base_unit"]
        has_unit_data = ProductUnitFormSet().add_prefix("TOTAL_FORMS") in self.request.POST
        unit_formset = ProductUnitFormSet(self.request.POST if has_unit_data else None,
                                          instance=form.instance, initial=initial)
        if has_unit_data and not unit_formset.is_valid():
            return self.render_to_response(self.get_context_data(form=form, unit_formset=unit_formset))
        with transaction.atomic():
            self.object = form.save()
            if has_unit_data:
                unit_formset.instance = self.object
                unit_formset.save()
            else:
                ProductUnit.objects.update_or_create(product=self.object, unit_code=self.object.base_unit,
                    defaults={"conversion_factor": 1, "purchase_enabled": True, "sales_enabled": True,
                              "selling_price": self.object.selling_price})
            opening = form.cleaned_data["opening_stock"]
            if opening:
                change_stock(self.object, opening, StockMovement.Type.OPENING,
                             user=self.request.user, reason="Opening stock", unit_cost=self.object.cost_price)
        log_action(self.request.user, "product.created", self.object.sku)
        messages.success(self.request, f"“{self.object.name}” added.")
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        messages.error(self.request, "Product was not saved. Fix the highlighted fields, then save again.")
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse("products:detail", args=[self.object.pk])


class ProductUpdateView(OwnerRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = "products/form.html"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx.update(title=f"Edit {self.object.name}", back_url=reverse("products:detail", args=[self.object.pk]))
        ctx["unit_formset"] = kw.get("unit_formset") or ProductUnitFormSet(
            self.request.POST or None, instance=self.object)
        return ctx

    def form_valid(self, form):
        form.instance.base_unit = form.cleaned_data["base_unit"]
        has_unit_data = ProductUnitFormSet().add_prefix("TOTAL_FORMS") in self.request.POST
        unit_formset = ProductUnitFormSet(self.request.POST if has_unit_data else None, instance=form.instance)
        if has_unit_data and not unit_formset.is_valid():
            return self.render_to_response(self.get_context_data(form=form, unit_formset=unit_formset))
        changed = PRICE_FIELDS & set(form.changed_data)
        if changed:
            log_action(self.request.user, "product.price_changed", form.instance.sku,
                       changes={f: [str(form.initial.get(f)), str(form.cleaned_data[f])] for f in changed})
        with transaction.atomic():
            self.object = form.save()
            if has_unit_data:
                unit_formset.instance = self.object
                unit_formset.save()
            else:
                ProductUnit.objects.update_or_create(product=self.object, unit_code=self.object.base_unit,
                    defaults={"conversion_factor": 1, "purchase_enabled": True, "sales_enabled": True,
                              "selling_price": self.object.selling_price})
        messages.success(self.request, "Product saved.")
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("products:detail", args=[self.object.pk])


class ProductArchiveView(OwnerRequiredMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        product.is_archived = not product.is_archived
        product.save(update_fields=["is_archived", "updated_at"])
        log_action(request.user, "product.archived" if product.is_archived else "product.restored", product.sku)
        messages.success(request, f"Product {'archived' if product.is_archived else 'restored'}.")
        return redirect("products:detail", pk=pk)


class StockAdjustView(OwnerRequiredMixin, FormView):
    form_class = StockAdjustmentForm
    template_name = "dashboard/generic_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.product = get_object_or_404(Product, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx.update(title=f"Adjust stock: {self.product.name} (now {self.product.stock_quantity})",
                   back_url=reverse("products:detail", args=[self.product.pk]))
        return ctx

    def form_valid(self, form):
        try:
            adjust_stock(self.product, form.cleaned_data["quantity_change"], form.cleaned_data["reason"], self.request.user)
        except InsufficientStock as exc:
            form.add_error("quantity_change", str(exc))
            return self.form_invalid(form)
        log_action(self.request.user, "stock.adjusted", self.product.sku,
                   change=str(form.cleaned_data["quantity_change"]), reason=form.cleaned_data["reason"])
        messages.success(self.request, "Stock updated.")
        return redirect("products:detail", pk=self.product.pk)


class CategoryListView(StaffRequiredMixin, View):
    def _render(self, request, form):
        return render(request, "products/categories.html",
                      {"categories": Category.objects.all(), "form": form})

    def get(self, request):
        return self._render(request, CategoryForm())

    def post(self, request):
        if not request.user.is_owner:
            raise PermissionDenied
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Category added.")
            return redirect("products:categories")
        return self._render(request, form)
