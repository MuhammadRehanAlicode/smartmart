"""Prepare clearly identified sample grocery products for the storefront."""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.inventory.models import StockMovement
from apps.inventory.services import change_stock
from apps.orders.models import CartItem, OrderItem
from apps.products.models import Category, Product
from apps.sales.models import SaleItem


SAMPLE_PRODUCTS = [
    # name, category, SKU suffix, original price, discount, cost, opening stock
    ("Fresh Bananas", "Fruits & Vegetables", "001", "140.00", "14.29", "85.00", 25),
    ("Coca Cola", "Beverages", "002", "200.00", "10.00", "130.00", 25),
    ("Milk", "Dairy & Eggs", "003", "180.00", "11.11", "120.00", 25),
    ("Bread", "Bakery", "004", "90.00", "11.11", "50.00", 25),
    ("Lay's Chips", "Snacks", "005", "70.00", "14.29", "35.00", 25),
    ("Haldi", "Cooking Essentials", "006", "120.00", "16.67", "65.00", 25),
    ("Oranges", "Fruits & Vegetables", "008", "185.00", "18.92", "100.00", 25),
    ("Seedless Grapes", "Fruits & Vegetables", "010", "420.00", "5", "270.00", 18),
    ("Cucumbers", "Fruits & Vegetables", "016", "100.00", "0", "60.00", 25),
    ("Orange Juice", "Beverages", "023", "240.00", "0", "155.00", 20),
    ("Mango Juice", "Beverages", "024", "220.00", "0", "140.00", 20),
    ("Mineral Water", "Beverages", "025", "70.00", "0", "38.00", 40),
    ("Green Tea", "Beverages", "026", "380.00", "5", "250.00", 15),
    ("Ground Coffee", "Beverages", "027", "650.00", "0", "440.00", 12),
    ("Sprite", "Beverages", "028", "180.00", "0", "115.00", 24),
    ("Plain Yogurt", "Dairy & Eggs", "029", "160.00", "0", "100.00", 22),
    ("Salted Butter", "Dairy & Eggs", "030", "290.00", "0", "205.00", 14),
    ("Cheddar Cheese", "Dairy & Eggs", "031", "420.00", "5", "300.00", 12),
    ("Farm Fresh Eggs", "Dairy & Eggs", "032", "340.00", "0", "250.00", 18),
    ("Fresh Cream", "Dairy & Eggs", "033", "190.00", "0", "125.00", 15),
    ("Chocolate Bar", "Snacks", "034", "120.00", "0", "70.00", 25),
    ("Salted Biscuits", "Snacks", "035", "90.00", "0", "50.00", 30),
    ("Butter Popcorn", "Snacks", "036", "140.00", "0", "85.00", 20),
    ("Mixed Nuts", "Snacks", "037", "520.00", "5", "370.00", 12),
    ("Chocolate Cookies", "Snacks", "038", "180.00", "0", "110.00", 18),
    ("Brown Bread", "Bakery", "039", "130.00", "0", "82.00", 18),
    ("Butter Croissants", "Bakery", "040", "160.00", "0", "100.00", 14),
    ("Whole Wheat Rusk", "Bakery", "041", "150.00", "0", "95.00", 20),
    ("Herbal Shampoo", "Personal Care", "042", "480.00", "0", "330.00", 12),
    ("Hand Wash", "Personal Care", "043", "210.00", "0", "135.00", 18),
    ("Mint Toothpaste", "Personal Care", "044", "190.00", "0", "120.00", 18),
    ("Dishwashing Liquid", "Household", "045", "260.00", "0", "175.00", 14),
    ("Laundry Detergent", "Household", "046", "550.00", "0", "390.00", 12),
    ("Paper Towels", "Household", "047", "180.00", "0", "115.00", 20),
    ("Rolled Oats", "Organic & Healthy", "048", "320.00", "0", "215.00", 14),
    ("Chia Seeds", "Organic & Healthy", "049", "450.00", "0", "310.00", 12),
    ("Cooking Oil 1L", "Cooking Essentials", "050", "620.00", "0", "510.00", 24),
    ("Desi Ghee 1kg", "Cooking Essentials", "051", "1450.00", "0", "1200.00", 16),
    ("Basmati Rice 5kg", "Cooking Essentials", "052", "1250.00", "0", "1020.00", 20),
    ("Wheat Flour 5kg", "Cooking Essentials", "053", "720.00", "0", "590.00", 22),
    ("White Sugar 1kg", "Cooking Essentials", "054", "180.00", "0", "145.00", 30),
    ("Red Lentils 1kg", "Cooking Essentials", "055", "360.00", "0", "285.00", 20),
    ("Colgate Toothpaste", "Personal Care", "057", "220.00", "0", "145.00", 24),
    ("Lifebuoy Soap", "Personal Care", "058", "110.00", "0", "70.00", 30),
    ("Dove Beauty Bar", "Personal Care", "059", "190.00", "0", "130.00", 18),
    ("Laundry Soap Bar", "Personal Care", "060", "100.00", "0", "65.00", 24),
    ("Family Body Lotion", "Personal Care", "061", "390.00", "0", "260.00", 14),
    ("Baby Diapers Pack", "Baby & Family", "062", "1100.00", "0", "850.00", 12),
    ("Baby Wipes Pack", "Baby & Family", "063", "260.00", "0", "175.00", 18),
    ("Kitchen Sponge Pack", "Household", "070", "120.00", "0", "75.00", 20),
    ("Facial Tissue Box", "Household", "071", "180.00", "0", "110.00", 20),
    ("Instant Noodles Pack", "Snacks", "072", "90.00", "0", "55.00", 30),
    ("Mixed Spice Pack", "Cooking Essentials", "073", "160.00", "0", "95.00", 20),
    ("Chana Dal 1kg", "Cooking Essentials", "074", "320.00", "0", "270.00", 24),
    ("Black Tea 450g", "Beverages", "075", "780.00", "0", "620.00", 14),
    ("Iodized Salt 800g", "Cooking Essentials", "076", "90.00", "0", "55.00", 30),
    ("Moong Dal 1kg", "Cooking Essentials", "077", "350.00", "0", "290.00", 24),
    ("Macaroni 400g", "Cooking Essentials", "078", "180.00", "0", "125.00", 25),
    ("Chickpeas 1kg", "Cooking Essentials", "079", "320.00", "0", "260.00", 22),
    ("Vermicelli 200g", "Cooking Essentials", "080", "90.00", "0", "60.00", 25),
    ("Black Pepper 100g", "Cooking Essentials", "081", "240.00", "0", "175.00", 18),
    ("Corn Flour 300g", "Cooking Essentials", "082", "160.00", "0", "110.00", 20),
    ("Tomato Paste 400g", "Cooking Essentials", "083", "180.00", "0", "120.00", 20),
    ("Milk Powder 500g", "Dairy & Eggs", "084", "950.00", "0", "780.00", 15),
    ("Kidney Beans 1kg", "Cooking Essentials", "085", "380.00", "0", "300.00", 20),
    ("Basmati Rice 1kg", "Cooking Essentials", "086", "300.00", "0", "245.00", 25),
    ("Turmeric Powder 100g", "Cooking Essentials", "087", "110.00", "0", "70.00", 24),
    ("Mayonnaise 500g", "Cooking Essentials", "088", "320.00", "0", "245.00", 16),
    ("White Vinegar 500ml", "Cooking Essentials", "089", "150.00", "0", "100.00", 20),
    ("Baking Powder 100g", "Cooking Essentials", "090", "100.00", "0", "65.00", 20),
    ("Breakfast Cereal 375g", "Snacks", "091", "420.00", "0", "320.00", 16),
    ("Custard Powder 300g", "Cooking Essentials", "092", "240.00", "0", "175.00", 18),
    ("Pasta 400g", "Cooking Essentials", "093", "190.00", "0", "130.00", 24),
]
REPLACED_SAMPLE_SUFFIXES = (
    "007", "009", "011", "012", "013", "014", "015", "017", "018", "019",
    "020", "021", "022", "056", "064", "065", "066", "067", "068", "069",
)
SHOP_CATEGORIES = [
    "Fruits & Vegetables", "Beverages", "Dairy & Eggs", "Snacks", "Bakery",
    "Personal Care", "Household", "Organic & Healthy", "Cooking Essentials",
    "Baby & Family", "Clothing & Accessories", "Watches & Accessories",
]


class Command(BaseCommand):
    help = "Prepare clearly marked sample grocery products for the storefront."

    @transaction.atomic
    def handle(self, *args, **options):
        for category_name in SHOP_CATEGORIES:
            Category.objects.get_or_create(name=category_name)
        self._archive_replaced_products()
        added = 0
        for name, category_name, suffix, price, discount, cost, stock in SAMPLE_PRODUCTS:
            sku = f"SHOP-DEMO-{suffix}"
            if Product.objects.filter(sku=sku).exists():
                continue
            category, _ = Category.objects.get_or_create(name=category_name)
            product = Product.objects.create(
                name=name,
                category=category,
                sku=sku,
                selling_price=Decimal(price),
                cost_price=Decimal(cost),
                discount_percent=Decimal(discount),
                is_online=True,
                description="Sample storefront product based on the SmartMart design reference.",
            )
            change_stock(
                product,
                stock,
                StockMovement.Type.OPENING,
                reason="Sample storefront inventory",
                reference=sku,
            )
            added += 1

        self.stdout.write(self.style.SUCCESS(
            f"Prepared {len(SHOP_CATEGORIES)} shop categories and added {added} sample products."
        ))

    def _archive_replaced_products(self):
        for suffix in REPLACED_SAMPLE_SUFFIXES:
            product = Product.objects.filter(sku=f"SHOP-DEMO-{suffix}").first()
            if product is None or product.is_archived:
                continue
            if (SaleItem.objects.filter(product=product).exists()
                    or OrderItem.objects.filter(product=product).exists()
                    or CartItem.objects.filter(product=product).exists()):
                raise CommandError(
                    f"Cannot replace {product.sku}: it has sales, orders, or cart items."
                )
            if product.stock_quantity:
                change_stock(
                    product,
                    -product.stock_quantity,
                    StockMovement.Type.ADJUSTMENT,
                    reason="Archived replaced sample catalog item",
                    reference=product.sku,
                )
            product.is_online = False
            product.is_archived = True
            product.save(update_fields=["is_online", "is_archived", "updated_at"])
