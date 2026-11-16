from django.contrib import admin

from .models import Sale, SaleItem, SaleReturn


class ItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in SaleItem._meta.fields]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("id", "total", "payment_method", "cashier", "created_at")
    inlines = [ItemInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(SaleReturn)
