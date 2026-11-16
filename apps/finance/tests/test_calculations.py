from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.finance.calculations import summary
from apps.finance.models import Expense
from apps.inventory.models import StockMovement
from apps.inventory.services import change_stock
from apps.products.models import Product
from apps.purchases.models import Purchase, PurchaseItem
from apps.purchases.services import receive_purchase
from apps.sales.services import create_return, create_sale
from apps.suppliers.models import Supplier

PW = "S3cure-pass-987"


class SummaryTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password=PW, role="owner")
        self.p = Product.objects.create(name="Rice", sku="R", selling_price=Decimal("100.00"), cost_price=Decimal("60.00"))
        change_stock(self.p, 10, StockMovement.Type.OPENING)
        self.today = timezone.localdate()

    def test_empty_range_is_all_zero_except_inventory(self):
        s = summary(date(2000, 1, 1), date(2000, 1, 2))
        self.assertEqual((s.revenue, s.gross_profit, s.net_profit, s.sales_count), (0, 0, 0, 0))
        self.assertEqual(s.inventory_value, Decimal("600.00"))

    def test_profit_with_return_restock_and_expense(self):
        sale = create_sale(user=self.owner, items=[(self.p.pk, 3)], payment_method="cash")
        item = sale.items.get()
        create_return(sale_id=sale.pk, user=self.owner, quantities={item.pk: 1}, reason="x", restock=True)
        Expense.objects.create(date=self.today, description="Electricity", amount=Decimal("30.00"))
        s = summary(self.today, self.today)
        self.assertEqual(s.revenue, Decimal("300.00"))
        self.assertEqual(s.refunds, Decimal("100.00"))
        self.assertEqual(s.net_revenue, Decimal("200.00"))
        self.assertEqual(s.cogs, Decimal("120.00"))          # 3x60 sold minus 1x60 restocked
        self.assertEqual(s.gross_profit, Decimal("80.00"))
        self.assertEqual(s.net_profit, Decimal("50.00"))
        self.assertEqual(s.inventory_value, Decimal("480.00"))  # 8 units x 60

    def test_unrestocked_return_keeps_cost_in_cogs(self):
        sale = create_sale(user=self.owner, items=[(self.p.pk, 2)], payment_method="cash")
        item = sale.items.get()
        create_return(sale_id=sale.pk, user=self.owner, quantities={item.pk: 1}, reason="Damaged", restock=False)
        s = summary(self.today, self.today)
        self.assertEqual(s.cogs, Decimal("120.00"))
        self.assertEqual(s.gross_profit, Decimal("200.00") - Decimal("100.00") - Decimal("120.00"))

    def test_purchase_spend_is_not_an_expense(self):
        sup = Supplier.objects.create(name="S")
        pur = Purchase.objects.create(supplier=sup)
        PurchaseItem.objects.create(purchase=pur, product=self.p, quantity=5, unit_cost=Decimal("70.00"))
        receive_purchase(pur.pk, self.owner)
        s = summary(self.today, self.today)
        self.assertEqual(s.purchase_spend, Decimal("350.00"))
        self.assertEqual(s.expenses, Decimal("0.00"))
        self.assertEqual(s.net_profit, Decimal("0.00"))


class ExpenseViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password=PW, role="owner")
        self.staff = User.objects.create_user("cash", password=PW, role="staff")

    def test_owner_records_and_deletes_expense(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse("expenses:create"), {"date": "2026-10-01", "category": "rent", "description": "Shop rent", "amount": "5000"})
        self.assertRedirects(r, reverse("expenses:list"))
        e = Expense.objects.get()
        self.assertEqual(e.created_by, self.owner)
        self.client.post(reverse("expenses:delete", args=[e.pk]))
        self.assertEqual(Expense.objects.count(), 0)

    def test_invalid_amount_rejected(self):
        self.client.force_login(self.owner)
        for bad in ("0", "-5", "abc"):
            self.client.post(reverse("expenses:create"), {"date": "2026-10-01", "category": "rent", "description": "x", "amount": bad})
        self.assertEqual(Expense.objects.count(), 0)

    def test_staff_cannot_access_expenses(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("expenses:list")).status_code, 403)
        self.assertEqual(self.client.post(reverse("expenses:create"), {}).status_code, 403)
