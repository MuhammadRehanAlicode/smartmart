from django.urls import path

from . import views

app_name = "inventory"
urlpatterns = [
    path("", views.MovementListView.as_view(), name="movements"),
    path("alerts/", views.StockAlertsView.as_view(), name="alerts"),
]
