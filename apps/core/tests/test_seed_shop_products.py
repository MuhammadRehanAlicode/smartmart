from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db.models import Sum
from django.test import TestCase

from apps.inventory.models import StockMovement
from apps.inventory.services import change_stock
from apps.orders.models import Cart, CartItem
from apps.products.models import Category, Product


class SeedShopProductsTests(TestCase):
    def create_legacy_carrots(self):
        category = Category.objects.create(name="Fruits & Vegetables")
        product = Product.objects.create(
            name="Carrots",
            category=category,
            sku="SHOP-DEMO-015",
            selling_price=Decimal("110.00"),
            cost_price=Decimal("65.00"),
        )
        change_stock(
            product,
            28,
            StockMovement.Type.OPENING,
            reason="Sample storefront inventory",
            reference=product.sku,
        )
        return product

    def test_seed_retires_replaced_samples_and_adds_grocery_replacements_idempotently(self):
        old_product = self.create_legacy_carrots()

        call_command("seed_shop_products", stdout=StringIO())

        old_product.refresh_from_db()
        self.assertTrue(old_product.is_archived)
        self.assertFalse(old_product.is_online)
        self.assertEqual(old_product.stock_quantity, 0)
        self.assertEqual(old_product.movements.aggregate(total=Sum("quantity_change"))["total"], 0)

        replacement = Product.objects.get(sku="SHOP-DEMO-074")
        self.assertEqual(replacement.name, "Chana Dal 1kg")
        self.assertEqual(replacement.category.name, "Cooking Essentials")
        self.assertEqual(replacement.stock_quantity, 24)

        haldi = Product.objects.get(sku="SHOP-DEMO-006")
        self.assertEqual(haldi.name, "Haldi")
        self.assertEqual(haldi.category.name, "Cooking Essentials")

        count = Product.objects.count()
        movement_count = StockMovement.objects.count()
        call_command("seed_shop_products", stdout=StringIO())
        self.assertEqual(Product.objects.count(), count)
        self.assertEqual(StockMovement.objects.count(), movement_count)

    def test_seed_refuses_to_retire_a_product_in_a_customer_cart(self):
        old_product = self.create_legacy_carrots()
        customer = get_user_model().objects.create_user(
            username="cart-customer",
            password="test-pass-12345",
            role="customer",
        )
        cart = Cart.objects.create(user=customer)
        CartItem.objects.create(cart=cart, product=old_product, quantity=1)

        with self.assertRaises(CommandError):
            call_command("seed_shop_products", stdout=StringIO())

        old_product.refresh_from_db()
        self.assertFalse(old_product.is_archived)
        self.assertEqual(old_product.stock_quantity, 28)
        self.assertFalse(Product.objects.filter(sku="SHOP-DEMO-074").exists())
