from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/", include("apps.api.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("dashboard/products/", include("apps.products.urls")),
    path("dashboard/inventory/", include("apps.inventory.urls")),
    path("dashboard/suppliers/", include("apps.suppliers.urls")),
    path("dashboard/purchases/", include("apps.purchases.urls")),
    path("dashboard/orders/", include("apps.orders.urls")),
    path("dashboard/sales/", include("apps.sales.urls")),
    path("dashboard/expenses/", include("apps.finance.urls")),
    path("dashboard/reports/", include("apps.reports.urls")),
    path("dashboard/banners/", include("apps.store.dashboard_urls")),
    path("dashboard/", include("apps.accounts.dashboard_urls")),
    path("", include("apps.store.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.not_found"
handler500 = "apps.core.views.server_error"
