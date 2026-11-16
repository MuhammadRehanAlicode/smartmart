from decimal import Decimal

from django.test import TestCase

from apps.inventory.models import StockMovement
from apps.inventory.services import InsufficientStock, adjust_stock, change_stock
from apps.products.models import Product

T = StockMovement.Type


def product(**kw):
    d = dict(name="Rice 5kg", sku="RICE5", selling_price=Decimal("100.00"), cost_price=Decimal("10.00"))
    d.update(kw)
    return Product.objects.create(**d)


class ChangeStockTests(TestCase):
    def test_increase_records_movement_with_balance(self):
        p = product()
        m = change_stock(p, 10, T.OPENING)
        p.refresh_from_db()
        self.assertEqual(p.stock_quantity, 10)
        self.assertEqual((m.quantity_change, m.balance_after), (10, 10))

    def test_cannot_go_negative(self):
        p = product()
        change_stock(p, 3, T.OPENING)
        with self.assertRaises(InsufficientStock):
            change_stock(p, -4, T.SALE)
        p.refresh_from_db()
        self.assertEqual(p.stock_quantity, 3)
        self.assertEqual(StockMovement.objects.filter(movement_type=T.SALE).count(), 0)

    def test_last_unit_cannot_be_sold_twice(self):
        p = product()
        change_stock(p, 1, T.OPENING)
        change_stock(p, -1, T.SALE)
        with self.assertRaises(InsufficientStock):
            change_stock(p, -1, T.ONLINE_ORDER)

    def test_zero_change_rejected(self):
        with self.assertRaises(ValueError):
            change_stock(product(), 0, T.ADJUSTMENT)

    def test_weighted_average_cost(self):
        p = product(cost_price=Decimal("10.00"))
        change_stock(p, 10, T.OPENING)
        change_stock(p, 10, T.PURCHASE, unit_cost=Decimal("20.00"))
        p.refresh_from_db()
        self.assertEqual(p.cost_price, Decimal("15.00"))
        self.assertEqual(p.stock_quantity, 20)

    def test_first_purchase_into_empty_stock_sets_cost(self):
        p = product(cost_price=Decimal("0.00"))
        change_stock(p, 4, T.PURCHASE, unit_cost=Decimal("12.50"))
        p.refresh_from_db()
        self.assertEqual(p.cost_price, Decimal("12.50"))

    def test_adjustment_requires_reason(self):
        p = product()
        change_stock(p, 5, T.OPENING)
        with self.assertRaises(ValueError):
            adjust_stock(p, -1, "  ", None)
        adjust_stock(p, -1, "Damaged", None)
        p.refresh_from_db()
        self.assertEqual(p.stock_quantity, 4)
