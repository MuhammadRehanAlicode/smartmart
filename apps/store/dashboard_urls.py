from django.urls import path

from .views import HeroBannerManageView

app_name = "store_banners"
urlpatterns = [
    path("", HeroBannerManageView.as_view(), name="manage"),
]
