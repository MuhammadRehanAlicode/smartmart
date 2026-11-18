from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("categories", views.CategoryViewSet, basename="category")
router.register("products", views.ProductViewSet, basename="product")
router.register("stock-movements", views.StockMovementViewSet, basename="stock-movement")
router.register("suppliers", views.SupplierViewSet, basename="supplier")
router.register("purchases", views.PurchaseViewSet, basename="purchase")
router.register("sales", views.SaleViewSet, basename="sale")
router.register("customers", views.CustomerViewSet, basename="customer")
router.register("orders", views.OrderViewSet, basename="order")

app_name = "api"
urlpatterns = [
    path("auth/csrf/", views.CsrfView.as_view(), name="csrf"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/2fa/verify/", views.TwoFactorLoginView.as_view(), name="2fa-verify"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/me/", views.MeView.as_view(), name="me"),
    path("cart/", views.CartView.as_view(), name="cart"),
    path("cart/items/<int:pk>/", views.CartItemView.as_view(), name="cart-item"),
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
    path("offline/orders/", views.OfflineOrderView.as_view(), name="offline-orders"),
    path("offline/cart/", views.OfflineCartView.as_view(), name="offline-cart"),
    path("reports/summary/", views.ReportSummaryView.as_view(), name="report-summary"),
    path("reports/daily/", views.ReportDailyView.as_view(), name="report-daily"),
    path("reports/best-sellers/", views.ReportBestSellersView.as_view(), name="report-best-sellers"),
    path("", include(router.urls)),
]
