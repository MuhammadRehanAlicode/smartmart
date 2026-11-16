import uuid
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.core.mail import send_mail
from django.http import HttpResponse, JsonResponse
from django.db import IntegrityError
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from apps.accounts.permissions import OwnerRequiredMixin, RoleRequiredMixin
from apps.customers.forms import ProfileForm
from apps.customers.models import CustomerProfile
from apps.inventory.services import InsufficientStock
from apps.orders.models import CartItem, Order
from apps.orders.services import (OrderError, cart_add, cart_set, cart_totals, get_cart, place_order,
                                  storefront_products, update_order_status)
from apps.products.models import Category, Product
from apps.sales.models import SaleItem
from apps.orders.models import OrderItem

from .forms import CheckoutForm, ContactForm
from .forms import HeroBannerEditForm, HeroBannerUploadForm
from .models import HeroBanner
from .pending import clear_pending, is_ajax, remember_pending


class CustomerRequiredMixin(RoleRequiredMixin):
    # Store owners may also place storefront orders from the shop UI.
    allowed_roles = ("customer", "owner")


class HeroBannerManageView(OwnerRequiredMixin, View):
    template_name = "store/dashboard_banners.html"

    def get(self, request):
        return self.render_page(request)

    def render_page(self, request, *, upload_form=None, edit_form=None):
        banners = HeroBanner.objects.all()
        edit_forms = [
            (banner, edit_form if edit_form and edit_form.instance.pk == banner.pk else
             HeroBannerEditForm(instance=banner, prefix=f"banner-{banner.pk}"))
            for banner in banners
        ]
        next_order = max((banner.sort_order for banner in banners), default=-1) + 1
        return render(request, self.template_name, {
            "banners": banners,
            "edit_forms": edit_forms,
            "upload_form": upload_form or HeroBannerUploadForm(initial={"sort_order": next_order}, prefix="upload"),
        })

    def post(self, request):
        action = request.POST.get("action")
        if action == "add":
            form = HeroBannerUploadForm(request.POST, request.FILES, prefix="upload")
            if form.is_valid():
                form.save()
                messages.success(request, "Banner added to the homepage carousel.")
                return redirect("store_banners:manage")
            return self.render_page(request, upload_form=form)

        banner = get_object_or_404(HeroBanner, pk=request.POST.get("banner_id"))
        if action == "update":
            form = HeroBannerEditForm(request.POST, request.FILES, instance=banner, prefix=f"banner-{banner.pk}")
            if form.is_valid():
                form.save()
                messages.success(request, "Banner settings updated.")
            else:
                messages.error(request, "Banner was not updated. Check the highlighted fields.")
                return self.render_page(request, edit_form=form)
        elif action == "delete":
            banner.delete()
            messages.success(request, "Banner removed from the homepage carousel. Its media file was kept.")
        return redirect("store_banners:manage")


def _with_popularity(qs):
    sale_units = SaleItem.objects.filter(product=OuterRef("pk")).order_by().values("product").annotate(s=Sum("quantity")).values("s")
    order_units = (OrderItem.objects.filter(product=OuterRef("pk")).exclude(order__status="cancelled")
                   .order_by().values("product").annotate(s=Sum("quantity")).values("s"))
    return qs.annotate(popularity=Coalesce(Subquery(sale_units, output_field=IntegerField()), Value(0))
                       + Coalesce(Subquery(order_units, output_field=IntegerField()), Value(0)))


SORTS = {"price_asc": "selling_price", "price_desc": "-selling_price", "popular": "-popularity", "name": "name"}


class HomeView(TemplateView):
    template_name = "store/home.html"

    def _category_link(self, categories, *words):
        for c in categories:
            if any(w in c.name.lower() for w in words):
                return reverse("store:category", args=[c.slug])
        return reverse("store:products") + "?offers=1"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        base = storefront_products().select_related("category")
        all_categories = list(Category.objects.filter(is_active=True).annotate(
            product_count=Count("products", filter=Q(products__is_online=True, products__is_archived=False))))
        category_order = ["Fruits & Vegetables", "Beverages", "Dairy & Eggs", "Snacks", "Bakery",
                          "Personal Care", "Household", "Organic & Healthy"]
        all_categories.sort(key=lambda category: (
            category_order.index(category.name) if category.name in category_order else len(category_order),
            category.name.lower(),
        ))
        ranked = _with_popularity(base.filter(stock_quantity__gt=0))
        spotlight_product = base.filter(name__iexact="Cooking Oil 1L", stock_quantity__gt=0).first()
        home_categories = all_categories
        if spotlight_product:
            home_categories = [
                category for category in all_categories
                if category.name != "Fruits & Vegetables"
            ][:7]
        featured_order = ("-popularity", "-discount_percent", "name")
        featured_overrides = {
            2: ranked.filter(name__iexact="Black Tea 450g").first(),
            3: ranked.filter(name__iexact="Turmeric Powder 100g").first(),
            4: ranked.filter(name__iexact="Milk").first(),
            5: ranked.filter(name__iexact="Pasta 400g").first(),
        }
        selected_overrides = {
            index: product
            for index, product in featured_overrides.items()
            if product is not None
        }
        featured_ids = {product.pk for product in selected_overrides.values()}
        featured_candidates = iter(
            list(ranked.exclude(pk__in=featured_ids).order_by(*featured_order)[:6])
        )
        featured_slots = [None] * 6
        for index, product in selected_overrides.items():
            featured_slots[index] = product
        for index, product in enumerate(featured_slots):
            if product is None:
                featured_slots[index] = next(featured_candidates, None)
        featured_products = [
            product for product in featured_slots if product is not None
        ]
        ctx.update(
            categories=home_categories[:8],
            spotlight_product=spotlight_product,
            deals=base.filter(discount_percent__gt=0, stock_quantity__gt=0)[:4],
            featured=featured_products,
            best_sellers=ranked.order_by("-popularity", "name")[:5],
            promo_pantry_url=self._category_link(all_categories, "cooking", "pantry"),
            promo_snack_url=self._category_link(all_categories, "snack", "beverage", "drink"),
        )
        ctx["hero_banners"] = HeroBanner.objects.filter(is_active=True)
        return ctx


class CategoryListView(TemplateView):
    template_name = "store/categories.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = Category.objects.filter(is_active=True).annotate(
            product_count=Count(
                "products",
                filter=Q(products__is_online=True, products__is_archived=False),
            )
        ).order_by("name")
        return ctx


class ProductListView(ListView):
    template_name = "store/product_list.html"
    paginate_by = 100
    context_object_name = "products"
    search_mode = False

    def get_queryset(self):
        g = self.request.GET
        qs = _with_popularity(storefront_products().select_related("category"))
        self.category = None
        if "slug" in self.kwargs:
            self.category = get_object_or_404(Category, slug=self.kwargs["slug"], is_active=True)
        self.selected_categories = g.getlist("category")
        if not self.selected_categories and self.category:
            self.selected_categories = [self.category.slug]
        if self.selected_categories:
            qs = qs.filter(category__slug__in=self.selected_categories)
        self.q = g.get("q", "").strip()
        if self.q:
            qs = qs.filter(Q(name__icontains=self.q) | Q(description__icontains=self.q) | Q(sku__icontains=self.q))
        if g.get("offers") == "1":
            qs = qs.filter(discount_percent__gt=0)
        self.availability = [value for value in g.getlist("availability") if value in ("stock", "out")]
        if self.availability == ["stock"]:
            qs = qs.filter(stock_quantity__gt=0)
        elif self.availability == ["out"]:
            qs = qs.filter(stock_quantity=0)
        self.selected_price_ranges = [value for value in g.getlist("price_range")
                                      if value in ("under_100", "100_500", "500_1000", "over_1000")]
        range_query = Q()
        for price_range in self.selected_price_ranges:
            if price_range == "under_100":
                range_query |= Q(selling_price__lt=100)
            elif price_range == "100_500":
                range_query |= Q(selling_price__gte=100, selling_price__lt=500)
            elif price_range == "500_1000":
                range_query |= Q(selling_price__gte=500, selling_price__lte=1000)
            else:
                range_query |= Q(selling_price__gt=1000)
        if self.selected_price_ranges:
            qs = qs.filter(range_query)
        self.price_min = self._price(g.get("min_price"))
        self.price_max = self._price(g.get("max_price"))
        if self.price_min is not None:
            qs = qs.filter(selling_price__gte=self.price_min)
        if self.price_max is not None:
            qs = qs.filter(selling_price__lte=self.price_max)
        self.sort = g.get("sort") if g.get("sort") in SORTS else "popular"
        return qs.order_by(SORTS[self.sort], "name")

    @staticmethod
    def _price(value):
        try:
            price = Decimal(value)
            return price if price >= 0 else None
        except (InvalidOperation, TypeError, ValueError):
            return None

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx.update(categories=Category.objects.filter(is_active=True).annotate(
                        product_count=Count("products", filter=Q(products__is_online=True, products__is_archived=False))),
                   category=self.category, q=self.q, sort=self.sort, search_mode=self.search_mode,
                   selected_categories=self.selected_categories,
                   selected_price_ranges=self.selected_price_ranges, availability=self.availability,
                   min_price=self.price_min, max_price=self.price_max,
                   availability_counts={
                       "stock": storefront_products().filter(stock_quantity__gt=0).count(),
                       "out": storefront_products().filter(stock_quantity=0).count(),
                   })
        return ctx


class SearchView(ProductListView):
    search_mode = True


class ProductDetailView(DetailView):
    template_name = "store/product_detail.html"

    def get_queryset(self):
        return storefront_products().select_related("category")

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["related"] = storefront_products().filter(category=self.object.category, stock_quantity__gt=0).exclude(pk=self.object.pk)[:4] if self.object.category_id else []
        return ctx


class HelpView(TemplateView):
    template_name = "store/help.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["about_stats"] = settings.ABOUT_STATS
        return context


class ContactView(TemplateView):
    template_name = "store/contact.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["contact_form"] = kwargs.get("contact_form", ContactForm())
        context["contact_email"] = settings.CONTACT_EMAIL
        context["contact_whatsapp"] = settings.CONTACT_WHATSAPP
        context["contact_hours"] = settings.CONTACT_BUSINESS_HOURS
        context["contact_map_embed_url"] = settings.CONTACT_MAP_EMBED_URL
        context["contact_social_links"] = settings.CONTACT_SOCIAL_LINKS
        return context

    def post(self, request, *args, **kwargs):
        form = ContactForm(request.POST)
        if form.is_valid():
            recipient = settings.CONTACT_EMAIL.strip()
            if not recipient:
                form.add_error(None, "The contact form is not configured yet. Please use the contact details shown on this page.")
                return self.render_to_response(self.get_context_data(contact_form=form), status=503)
            data = form.cleaned_data
            subject_label = dict(ContactForm.SUBJECT_CHOICES)[data["subject"]]
            body = (
                f"Name: {data['name']}\nEmail: {data['email']}\n"
                f"Phone: {data['phone'] or 'Not provided'}\nSubject: {subject_label}\n\n"
                f"{data['message']}"
            )
            try:
                sent = send_mail(
                    f"W&B General Store contact: {subject_label}", body,
                    settings.DEFAULT_FROM_EMAIL or recipient, [recipient],
                    reply_to=[data["email"]], fail_silently=False,
                )
            except Exception:
                logging.getLogger(__name__).exception("Contact form email could not be sent")
                sent = 0
            if sent:
                messages.success(request, "Thanks for reaching out. Your message has been sent.")
                return redirect("store:contact")
            form.add_error(None, "We could not send your message right now. Please try again in a little while.")
            return self.render_to_response(self.get_context_data(contact_form=form), status=502)
        return self.render_to_response(self.get_context_data(contact_form=form), status=400)


# ---------------- cart ----------------
def _int(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class CartView(CustomerRequiredMixin, View):
    def get(self, request):
        items = list(get_cart(request.user).items.select_related("product__category"))
        return render(request, "store/cart.html", {"items": items, "totals": cart_totals(items),
                                                    "problems": [i for i in items if _cart_item_needs_attention(i)]})


def _cart_item_needs_attention(item):
    product = item.product
    category_unavailable = product.category_id and not product.category.is_active
    return (item.quantity > product.stock_quantity or not product.is_online
            or product.is_archived or category_unavailable)


def _cart_count(user):
    return CartItem.objects.filter(cart__user=user).aggregate(n=Sum("quantity"))["n"] or 0


def _safe_next(request, default="store:cart"):
    nxt = request.POST.get("next") or ""
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else reverse(default)


class CartAddView(View):
    """Guests are never added to a cart: their intent is remembered and the login modal / page takes over.

    Customer and owner accounts may shop; staff accounts remain restricted to browsing.
    """

    def post(self, request):
        pid, qty = _int(request.POST.get("product_id"), 0), _int(request.POST.get("quantity"))
        ajax = is_ajax(request)
        user = request.user
        if not user.is_authenticated:
            remember_pending(request, pid, qty)
            if ajax:
                return JsonResponse({"ok": False, "login_required": True,
                                     "error": "Please log in to add products to your cart."}, status=401)
            return redirect_to_login(_safe_next(request, "store:home"))
        if not user.is_customer and not user.is_owner:
            if ajax:
                return JsonResponse({"ok": False, "error": "Only customer accounts can shop."}, status=403)
            raise PermissionDenied
        try:
            item = cart_add(user, pid, qty)
        except OrderError as exc:
            if ajax:
                return JsonResponse({"ok": False, "error": str(exc)}, status=400)
            messages.error(request, str(exc))
        else:
            if ajax:
                return JsonResponse({"ok": True, "message": f"{item.product.name} added to your cart.",
                                     "cart_count": _cart_count(user)})
            messages.success(request, f"{item.product.name} added to your cart.")
        return redirect(_safe_next(request))


class PendingClearView(View):
    """Called when a guest dismisses the login modal: forget the remembered product."""

    def post(self, request):
        clear_pending(request)
        return HttpResponse(status=204)


class CartUpdateView(CustomerRequiredMixin, View):
    def post(self, request):
        try:
            item = cart_set(request.user, _int(request.POST.get("item_id"), 0), _int(request.POST.get("quantity"), 0))
        except OrderError as exc:
            if is_ajax(request):
                return JsonResponse({"ok": False, "error": str(exc)}, status=400)
            messages.error(request, str(exc))
            return redirect("store:cart")
        if is_ajax(request):
            items = list(get_cart(request.user).items.select_related("product__category"))
            totals = cart_totals(items)
            problems = [cart_item for cart_item in items if _cart_item_needs_attention(cart_item)]
            return JsonResponse({
                "ok": True,
                "item_id": _int(request.POST.get("item_id"), 0),
                "removed": item is None,
                "quantity": item.quantity if item else 0,
                "line_total": format(item.line_total, ",.2f") if item else "0.00",
                "cart_count": _cart_count(request.user),
                "items_count": len(items),
                "subtotal": format(totals["subtotal"], ",.2f"),
                "discount": format(totals["discount"], ",.2f"),
                "delivery_fee": format(totals["delivery_fee"], ",.2f"),
                "total": format(totals["total"], ",.2f"),
                "has_problems": bool(problems),
            })
        return redirect("store:cart")


# ---------------- checkout & orders ----------------
class CheckoutView(CustomerRequiredMixin, View):
    def _context(self, request, form):
        items = list(get_cart(request.user).items.select_related("product__category"))
        return {
            "form": form,
            "items": items,
            "totals": cart_totals(items),
            "problems": [item for item in items if _cart_item_needs_attention(item)],
        }

    def get(self, request):
        ctx = self._context(request, None)
        if not ctx["items"]:
            messages.error(request, "Your cart is empty.")
            return redirect("store:cart")
        if ctx["problems"]:
            messages.error(request, "Some items are unavailable. Remove them from your cart before checkout.")
            return redirect("store:cart")
        profile = CustomerProfile.objects.filter(user=request.user).first()
        ctx["form"] = CheckoutForm(initial={
            "customer_name": request.user.get_full_name(), "phone": request.user.phone,
            "address": profile.default_address if profile else "", "idempotency_key": uuid.uuid4()})
        return render(request, "store/checkout.html", ctx)

    def post(self, request):
        form = CheckoutForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            try:
                order, _ = place_order(user=request.user, name=d["customer_name"], phone=d["phone"], address=d["address"],
                                       instructions=d["delivery_instructions"], idempotency_key=d["idempotency_key"])
            except (OrderError, InsufficientStock) as exc:
                messages.error(request, str(exc))
                return render(request, "store/checkout.html", self._context(request, form), status=409)
            except IntegrityError:
                order = get_object_or_404(Order, idempotency_key=d["idempotency_key"], customer=request.user)
            return redirect("store:order-detail", pk=order.pk)
        return render(request, "store/checkout.html", self._context(request, form), status=400)


class OrderListView(CustomerRequiredMixin, ListView):
    template_name = "store/orders.html"
    paginate_by = 10
    context_object_name = "orders"

    def get_queryset(self):
        return Order.objects.filter(customer=self.request.user)


class OrderDetailView(CustomerRequiredMixin, View):
    def get(self, request, pk):
        order = get_object_or_404(Order.objects.prefetch_related("items__product", "events"), pk=pk, customer=request.user)
        return render(request, "store/order_detail.html", {"order": order})


class OrderCancelView(CustomerRequiredMixin, View):
    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk, customer=request.user)
        try:
            update_order_status(order_id=order.pk, new_status="cancelled", user=request.user, by_customer=True,
                                note=request.POST.get("note", ""))
            messages.success(request, "Your order has been cancelled.")
        except OrderError as exc:
            messages.error(request, str(exc))
        return redirect("store:order-detail", pk=order.pk)


class ProfileView(CustomerRequiredMixin, View):
    def _form(self, request, data=None):
        profile = CustomerProfile.objects.get_or_create(user=request.user)[0]
        return ProfileForm(data, instance=request.user, profile=profile)

    def get(self, request):
        return render(request, "store/profile.html", {"form": self._form(request)})

    def post(self, request):
        form = self._form(request, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile saved.")
            return redirect("store:profile")
        return render(request, "store/profile.html", {"form": form}, status=400)
