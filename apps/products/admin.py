from django.contrib import admin

from .models import Category, Product

admin.site.register(Category)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "selling_price", "stock_quantity", "is_archived")
    readonly_fields = ("stock_quantity",)
    search_fields = ("name", "sku", "barcode")
