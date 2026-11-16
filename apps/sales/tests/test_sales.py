import json
import uuid
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.inventory.models import StockMovement
from apps.inventory.services import InsufficientStock, change_stock
from apps.products.models import Product
from apps.products.models import ProductUnit
from apps.sales.models import Sale, SaleItem
from apps.sales.services import SaleError, create_return, create_sale

PW = "S3cure-pass-987"


class SalesBase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password=PW, role="owner")
        self.cash = User.objects.create_user("cash", password=PW, role="staff")
        self.cust = User.objects.create_user("cust", password=PW, role="customer")
        self.rice = Product.objects.create(name="Rice", sku="R", selling_price=Decimal("100.00"), cost_price=Decimal("60.00"))
        self.tea = Product.objects.create(name="Tea", sku="T", selling_price=Decimal("200.00"),
                                          cost_price=Decimal("120.00"), discount_percent=Decimal("10"))
        change_stock(self.rice, 10, StockMovement.Type.OPENING)
        change_stock(self.tea, 5, StockMovement.Type.OPENING)

    def stock(self, p):
        p.refresh_from_db()
        return p.stock_quantity

    def sell(self, items, **kw):
        kw.setdefault("payment_method", "cash")
        return create_sale(user=self.cash, items=items, **kw)


class CreateSaleTests(SalesBase):
    def test_carton_price_and_stock_use_product_specific_conversion(self):
        ProductUnit.objects.create(product=self.rice, unit_code=Product.Unit.CTN,
            conversion_factor=Decimal("12"), purchase_enabled=True, sales_enabled=True,
            selling_price=Decimal("550"))
        change_stock(self.rice, 50, StockMovement.Type.OPENING)
        sale = self.sell([(self.rice.pk, Decimal("2"), Product.Unit.CTN)])
        item = sale.items.get()
        self.assertEqual((item.quantity, item.unit_code, item.conversion_factor, item.converted_quantity),
                         (Decimal("2"), Product.Unit.CTN, Decimal("12"), Decimal("24")))
        self.assertEqual(sale.total, Decimal("1100.00"))
        self.assertEqual(self.stock(self.rice), Decimal("36"))

    def test_kg_quantities_support_six_decimal_places(self):
        kg = Product.objects.create(name="Flour", sku="KG", selling_price=Decimal("100"), base_unit=Product.Unit.KG)
        change_stock(kg, Decimal("10"), StockMovement.Type.OPENING)
        self.sell([(kg.pk, Decimal("2.5"), Product.Unit.KG)])
        self.assertEqual(self.stock(kg), Decimal("7.5"))
        self.sell([(kg.pk, Decimal("0.000125"), Product.Unit.KG)])
        self.assertEqual(self.stock(kg), Decimal("7.499875"))

    def test_conversion_changes_do_not_rewrite_sale_snapshots(self):
        carton = ProductUnit.objects.create(product=self.rice, unit_code=Product.Unit.CTN,
            conversion_factor=Decimal("12"), purchase_enabled=True, sales_enabled=True,
            selling_price=Decimal("550"))
        change_stock(self.rice, 60, StockMovement.Type.OPENING)
        sale = self.sell([(self.rice.pk, 1, Product.Unit.CTN)])
        carton.conversion_factor = Decimal("10"); carton.save()
        item = sale.items.get()
        self.assertEqual((item.conversion_factor, item.converted_quantity), (Decimal("12"), Decimal("12")))

    def test_totals_discount_and_stock(self):
        s = self.sell([(self.rice.pk, 2), (self.tea.pk, 1)])
        self.assertEqual(s.subtotal, Decimal("400.00"))
        self.assertEqual(s.discount_total, Decimal("20.00"))
        self.assertEqual(s.total, Decimal("380.00"))
        self.assertEqual((self.stock(self.rice), self.stock(self.tea)), (8, 4))
        self.assertEqual(StockMovement.objects.filter(reference=s.receipt_number).count(), 2)

    def test_snapshots_survive_price_change(self):
        s = self.sell([(self.tea.pk, 1)])
        self.tea.selling_price = Decimal("999.00"); self.tea.cost_price = Decimal("500.00"); self.tea.save()
        item = SaleItem.objects.get(sale=s)
        self.assertEqual((item.unit_price, item.sold_price, item.unit_cost), (Decimal("200.00"), Decimal("180.00"), Decimal("120.00")))

    def test_insufficient_stock_rolls_back_everything(self):
        with self.assertRaises(InsufficientStock):
            self.sell([(self.rice.pk, 2), (self.tea.pk, 6)])
        self.assertEqual((self.stock(self.rice), self.stock(self.tea)), (10, 5))
        self.assertEqual(Sale.objects.count(), 0)

    def test_last_unit_sold_once(self):
        self.sell([(self.tea.pk, 5)])
        with self.assertRaises(InsufficientStock):
            self.sell([(self.tea.pk, 1)])

    def test_idempotency_key_prevents_duplicate(self):
        key = uuid.uuid4()
        a = self.sell([(self.rice.pk, 1)], idempotency_key=key)
        b = self.sell([(self.rice.pk, 1)], idempotency_key=key)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(self.stock(self.rice), 9)

    def test_validation_errors(self):
        for items in ([], [(self.rice.pk, 0)], [(self.rice.pk, -1)], [(self.rice.pk, True)], [(999999, 1)]):
            with self.assertRaises(SaleError):
                self.sell(items)
        with self.assertRaises(SaleError):
            self.sell([(self.rice.pk, 1)], payment_method="bitcoin")
        self.assertEqual(self.stock(self.rice), 10)

    def test_archived_product_cannot_be_sold(self):
        self.rice.is_archived = True; self.rice.save()
        with self.assertRaises(SaleError):
            self.sell([(self.rice.pk, 1)])

    def test_tendered_must_cover_total_and_change_computed(self):
        with self.assertRaises(SaleError):
            self.sell([(self.rice.pk, 1)], amount_tendered=Decimal("50"))
        self.assertEqual(self.stock(self.rice), 10)
        s = self.sell([(self.rice.pk, 1)], amount_tendered=Decimal("150"))
        self.assertEqual(s.change_due, Decimal("50.00"))

    def test_duplicate_lines_are_merged(self):
        s = self.sell([(self.rice.pk, 1), (self.rice.pk, 2)])
        self.assertEqual(s.items.count(), 1)
        self.assertEqual(s.items.get().quantity, 3)


class ReturnTests(SalesBase):
    def test_partial_return_restocks_and_refunds_paid_price(self):
        s = self.sell([(self.tea.pk, 3)])
        item = s.items.get()
        r = create_return(sale_id=s.pk, user=self.owner, quantities={item.pk: 2}, reason="Wrong item")
        item.refresh_from_db()
        self.assertEqual(r.refund_total, Decimal("360.00"))
        self.assertEqual(item.quantity_returned, 2)
        self.assertEqual(self.stock(self.tea), 4)

    def test_cannot_return_more_than_sold_cumulatively(self):
        s = self.sell([(self.rice.pk, 2)])
        item = s.items.get()
        create_return(sale_id=s.pk, user=self.owner, quantities={item.pk: 1}, reason="x")
        with self.assertRaises(SaleError):
            create_return(sale_id=s.pk, user=self.owner, quantities={item.pk: 2}, reason="x")
        self.assertEqual(self.stock(self.rice), 9)

    def test_return_without_restock_leaves_stock(self):
        s = self.sell([(self.rice.pk, 2)])
        item = s.items.get()
        create_return(sale_id=s.pk, user=self.owner, quantities={item.pk: 1}, reason="Damaged", restock=False)
        self.assertEqual(self.stock(self.rice), 8)

    def test_reason_and_selection_required(self):
        s = self.sell([(self.rice.pk, 1)])
        item = s.items.get()
        with self.assertRaises(SaleError):
            create_return(sale_id=s.pk, user=self.owner, quantities={item.pk: 1}, reason=" ")
        with self.assertRaises(SaleError):
            create_return(sale_id=s.pk, user=self.owner, quantities={item.pk: 0}, reason="x")

    def test_item_from_other_sale_rejected(self):
        s1 = self.sell([(self.rice.pk, 1)]); s2 = self.sell([(self.rice.pk, 1)])
        with self.assertRaises(SaleError):
            create_return(sale_id=s1.pk, user=self.owner, quantities={s2.items.get().pk: 1}, reason="x")
        self.assertEqual(self.stock(self.rice), 8)


class SalesViewTests(SalesBase):
    def post_checkout(self, payload):
        return self.client.post(reverse("sales:checkout"), data=json.dumps(payload), content_type="application/json")

    def test_cashier_checkout_via_api(self):
        self.client.force_login(self.cash)
        r = self.post_checkout({"items": [{"product_id": self.rice.pk, "quantity": 2}], "payment_method": "cash",
                                "idempotency_key": str(uuid.uuid4()), "amount_tendered": "500"})
        self.assertEqual(r.status_code, 201)
        sale = Sale.objects.get()
        self.assertTrue(r.json()["receipt_url"].endswith(f"/{sale.pk}/receipt/"))
        self.assertEqual(self.stock(self.rice), 8)

    def test_checkout_api_preserves_selected_unit(self):
        ProductUnit.objects.create(product=self.rice, unit_code=Product.Unit.CTN,
            conversion_factor=Decimal("12"), purchase_enabled=True, sales_enabled=True,
            selling_price=Decimal("550"))
        change_stock(self.rice, 50, StockMovement.Type.OPENING)
        self.client.force_login(self.cash)
        response = self.post_checkout({"items": [{"product_id": self.rice.pk, "quantity": "2", "unit_code": "CTN"}],
                                       "payment_method": "cash", "idempotency_key": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 201)
        sale = Sale.objects.get()
        self.assertEqual((sale.total, sale.items.get().converted_quantity, self.stock(self.rice)),
                         (Decimal("1100.00"), Decimal("24"), Decimal("36")))

    def test_api_error_responses(self):
        self.client.force_login(self.cash)
        self.assertEqual(self.post_checkout({"items": [{"product_id": self.rice.pk, "quantity": 99}], "payment_method": "cash"}).status_code, 400)
        self.assertEqual(self.client.post(reverse("sales:checkout"), data="not json", content_type="application/json").status_code, 400)
        self.assertEqual(self.post_checkout({"items": [{"product_id": "x", "quantity": 1}], "payment_method": "cash"}).status_code, 400)
        self.assertEqual(Sale.objects.count(), 0)

    def test_customer_and_anonymous_blocked(self):
        self.assertEqual(self.client.post(reverse("sales:checkout")).status_code, 302)
        self.client.force_login(self.cust)
        self.assertEqual(self.post_checkout({"items": [], "payment_method": "cash"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("sales:pos")).status_code, 403)

    def test_search_api(self):
        self.client.force_login(self.cash)
        data = self.client.get(reverse("sales:search"), {"q": "tea"}).json()["results"]
        self.assertEqual(data[0]["price"], "180.00")
        exact = self.client.get(reverse("sales:search"), {"q": self.tea.barcode, "scan": "1"}).json()["results"]
        self.assertEqual([item["id"] for item in exact], [self.tea.pk])
        self.assertEqual(self.client.get(reverse("sales:search"), {"q": "missing", "scan": "1"}).json()["results"], [])
        self.assertEqual(self.client.get(reverse("sales:search"), {"q": ""}).json()["results"], [])

    def test_receipt_and_pos_pages_render(self):
        s = self.sell([(self.rice.pk, 1)])
        self.client.force_login(self.cash)
        self.assertContains(self.client.get(reverse("sales:receipt", args=[s.pk])), s.receipt_number)
        self.assertEqual(self.client.get(reverse("sales:pos")).status_code, 200)
        self.assertEqual(self.client.get(reverse("sales:list"), {"q": s.receipt_number}).status_code, 200)

    def test_returns_are_owner_only(self):
        s = self.sell([(self.rice.pk, 2)])
        item = s.items.get()
        self.client.force_login(self.cash)
        r = self.client.post(reverse("sales:return", args=[s.pk]), {f"qty_{item.pk}": "1", "reason": "x", "restock": "on"})
        self.assertEqual(r.status_code, 403)
        self.client.force_login(self.owner)
        r = self.client.post(reverse("sales:return", args=[s.pk]), {f"qty_{item.pk}": "1", "reason": "x", "restock": "on"})
        self.assertRedirects(r, reverse("sales:receipt", args=[s.pk]))
        self.assertEqual(self.stock(self.rice), 9)

    def test_return_form_rejects_bad_numbers(self):
        s = self.sell([(self.rice.pk, 2)])
        item = s.items.get()
        self.client.force_login(self.owner)
        r = self.client.post(reverse("sales:return", args=[s.pk]), {f"qty_{item.pk}": "-1", "reason": "x"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post(reverse("sales:return", args=[s.pk]), {f"qty_{item.pk}": "9", "reason": "x"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.stock(self.rice), 8)
