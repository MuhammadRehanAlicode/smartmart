from django.urls import path

from . import views

app_name = "sales"
urlpatterns = [
    path("", views.SaleListView.as_view(), name="list"),
    path("pos/", views.PosView.as_view(), name="pos"),
    path("pos/search/", views.ProductSearchApi.as_view(), name="search"),
    path("pos/checkout/", views.CheckoutApi.as_view(), name="checkout"),
    path("<int:pk>/receipt/", views.ReceiptView.as_view(), name="receipt"),
    path("<int:pk>/return/", views.ReturnView.as_view(), name="return"),
]
