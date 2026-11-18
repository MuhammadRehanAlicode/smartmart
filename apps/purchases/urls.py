from django.urls import path

from . import views

app_name = "purchases"
urlpatterns = [
    path("products/<int:pk>/stock/", views.PurchaseProductStockView.as_view(), name="product_stock"),
    path("", views.PurchaseListView.as_view(), name="list"),
    path("new/", views.PurchaseEditView.as_view(), name="create"),
    path("<int:pk>/", views.PurchaseDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.PurchaseEditView.as_view(), name="edit"),
    path("<int:pk>/receive/", views.PurchaseReceiveView.as_view(), name="receive"),
    path("<int:pk>/cancel/", views.PurchaseCancelView.as_view(), name="cancel"),
]
