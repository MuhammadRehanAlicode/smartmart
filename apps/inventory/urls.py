from django.urls import path

from . import views

app_name = "inventory"
urlpatterns = [
    path("barcode-lookup/", views.BarcodeInventoryView.as_view(), name="barcode_lookup"),
    path("barcode-lookup/search/", views.BarcodeLookupView.as_view(), name="barcode_lookup_api"),
    path("", views.MovementListView.as_view(), name="movements"),
    path("alerts/", views.StockAlertsView.as_view(), name="alerts"),
]
