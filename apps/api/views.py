from dataclasses import asdict
from datetime import date
from decimal import Decimal

from django.contrib.auth import authenticate, login, logout
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework import mixins, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts import lockout
from apps.accounts import two_factor
from apps.accounts.models import User
from apps.core.audit import log_action
from apps.finance.calculations import summary
from apps.inventory.models import StockMovement
from apps.inventory.services import InsufficientStock, adjust_stock
from apps.orders.models import Order
from apps.orders.offline import cart_snapshot, process_offline_order, replace_cart
from apps.orders.services import (OrderError, cart_add, cart_set, cart_totals, get_cart, place_order,
                                  update_order_status)
from apps.products.models import Category, Product
from apps.purchases.models import Purchase
from apps.purchases.services import PurchaseError, cancel_purchase, receive_purchase
from apps.reports.services import best_sellers, daily_series, parse_range
from apps.sales.models import Sale
from apps.sales.services import SaleError, create_return, create_sale
from apps.suppliers.models import Supplier

from . import serializers as S
from .exceptions import BusinessRuleError, StockConflict
from .permissions import IsAnyRole, IsCustomer, IsOwner, IsStaffOrOwner, OwnerWriteStaffRead


def _date_param(request, name):
    raw = request.query_params.get(name)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValidationError({name: "Use the format YYYY-MM-DD."})


def _money(d):
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in d.items()}


# ---------------- auth ----------------
class CsrfEnforcedNoAuth(SessionAuthentication):
    """For the login view: authenticates nobody but still enforces CSRF (prevents login CSRF)."""

    def authenticate(self, request):
        self.enforce_csrf(request)
        return None


class CsrfView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class LoginView(APIView):
    authentication_classes = [CsrfEnforcedNoAuth]
    permission_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        username = str(request.data.get("username", ""))[:150]
        password = str(request.data.get("password", ""))
        if lockout.is_locked(request, username):
            return Response({"error": {"status": 429, "code": "locked", "message": "Too many failed attempts. Try again later.", "details": None}}, status=429)
        user = authenticate(request, username=username, password=password)
        if user is None:
            lockout.register_failure(request, username)
            return Response({"error": {"status": 400, "code": "invalid_credentials", "message": "Incorrect username or password.", "details": None}}, status=400)
        lockout.clear(request, username)
        if user.is_superuser:
            two_factor.set_preauth(request, user)
            target = "accounts:2fa-setup" if not user.totp_confirmed_at else "api:2fa-verify"
            return Response({"requires_2fa": True, "setup_required": not bool(user.totp_confirmed_at),
                             "verification_url": request.build_absolute_uri(reverse(target))}, status=status.HTTP_202_ACCEPTED)
        login(request, user)
        return Response(S.MeSerializer(user).data)


class TwoFactorLoginView(APIView):
    authentication_classes = [CsrfEnforcedNoAuth]
    permission_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        user = two_factor.get_preauth_user(request)
        if not user or not user.totp_confirmed_at:
            return Response({"error": {"status": 400, "code": "invalid_challenge", "message": "Sign in again to start a valid verification challenge.", "details": None}}, status=400)
        if two_factor.is_rate_limited(user.pk):
            return Response({"error": {"status": 429, "code": "locked", "message": "Too many verification attempts. Try again later.", "details": None}}, status=429)
        method = two_factor.verify_and_consume(user, request.data.get("code"))
        if not method:
            return Response({"error": {"status": 400, "code": "invalid_code", "message": "The verification code is invalid or has already been used.", "details": None}}, status=400)
        two_factor.complete_login(request, user)
        log_action(user, "security.2fa_verified", user.username, method=method)
        return Response(S.MeSerializer(user).data)


class LogoutView(APIView):
    permission_classes = [IsAnyRole]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAnyRole]

    def get(self, request):
        return Response(S.MeSerializer(request.user).data)

    def patch(self, request):
        ser = S.MeSerializer(request.user, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)


# ---------------- catalogue ----------------
class CategoryViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                      mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = S.CategorySerializer
    permission_classes = [OwnerWriteStaffRead]
    queryset = Category.objects.all()
    filter_backends = [SearchFilter]
    search_fields = ("name",)


class ProductViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                     mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = S.ProductSerializer
    permission_classes = [OwnerWriteStaffRead]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ("name", "sku", "barcode")
    ordering_fields = ("name", "selling_price", "stock_quantity", "created_at")
    ordering = ("name",)

    def get_queryset(self):
        p = self.request.query_params
        qs = Product.objects.select_related("category")
        if self.action == "list" and p.get("archived") != "true":
            qs = qs.filter(is_archived=False)
        if p.get("category", "").isdigit():
            qs = qs.filter(category_id=int(p["category"]))
        if p.get("online") in ("true", "false"):
            qs = qs.filter(is_online=p["online"] == "true")
        if p.get("stock") == "out":
            qs = qs.filter(stock_quantity=0)
        elif p.get("stock") == "low":
            from django.db.models import F
            qs = qs.filter(stock_quantity__gt=0, stock_quantity__lte=F("low_stock_threshold"))
        return qs

    @action(detail=True, methods=["post"], url_path="adjust-stock", permission_classes=[IsOwner])
    def adjust_stock(self, request, pk=None):
        product = self.get_object()
        ser = S.StockAdjustSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            adjust_stock(product, ser.validated_data["quantity_change"], ser.validated_data["reason"], request.user)
        except InsufficientStock as exc:
            raise StockConflict(str(exc))
        log_action(request.user, "stock.adjusted", product.sku, change=ser.validated_data["quantity_change"],
                   reason=ser.validated_data["reason"], via="api")
        product.refresh_from_db()
        return Response(S.ProductSerializer(product, context={"request": request}).data)

    @action(detail=True, methods=["post"], permission_classes=[IsOwner])
    def archive(self, request, pk=None):
        return self._set_archived(request, True)

    @action(detail=True, methods=["post"], permission_classes=[IsOwner])
    def restore(self, request, pk=None):
        return self._set_archived(request, False)

    def _set_archived(self, request, value):
        product = get_object_or_404(Product, pk=self.kwargs["pk"])
        product.is_archived = value
        product.save(update_fields=["is_archived", "updated_at"])
        log_action(request.user, "product.archived" if value else "product.restored", product.sku, via="api")
        return Response(S.ProductSerializer(product, context={"request": request}).data)


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = S.StockMovementSerializer
    permission_classes = [IsStaffOrOwner]

    def get_queryset(self):
        qs = StockMovement.objects.select_related("product")
        p = self.request.query_params
        if p.get("product", "").isdigit():
            qs = qs.filter(product_id=int(p["product"]))
        if p.get("type") in StockMovement.Type.values:
            qs = qs.filter(movement_type=p["type"])
        if (d := _date_param(self.request, "date_from")):
            qs = qs.filter(created_at__date__gte=d)
        if (d := _date_param(self.request, "date_to")):
            qs = qs.filter(created_at__date__lte=d)
        return qs


# ---------------- suppliers & purchases ----------------
class SupplierViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                      mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = S.SupplierSerializer
    permission_classes = [IsOwner]
    queryset = Supplier.objects.all()
    filter_backends = [SearchFilter]
    search_fields = ("name", "phone")


class PurchaseViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsOwner]

    def get_serializer_class(self):
        return S.PurchaseCreateSerializer if self.action == "create" else S.PurchaseSerializer

    def get_queryset(self):
        qs = Purchase.objects.select_related("supplier").prefetch_related("items__product")
        if self.request.query_params.get("status") in Purchase.Status.values:
            qs = qs.filter(status=self.request.query_params["status"])
        if self.request.query_params.get("supplier", "").isdigit():
            qs = qs.filter(supplier_id=int(self.request.query_params["supplier"]))
        return qs

    def create(self, request, *args, **kwargs):
        ser = S.PurchaseCreateSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        purchase = ser.save()
        purchase = self.get_queryset().get(pk=purchase.pk)
        return Response(S.PurchaseSerializer(purchase).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        get_object_or_404(Purchase, pk=pk)
        try:
            receive_purchase(int(pk), request.user)
        except PurchaseError as exc:
            raise BusinessRuleError(str(exc))
        return Response(S.PurchaseSerializer(self.get_queryset().get(pk=pk)).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        get_object_or_404(Purchase, pk=pk)
        try:
            cancel_purchase(int(pk), request.user)
        except PurchaseError as exc:
            raise BusinessRuleError(str(exc))
        return Response(S.PurchaseSerializer(self.get_queryset().get(pk=pk)).data)


# ---------------- sales ----------------
class SaleViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = S.SaleSerializer
    permission_classes = [IsStaffOrOwner]

    def get_queryset(self):
        qs = Sale.objects.select_related("cashier").prefetch_related("items", "returns")
        if (d := _date_param(self.request, "date_from")):
            qs = qs.filter(created_at__date__gte=d)
        if (d := _date_param(self.request, "date_to")):
            qs = qs.filter(created_at__date__lte=d)
        return qs

    def create(self, request):
        ser = S.SaleCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        key = d.get("idempotency_key")
        try:
            sale = create_sale(user=request.user, items=[(i["product_id"], i["quantity"]) for i in d["items"]],
                               payment_method=d["payment_method"], amount_tendered=d.get("amount_tendered"),
                               idempotency_key=key)
        except SaleError as exc:
            raise BusinessRuleError(str(exc))
        except InsufficientStock as exc:
            raise StockConflict(str(exc))
        except IntegrityError:
            sale = get_object_or_404(Sale, idempotency_key=key)
        sale = self.get_queryset().get(pk=sale.pk)
        return Response(S.SaleSerializer(sale, context={"request": request}).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="return", permission_classes=[IsOwner])
    def return_items(self, request, pk=None):
        get_object_or_404(Sale, pk=pk)
        ser = S.ReturnCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        quantities = {}
        for line in ser.validated_data["items"]:
            quantities[line["sale_item_id"]] = quantities.get(line["sale_item_id"], 0) + line["quantity"]
        try:
            ret = create_return(sale_id=int(pk), user=request.user, quantities=quantities,
                                reason=ser.validated_data["reason"], restock=ser.validated_data["restock"])
        except (SaleError, InsufficientStock) as exc:
            raise BusinessRuleError(str(exc))
        return Response({"id": ret.pk, "refund_total": str(ret.refund_total), "restocked": ret.restock},
                        status=status.HTTP_201_CREATED)


# ---------------- customers ----------------
class CustomerViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = S.CustomerSerializer
    permission_classes = [IsStaffOrOwner]
    queryset = User.objects.filter(role=User.Role.CUSTOMER).order_by("username")
    filter_backends = [SearchFilter]
    search_fields = ("username", "first_name", "last_name", "phone", "email")


# ---------------- cart, checkout, orders ----------------
def _cart_payload(user):
    items = list(get_cart(user).items.select_related("product"))
    return {
        "items": [{"id": i.pk, "quantity": i.quantity, "line_total": str(i.line_total),
                   "product": {"id": i.product_id, "name": i.product.name, "price": str(i.product.discounted_price),
                               "stock": i.product.stock_quantity}} for i in items],
        "totals": {k: str(v) for k, v in cart_totals(items).items()},
    }


class CartView(APIView):
    permission_classes = [IsCustomer]

    def get(self, request):
        return Response(_cart_payload(request.user))

    def post(self, request):
        ser = S.CartAddSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            cart_add(request.user, ser.validated_data["product_id"], ser.validated_data["quantity"])
        except OrderError as exc:
            raise BusinessRuleError(str(exc))
        return Response(_cart_payload(request.user), status=status.HTTP_201_CREATED)


class CartItemView(APIView):
    permission_classes = [IsCustomer]

    def patch(self, request, pk):
        ser = S.CartQuantitySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            cart_set(request.user, pk, ser.validated_data["quantity"])
        except OrderError as exc:
            raise NotFound(str(exc))
        return Response(_cart_payload(request.user))

    def delete(self, request, pk):
        try:
            cart_set(request.user, pk, 0)
        except OrderError as exc:
            raise NotFound(str(exc))
        return Response(status=status.HTTP_204_NO_CONTENT)


class CheckoutView(APIView):
    permission_classes = [IsCustomer]

    def post(self, request):
        ser = S.CheckoutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            order, created = place_order(user=request.user, name=d["customer_name"].strip(), phone=d["phone"],
                                         address=d["address"].strip(), instructions=d["delivery_instructions"],
                                         idempotency_key=d["idempotency_key"])
        except OrderError as exc:
            raise BusinessRuleError(str(exc))
        except InsufficientStock as exc:
            raise StockConflict(str(exc))
        except IntegrityError:
            order, created = get_object_or_404(Order, idempotency_key=d["idempotency_key"], customer=request.user), False
        order = Order.objects.prefetch_related("items", "events", "payments").get(pk=order.pk)
        return Response(S.OrderSerializer(order).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class OfflineOrderView(APIView):
    """Receives an order a customer saved offline. Same permission as the normal checkout API (customers only)."""
    permission_classes = [IsCustomer]

    def post(self, request):
        ser = S.OfflineOrderSerializer(data=request.data)
        if not ser.is_valid():  # retrying the same data can never fix this, so it is a final answer
            return Response({"status": "rejected", "reason_code": "invalid",
                             "reason": "The saved order contains invalid information.", "errors": ser.errors},
                            status=status.HTTP_400_BAD_REQUEST)
        result = process_offline_order(user=request.user, data=ser.validated_data)
        response = Response(result.body, status=result.http_status)
        response["Cache-Control"] = "no-store"
        return response


class OfflineCartView(APIView):
    """GET: the server cart in offline-cart shape. PUT: replace the server cart with the offline cart (idempotent)."""
    permission_classes = [IsCustomer]

    def get(self, request):
        response = Response(cart_snapshot(request.user))
        response["Cache-Control"] = "no-store"
        return response

    def put(self, request):
        ser = S.OfflineCartSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        skipped = replace_cart(request.user, ser.validated_data["items"])
        data = cart_snapshot(request.user)
        data["skipped"] = skipped
        response = Response(data)
        response["Cache-Control"] = "no-store"
        return response


class OrderViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = S.OrderSerializer
    permission_classes = [IsAnyRole]
    filter_backends = [SearchFilter]
    search_fields = ("customer_name", "phone")

    def get_queryset(self):
        qs = Order.objects.prefetch_related("items", "events", "payments")
        if self.request.user.role == "customer":
            qs = qs.filter(customer=self.request.user)          # customers only ever see their own orders
        if self.request.query_params.get("status") in Order.Status.values:
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    @action(detail=True, methods=["post"], permission_classes=[IsStaffOrOwner])
    def status(self, request, pk=None):
        order = self.get_object()
        ser = S.OrderStatusSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            update_order_status(order_id=order.pk, new_status=ser.validated_data["status"], user=request.user,
                                note=ser.validated_data["note"])
        except OrderError as exc:
            raise BusinessRuleError(str(exc))
        return Response(S.OrderSerializer(self.get_queryset().get(pk=order.pk)).data)

    @action(detail=True, methods=["post"], permission_classes=[IsCustomer])
    def cancel(self, request, pk=None):
        order = self.get_object()
        ser = S.OrderCancelSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            update_order_status(order_id=order.pk, new_status="cancelled", user=request.user, by_customer=True,
                                note=ser.validated_data["note"])
        except OrderError as exc:
            raise BusinessRuleError(str(exc))
        return Response(S.OrderSerializer(self.get_queryset().get(pk=order.pk)).data)


# ---------------- reports (owner only) ----------------
def _range(request):
    start, end, error = parse_range(request.query_params)
    if error:
        raise ValidationError({"date_from": error})
    return start, end


class ReportSummaryView(APIView):
    permission_classes = [IsOwner]

    def get(self, request):
        start, end = _range(request)
        return Response({"date_from": start.isoformat(), "date_to": end.isoformat(), **_money(asdict(summary(start, end)))})


class ReportDailyView(APIView):
    permission_classes = [IsOwner]

    def get(self, request):
        start, end = _range(request)
        rows = [{**_money(r), "date": r["date"].isoformat()} for r in daily_series(start, end)]
        return Response({"date_from": start.isoformat(), "date_to": end.isoformat(), "days": rows})


class ReportBestSellersView(APIView):
    permission_classes = [IsOwner]

    def get(self, request):
        start, end = _range(request)
        return Response({"results": [{"product_id": r["product_id"], "product_name": r["product_name"],
                                      "units": r["units"], "revenue": str(r["revenue"])} for r in best_sellers(start, end, 20)]})
