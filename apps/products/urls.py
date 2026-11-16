from django.urls import path

from . import views

app_name = "products"
urlpatterns = [
    path("", views.ProductListView.as_view(), name="list"),
    path("new/", views.ProductCreateView.as_view(), name="create"),
    path("categories/", views.CategoryListView.as_view(), name="categories"),
    path("<int:pk>/", views.ProductDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ProductUpdateView.as_view(), name="edit"),
    path("<int:pk>/barcode-labels/", views.ProductBarcodeLabelView.as_view(), name="barcode_labels"),
    path("<int:pk>/archive/", views.ProductArchiveView.as_view(), name="archive"),
    path("<int:pk>/adjust/", views.StockAdjustView.as_view(), name="adjust"),
]
