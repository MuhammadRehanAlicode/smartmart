from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView
from django.http import HttpResponse, HttpResponseBadRequest
from django.template.loader import render_to_string
from django.utils.text import slugify
from barcode.errors import BarcodeError

from apps.accounts.permissions import OwnerRequiredMixin, StaffRequiredMixin
from apps.core.audit import log_action
from apps.inventory.forms import StockAdjustmentForm
from apps.inventory.models import StockMovement
from apps.inventory.services import InsufficientStock, adjust_stock, change_stock

from .barcodes import render_barcode, thermal_job
from .forms import BarcodeSheetForm, CategoryForm, ProductCreateForm, ProductForm, ProductUnitFormSet, ThermalLabelForm
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
        try:
            svg = render_barcode(product.barcode).decode("utf-8")
        except (BarcodeError, ValueError, UnicodeError, TypeError):
            return HttpResponseBadRequest("This barcode cannot be rendered as Code 128.")
        html = render_to_string("products/barcode_labels.html", {
            "product": product, "copies": range(copies), "barcode_svg": svg, "show_price": show_price,
        }, request=request)
        return HttpResponse(html)


class ProductBarcodeImageView(StaffRequiredMixin, View):
    def get(self, request, pk, image_format):
        product = get_object_or_404(Product, pk=pk)
        try:
            content = render_barcode(product.barcode, image_format)
        except (BarcodeError, ValueError, UnicodeError, TypeError):
            return HttpResponseBadRequest("This barcode cannot be rendered in the requested format.")
        mime = "image/png" if image_format == "png" else "image/svg+xml"
        response = HttpResponse(content, content_type=mime)
        disposition = "inline" if request.GET.get("inline") == "1" else "attachment"
        filename = slugify(product.sku) or f"product-{product.pk}"
        response["Content-Disposition"] = f'{disposition}; filename="{filename}-barcode.{image_format}"'
        response["X-Content-Type-Options"] = "nosniff"
        return response


class ProductBarcodePreviewView(StaffRequiredMixin, View):
    def get(self, request):
        value = request.GET.get("value", "")
        if not value or len(value) > 64:
            return HttpResponseBadRequest("Enter a barcode of 1 to 64 characters.")
        try:
            content = render_barcode(value, "png")
        except (BarcodeError, ValueError, UnicodeError, TypeError):
            return HttpResponseBadRequest("This value cannot be rendered as Code 128.")
        return HttpResponse(content, content_type="image/png")


class BarcodeManagementView(StaffRequiredMixin, View):
    template_name = "products/barcode_management.html"
    max_labels = 500

    def get_queryset(self, request):
        query = request.GET.get("q", "").strip()[:100]
        products = Product.objects.all().order_by("name", "pk")
        if query:
            products = products.filter(Q(name__icontains=query) | Q(sku__icontains=query) | Q(barcode__icontains=query))
        return products

    def context(self, request, *, form=None, selected=None, labels=None, message=""):
        products = self.get_queryset(request)
        selected_ids = set(selected or [])
        for product in products[:200]:
            product.barcode_source = "Manufacturer" if product.has_manufacturer_barcode else "Internal"
            product.selected_for_print = product.pk in selected_ids
        all_products = Product.objects.all()
        return {
            "products": products[:200], "query": request.GET.get("q", "").strip(),
            "total_barcodes": all_products.exclude(barcode__isnull=True).exclude(barcode="").count(),
            "manufacturer_barcodes": all_products.filter(has_manufacturer_barcode=True).exclude(barcode__isnull=True).exclude(barcode="").count(),
            "internal_barcodes": all_products.filter(has_manufacturer_barcode=False).exclude(barcode__isnull=True).exclude(barcode="").count(),
            "missing_barcodes": all_products.filter(Q(barcode__isnull=True) | Q(barcode="")).count(),
            "sheet_form": form or BarcodeSheetForm(), "labels": labels, "message": message,
        }

    def get(self, request):
        return render(request, self.template_name, self.context(request))

    def _selected(self, request):
        if request.POST.get("select_all") == "on":
            return self.get_queryset(request)[:200]
        raw_ids = request.POST.getlist("products")[:200]
        ids = [int(value) for value in raw_ids if value.isdigit()]
        return Product.objects.filter(pk__in=ids).order_by("name", "pk")

    def post(self, request):
        action = request.POST.get("action", "print")
        if action == "generate_missing":
            if not request.user.is_owner:
                raise PermissionDenied
            missing = self.get_queryset(request).filter(Q(barcode__isnull=True) | Q(barcode=""))[:200]
            for product in missing:
                product.has_manufacturer_barcode = False
                product.save(update_fields=["barcode", "has_manufacturer_barcode", "updated_at"])
            from urllib.parse import urlencode
            return redirect(f"{reverse('products:barcodes')}?{urlencode({'q': request.GET.get('q', '')})}")

        selected = list(self._selected(request))
        if not selected:
            return render(request, self.template_name, self.context(request, message="Select at least one product."), status=400)
        labels = []
        for product in selected:
            if not product.barcode:
                continue
            try:
                copies = int(request.POST.get(f"copies_{product.pk}", "1"))
            except (TypeError, ValueError):
                copies = 1
            copies = max(1, min(copies, self.max_labels))
            if len(labels) + copies > self.max_labels:
                return render(request, self.template_name, self.context(request, selected=[p.pk for p in selected],
                    message=f"A print job is limited to {self.max_labels} labels."), status=400)
            try:
                svg = render_barcode(product.barcode).decode("utf-8")
            except (BarcodeError, ValueError, UnicodeError, TypeError):
                continue
            labels.extend({"product": product, "barcode_svg": svg} for _ in range(copies))
        if not labels:
            return render(request, self.template_name, self.context(request, selected=[p.pk for p in selected],
                message="Selected products do not have barcodes that can be printed."), status=400)

        if action == "thermal":
            thermal_form = ThermalLabelForm(request.POST)
            if not thermal_form.is_valid():
                return render(request, self.template_name, self.context(request, form=BarcodeSheetForm(request.POST),
                    selected=[p.pk for p in selected], message="Check the thermal label settings."), status=400)
            settings = thermal_form.cleaned_data
            thermal_labels = [{"barcode": item["product"].barcode, "name": item["product"].name} for item in labels]
            try:
                payload = thermal_job(thermal_labels, printer=settings["printer"], width_mm=float(settings["thermal_width"]),
                                      height_mm=float(settings["thermal_height"]))
            except ValueError as exc:
                return render(request, self.template_name, self.context(request, selected=[p.pk for p in selected], message=str(exc)), status=400)
            response = HttpResponse(payload, content_type="text/plain; charset=us-ascii")
            response["Content-Disposition"] = f'attachment; filename="smartmart-labels.{settings["printer"]}"'
            return response

        form = BarcodeSheetForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self.context(request, form=form, selected=[p.pk for p in selected],
                message="Check the label sheet measurements."), status=400)
        return render(request, "products/barcode_sheet.html", {
            "labels": labels, "settings": form.cleaned_data, "currency": "Rs.",
        })


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
