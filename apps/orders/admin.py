from django.contrib import admin

from .models import Order, OrderItem


class ItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in OrderItem._meta.fields]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "status", "source", "total", "created_at")
    inlines = [ItemInline]
    # Status/stock changes must go through the app (services.update_order_status).
    readonly_fields = [f.name for f in Order._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
