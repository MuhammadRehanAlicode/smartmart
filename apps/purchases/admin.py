from django.contrib import admin

from .models import Purchase, PurchaseItem


class ItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 0


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ("id", "supplier", "status", "created_at")
    inlines = [ItemInline]
    # Receiving must go through the app so stock and audit stay consistent.
    readonly_fields = ("status", "received_at")
