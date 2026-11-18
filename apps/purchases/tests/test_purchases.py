from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.inventory.models import StockMovement
from apps.products.models import Product
from apps.products.models import ProductUnit
from apps.purchases.models import Purchase, PurchaseItem
from apps.purchases.services import PurchaseError, cancel_purchase, receive_purchase
from apps.suppliers.models import Supplier

PW = "S3cure-pass-987"


class PurchaseBase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password=PW, role="owner")
        self.staff = User.objects.create_user("cash", password=PW, role="staff")
        self.supplier = Supplier.objects.create(name="Metro Traders")
        self.p1 = Product.objects.create(name="Rice", sku="R1", selling_price=Decimal("120"))
        self.p2 = Product.objects.create(name="Sugar", sku="S1", selling_price=Decimal("150"))

    def make_purchase(self):
        pur = Purchase.objects.create(supplier=self.supplier, created_by=self.owner)
        PurchaseItem.objects.create(purchase=pur, product=self.p1, quantity=10, unit_cost=Decimal("100.00"))
        PurchaseItem.objects.create(purchase=pur, product=self.p2, quantity=5, unit_cost=Decimal("40.50"))
        return pur


class PurchaseServiceTests(PurchaseBase):
    def test_carton_purchase_converts_and_prices_cost_per_base_unit(self):
        from apps.products.models import ProductUnit
        carton = ProductUnit.objects.create(product=self.p1, unit_code=Product.Unit.CTN,
            conversion_factor=Decimal("12"), purchase_enabled=True, sales_enabled=True,
            selling_price=Decimal("550"))
        pur = Purchase.objects.create(supplier=self.supplier, created_by=self.owner)
        PurchaseItem.objects.create(purchase=pur, product=self.p1, quantity=Decimal("5"),
            unit_code=Product.Unit.CTN, conversion_factor=carton.conversion_factor,
            converted_quantity=Decimal("60"), unit_cost=Decimal("1200"))
        receive_purchase(pur.pk, self.owner)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.stock_quantity, Decimal("60"))
        self.assertEqual(self.p1.cost_price, Decimal("100.00"))
        self.assertEqual(PurchaseItem.objects.get(purchase=pur).converted_quantity, Decimal("60"))

    def test_purchase_sets_latest_unit_cost_without_weighting_or_box_cost(self):
        pur = Purchase.objects.create(supplier=self.supplier)
        PurchaseItem.objects.create(purchase=pur, product=self.p1, quantity=2,
                                    unit_cost=Decimal("10"), box_cost=Decimal("4"))
        receive_purchase(pur.pk, self.owner)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.cost_price, Decimal("10.00"))

    def test_latest_received_purchase_sets_cost_and_selling_price(self):
        first = self.make_purchase()
        receive_purchase(first.pk, self.owner)
        second = Purchase.objects.create(supplier=self.supplier)
        PurchaseItem.objects.create(purchase=second, product=self.p1, quantity=2,
            unit_cost=Decimal("120"), selling_price=Decimal("150"))
        self.assertEqual(self.p1.__class__.objects.get(pk=self.p1.pk).selling_price, Decimal("120"))
        receive_purchase(second.pk, self.owner)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.cost_price, Decimal("120.00"))
        self.assertEqual(self.p1.selling_price, Decimal("150.00"))

    def test_total(self):
        self.assertEqual(self.make_purchase().total, Decimal("1202.50"))

    def test_pending_purchase_does_not_change_stock(self):
        self.make_purchase()
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.stock_quantity, 0)

    def test_pending_purchase_preserves_both_product_prices(self):
        pur = Purchase.objects.create(supplier=self.supplier)
        PurchaseItem.objects.create(purchase=pur, product=self.p1, quantity=1,
            unit_cost=Decimal("80"), selling_price=Decimal("100"))
        self.p1.refresh_from_db()
        self.assertEqual((self.p1.cost_price, self.p1.selling_price), (Decimal("0.00"), Decimal("120.00")))

    def test_receive_increases_stock_and_sets_cost(self):
        pur = self.make_purchase()
        receive_purchase(pur.pk, self.owner)
        self.p1.refresh_from_db(); self.p2.refresh_from_db(); pur.refresh_from_db()
        self.assertEqual((self.p1.stock_quantity, self.p2.stock_quantity), (10, 5))
        self.assertEqual(self.p1.cost_price, Decimal("100.00"))
        self.assertEqual(pur.status, Purchase.Status.RECEIVED)
        self.assertEqual(StockMovement.objects.filter(reference=f"PUR-{pur.pk}").count(), 2)

    def test_cannot_receive_twice(self):
        pur = self.make_purchase()
        receive_purchase(pur.pk, self.owner)
        with self.assertRaises(PurchaseError):
            receive_purchase(pur.pk, self.owner)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.stock_quantity, 10)

    def test_cancelled_cannot_be_received(self):
        pur = self.make_purchase()
        cancel_purchase(pur.pk, self.owner)
        with self.assertRaises(PurchaseError):
            receive_purchase(pur.pk, self.owner)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.stock_quantity, 0)
        self.assertEqual((self.p1.cost_price, self.p1.selling_price), (Decimal("0.00"), Decimal("120.00")))

    def test_empty_purchase_cannot_be_received(self):
        pur = Purchase.objects.create(supplier=self.supplier)
        with self.assertRaises(PurchaseError):
            receive_purchase(pur.pk, self.owner)

    def test_supplier_balance_counts_received_only(self):
        pur = self.make_purchase()
        self.assertEqual(self.supplier.balance, Decimal("0.00"))
        pur.amount_paid = Decimal("200.00"); pur.save()
        receive_purchase(pur.pk, self.owner)
        self.assertEqual(self.supplier.balance, Decimal("1002.50"))


class PurchaseViewTests(PurchaseBase):
    def data(self, paid="0"):
        return {
            "supplier": self.supplier.pk, "invoice_reference": "INV-9", "amount_paid": paid, "notes": "",
            "items-TOTAL_FORMS": "2", "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "1", "items-MAX_NUM_FORMS": "1000",
            "items-0-product": self.p1.pk, "items-0-quantity": "4", "items-0-unit_cost": "10.00",
            "items-1-product": self.p2.pk, "items-1-quantity": "2", "items-1-unit_cost": "5.00",
        }

    def test_owner_creates_multi_item_purchase_pending(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse("purchases:create"), self.data())
        pur = Purchase.objects.get()
        self.assertRedirects(r, reverse("purchases:detail", args=[pur.pk]))
        self.assertEqual(pur.items.count(), 2)
        self.assertEqual(pur.total, Decimal("50.00"))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.stock_quantity, 0)

    def test_purchase_form_shows_ledger_opening_stock_and_closing_preview(self):
        from apps.inventory.services import change_stock
        change_stock(self.p1, 15, StockMovement.Type.OPENING)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("purchases:create"))
        self.assertContains(response, "Opening stock")
        self.assertContains(response, "Closing stock")
        self.assertContains(response, '"stock": "15.000000"')

    def test_product_stock_endpoint_returns_current_available_stock(self):
        from apps.inventory.services import change_stock
        change_stock(self.p1, 15, StockMovement.Type.OPENING)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("purchases:product_stock", args=[self.p1.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"stock": "15.000000", "base_unit": self.p1.base_unit})

    def test_pack_requires_explicit_conversion_and_stores_converted_quantity(self):
        self.client.force_login(self.owner)
        payload = self.data()
        payload["items-0-unit_code"] = Product.Unit.PACK
        payload["items-0-quantity"] = "3"
        response = self.client.post(reverse("purchases:create"), payload)
        self.assertEqual(Purchase.objects.count(), 0)
        self.assertContains(response, "Enter how many base units are in one pack.")

        payload["items-0-conversion_factor"] = "6"
        response = self.client.post(reverse("purchases:create"), payload)
        purchase = Purchase.objects.get()
        self.assertRedirects(response, reverse("purchases:detail", args=[purchase.pk]))
        item = purchase.items.get(product=self.p1)
        self.assertEqual(item.converted_quantity, Decimal("18.000000"))

    def test_purchase_form_has_no_other_cost_and_clears_legacy_cost_on_save(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("purchases:create"))
        self.assertNotContains(response, "Other Cost")
        payload = self.data()
        payload["items-0-box_cost"] = "25"
        self.client.post(reverse("purchases:create"), payload)
        item = PurchaseItem.objects.get(product=self.p1)
        self.assertEqual(item.box_cost, Decimal("0.00"))

    def test_carton_purchase_form_stores_original_and_converted_quantities(self):
        ProductUnit.objects.create(product=self.p1, unit_code=Product.Unit.CTN,
            conversion_factor=Decimal("12"), purchase_enabled=True, selling_price=Decimal("550"))
        self.client.force_login(self.owner)
        payload = self.data()
        payload["items-0-quantity"] = "5"
        payload["items-0-unit_code"] = Product.Unit.CTN
        payload["items-0-unit_cost"] = "1200.00"
        response = self.client.post(reverse("purchases:create"), payload)
        purchase = Purchase.objects.get()
        self.assertRedirects(response, reverse("purchases:detail", args=[purchase.pk]))
        item = purchase.items.get(product=self.p1)
        self.assertEqual((item.quantity, item.unit_code, item.conversion_factor, item.converted_quantity),
                         (Decimal("5"), Product.Unit.CTN, Decimal("12"), Decimal("60")))
        self.assertEqual(item.line_total, Decimal("6000.00"))

    def test_overpayment_rejected(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse("purchases:create"), self.data(paid="999"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Purchase.objects.count(), 0)

    def test_negative_quantity_rejected(self):
        self.client.force_login(self.owner)
        d = self.data(); d["items-0-quantity"] = "-3"
        self.client.post(reverse("purchases:create"), d)
        self.assertEqual(Purchase.objects.count(), 0)

    def test_receive_via_view_and_staff_blocked(self):
        pur = self.make_purchase()
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(reverse("purchases:receive", args=[pur.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("purchases:list")).status_code, 403)
        self.client.force_login(self.owner)
        self.client.post(reverse("purchases:receive", args=[pur.pk]))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.stock_quantity, 10)

    def test_received_purchase_not_editable(self):
        pur = self.make_purchase()
        receive_purchase(pur.pk, self.owner)
        self.client.force_login(self.owner)
        r = self.client.get(reverse("purchases:edit", args=[pur.pk]))
        self.assertRedirects(r, reverse("purchases:detail", args=[pur.pk]))
