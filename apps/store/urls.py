from django.urls import path
from django.views.generic import RedirectView

from . import pwa, views

app_name = "store"
urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("categories/", views.CategoryListView.as_view(), name="categories"),
    path("about/", views.HelpView.as_view(), name="about"),
    path("shop/", views.ProductListView.as_view(), name="products"),
    path("category/<slug:slug>/", views.ProductListView.as_view(), name="category"),
    path("search/", views.SearchView.as_view(), name="search"),
    path("product/<int:pk>/", views.ProductDetailView.as_view(), name="product"),
    path("cart/", views.CartView.as_view(), name="cart"),
    path("cart/add/", views.CartAddView.as_view(), name="cart-add"),
    path("cart/pending/clear/", views.PendingClearView.as_view(), name="pending-clear"),
    path("cart/update/", views.CartUpdateView.as_view(), name="cart-update"),
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
    path("orders/", views.OrderListView.as_view(), name="orders"),
    path("orders/<int:pk>/", views.OrderDetailView.as_view(), name="order-detail"),
    path("orders/<int:pk>/cancel/", views.OrderCancelView.as_view(), name="order-cancel"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("help/", views.HelpView.as_view(), name="help"),
    path("contact/", views.ContactView.as_view(), name="contact"),
    # Progressive Web App / offline support
    path("manifest.webmanifest", pwa.manifest, name="manifest"),
    path("sw.js", pwa.service_worker, name="service-worker"),
    path("offline/", pwa.OfflinePage.as_view(), name="offline"),
    path("offline/cart/", pwa.OfflinePage.as_view(template_name="store/offline_cart.html", page="cart"), name="offline-cart"),
    path("offline/checkout/", pwa.OfflinePage.as_view(template_name="store/offline_checkout.html", page="checkout"), name="offline-checkout"),
    path("offline/orders/", pwa.OfflinePage.as_view(template_name="store/offline_orders.html", page="orders"), name="offline-orders"),
]
