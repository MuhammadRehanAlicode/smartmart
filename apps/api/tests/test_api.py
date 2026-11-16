import uuid
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.models import AuditLog
from apps.inventory.models import StockMovement
from apps.inventory.services import change_stock
from apps.orders.models import Order
from apps.products.models import Product
from apps.purchases.models import Purchase
from apps.suppliers.models import Supplier

PW = "S3cure-pass-987"
V1 = "/api/v1/"


class ApiBase(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user("owner", password=PW, role="owner")
        self.staff = User.objects.create_user("cash", password=PW, role="staff")
        self.c1 = User.objects.create_user("c1", password=PW, role="customer", first_name="Ali", phone="03001234567")
        self.c2 = User.objects.create_user("c2", password=PW, role="customer", first_name="Sara", phone="03007654321")
        self.rice = Product.objects.create(name="Rice", sku="R", selling_price=Decimal("100.00"), cost_price=Decimal("60.00"))
        self.tea = Product.objects.create(name="Tea", sku="T", selling_price=Decimal("200.00"), cost_price=Decimal("120.00"))
        change_stock(self.rice, 10, StockMovement.Type.OPENING)
        change_stock(self.tea, 2, StockMovement.Type.OPENING)

    def as_user(self, user):
        c = APIClient()
        if user:
            c.force_authenticate(user)
        return c

    def stock(self, p):
        p.refresh_from_db()
        return p.stock_quantity


class AuthAndErrorTests(ApiBase):
    def test_anonymous_is_blocked_everywhere(self):
        c = self.as_user(None)
        for url in ("products/", "sales/", "orders/", "cart/", "customers/", "suppliers/", "purchases/", "reports/summary/", "auth/me/"):
            self.assertIn(c.get(V1 + url).status_code, (401, 403), url)

    def test_error_format(self):
        r = self.as_user(self.owner).post(V1 + "products/", {"name": "x"}, format="json")
        self.assertEqual(r.status_code, 400)
        err = r.json()["error"]
        self.assertEqual((err["status"], err["code"]), (400, "invalid"))
        self.assertIn("selling_price", err["details"])
        r = self.as_user(self.staff).post(V1 + "products/", {}, format="json")
        self.assertEqual(r.json()["error"]["status"], 403)

    def test_login_requires_csrf_and_logout_works(self):
        c = APIClient(enforce_csrf_checks=True)
        r = c.post(V1 + "auth/login/", {"username": "owner", "password": PW}, format="json")
        self.assertEqual(r.status_code, 403)
        token = c.get(V1 + "auth/csrf/").json()["csrfToken"]
        r = c.post(V1 + "auth/login/", {"username": "owner", "password": PW}, format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["role"], "owner")
        self.assertEqual(c.get(V1 + "auth/me/").json()["username"], "owner")
        self.assertEqual(c.post(V1 + "auth/logout/", format="json").status_code, 403)    # CSRF needed to log out too
        token = c.get(V1 + "auth/csrf/").json()["csrfToken"]
        self.assertEqual(c.post(V1 + "auth/logout/", format="json", HTTP_X_CSRFTOKEN=token).status_code, 204)

    def test_bad_login_and_lockout(self):
        c = APIClient()
        for _ in range(5):
            self.assertEqual(c.post(V1 + "auth/login/", {"username": "owner", "password": "wrong"}, format="json").status_code, 400)
        self.assertEqual(c.post(V1 + "auth/login/", {"username": "owner", "password": PW}, format="json").status_code, 429)

    def test_me_cannot_change_role(self):
        c = self.as_user(self.c1)
        r = c.patch(V1 + "auth/me/", {"first_name": "Alii", "role": "owner", "phone": "03111111111"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.c1.refresh_from_db()
        self.assertEqual((self.c1.role, self.c1.first_name), ("customer", "Alii"))
        self.assertEqual(c.patch(V1 + "auth/me/", {"phone": "bad"}, format="json").status_code, 400)


class ProductApiTests(ApiBase):
    def payload(self, **kw):
        d = {"name": "Salt", "sku": "salt1", "selling_price": "50.00", "cost_price": "30.00", "opening_stock": 7}
        d.update(kw)
        return d

    def test_staff_reads_without_cost_owner_sees_cost(self):
        self.assertNotIn("cost_price", self.as_user(self.staff).get(V1 + "products/").json()["results"][0])
        self.assertIn("cost_price", self.as_user(self.owner).get(V1 + "products/").json()["results"][0])

    def test_owner_creates_with_opening_stock_and_sku_normalised(self):
        r = self.as_user(self.owner).post(V1 + "products/", self.payload(), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        p = Product.objects.get(sku="SALT1")
        self.assertEqual(p.stock_quantity, 7)
        self.assertEqual(StockMovement.objects.get(product=p).movement_type, "opening")
        self.assertEqual(self.as_user(self.owner).post(V1 + "products/", self.payload(sku="Salt1"), format="json").status_code, 400)

    def test_validation(self):
        c = self.as_user(self.owner)
        for bad in ({"selling_price": "-1"}, {"selling_price": "0"}, {"discount_percent": "101"}, {"cost_price": "-1"}, {"opening_stock": -5}):
            self.assertEqual(c.post(V1 + "products/", self.payload(sku="X" + str(abs(hash(str(bad))) % 9999), **bad), format="json").status_code, 400, bad)

    def test_staff_cannot_write_and_no_delete(self):
        self.assertEqual(self.as_user(self.staff).post(V1 + "products/", self.payload(), format="json").status_code, 403)
        self.assertEqual(self.as_user(self.staff).patch(f"{V1}products/{self.rice.pk}/", {"selling_price": "1"}, format="json").status_code, 403)
        self.assertEqual(self.as_user(self.owner).delete(f"{V1}products/{self.rice.pk}/").status_code, 405)

    def test_price_patch_audited_and_stock_not_writable(self):
        r = self.as_user(self.owner).patch(f"{V1}products/{self.rice.pk}/", {"selling_price": "120.00", "stock_quantity": 999}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.stock(self.rice), 10)
        self.assertTrue(AuditLog.objects.filter(action="product.price_changed", target="R").exists())

    def test_adjust_archive_restore(self):
        c = self.as_user(self.owner)
        self.assertEqual(c.post(f"{V1}products/{self.rice.pk}/adjust-stock/", {"quantity_change": -3, "reason": "Damaged"}, format="json").status_code, 200)
        self.assertEqual(self.stock(self.rice), 7)
        self.assertEqual(c.post(f"{V1}products/{self.rice.pk}/adjust-stock/", {"quantity_change": -30, "reason": "x"}, format="json").status_code, 409)
        self.assertEqual(c.post(f"{V1}products/{self.rice.pk}/adjust-stock/", {"quantity_change": 1, "reason": ""}, format="json").status_code, 400)
        self.assertEqual(self.as_user(self.staff).post(f"{V1}products/{self.rice.pk}/adjust-stock/", {"quantity_change": 1, "reason": "x"}, format="json").status_code, 403)
        c.post(f"{V1}products/{self.rice.pk}/archive/")
        self.assertNotIn("Rice", str(c.get(V1 + "products/").json()))
        self.assertEqual(c.get(f"{V1}products/{self.rice.pk}/").status_code, 200)
        c.post(f"{V1}products/{self.rice.pk}/restore/")
        self.assertIn("Rice", str(c.get(V1 + "products/").json()))

    def test_pagination_search_filters(self):
        for i in range(25):
            Product.objects.create(name=f"Bulk {i:02d}", sku=f"B{i}", selling_price=Decimal("1.00"))
        c = self.as_user(self.staff)
        r = c.get(V1 + "products/").json()
        self.assertEqual((r["count"], len(r["results"])), (27, 20))
        self.assertEqual(len(c.get(V1 + "products/?page_size=1000").json()["results"]), 27)       # capped at 100, 27 exist
        self.assertEqual(c.get(V1 + "products/?search=rice").json()["count"], 1)
        self.assertEqual(c.get(V1 + "products/?stock=low").json()["count"], 1)                     # only tea (2 <= 5); rice has 10
        self.assertGreater(c.get(V1 + "products/?stock=out").json()["count"], 0)
        self.assertEqual(c.get(V1 + "products/?ordering=-selling_price").json()["results"][0]["name"], "Tea")


class StockMovementApiTests(ApiBase):
    def test_read_only_filters_and_bad_dates(self):
        c = self.as_user(self.staff)
        self.assertEqual(c.get(V1 + "stock-movements/").json()["count"], 2)
        self.assertEqual(c.get(f"{V1}stock-movements/?product={self.tea.pk}").json()["count"], 1)
        self.assertEqual(c.get(V1 + "stock-movements/?date_from=garbage").status_code, 400)
        self.assertEqual(c.post(V1 + "stock-movements/", {}, format="json").status_code, 405)
        self.assertIn(self.as_user(self.c1).get(V1 + "stock-movements/").status_code, (403,))


class SalesApiTests(ApiBase):
    def sale(self, client, items, **kw):
        return client.post(V1 + "sales/", {"items": items, "payment_method": "cash", **kw}, format="json")

    def test_staff_sale_hides_cost_and_reduces_stock(self):
        r = self.sale(self.as_user(self.staff), [{"product_id": self.rice.pk, "quantity": 3}])
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body["total"], "300.00")
        self.assertNotIn("unit_cost", body["items"][0])
        self.assertEqual(self.stock(self.rice), 7)
        owner_view = self.as_user(self.owner).get(f"{V1}sales/{body['id']}/").json()
        self.assertEqual(owner_view["items"][0]["unit_cost"], "60.00")

    def test_conflict_validation_and_idempotency(self):
        c = self.as_user(self.staff)
        self.assertEqual(self.sale(c, [{"product_id": self.tea.pk, "quantity": 5}]).status_code, 409)
        self.assertEqual(self.sale(c, []).status_code, 400)
        self.assertEqual(self.sale(c, [{"product_id": self.rice.pk, "quantity": 0}]).status_code, 400)
        self.assertEqual(self.sale(c, [{"product_id": 99999, "quantity": 1}]).status_code, 400)
        self.assertEqual(self.sale(c, [{"product_id": self.rice.pk, "quantity": 1}], payment_method="bitcoin").status_code, 400)
        self.assertEqual(self.sale(c, [{"product_id": self.rice.pk, "quantity": 1}], amount_tendered="5").status_code, 400)
        key = str(uuid.uuid4())
        a = self.sale(c, [{"product_id": self.rice.pk, "quantity": 1}], idempotency_key=key).json()["id"]
        b = self.sale(c, [{"product_id": self.rice.pk, "quantity": 1}], idempotency_key=key).json()["id"]
        self.assertEqual(a, b)
        self.assertEqual(self.stock(self.rice), 9)

    def test_returns_owner_only(self):
        sale = self.sale(self.as_user(self.staff), [{"product_id": self.rice.pk, "quantity": 2}]).json()
        item_id = sale["items"][0]["id"]
        url = f"{V1}sales/{sale['id']}/return/"
        body = {"items": [{"sale_item_id": item_id, "quantity": 1}], "reason": "Wrong item"}
        self.assertEqual(self.as_user(self.staff).post(url, body, format="json").status_code, 403)
        r = self.as_user(self.owner).post(url, body, format="json")
        self.assertEqual((r.status_code, r.json()["refund_total"]), (201, "100.00"))
        self.assertEqual(self.stock(self.rice), 9)
        over = {"items": [{"sale_item_id": item_id, "quantity": 5}], "reason": "x"}
        self.assertEqual(self.as_user(self.owner).post(url, over, format="json").status_code, 400)

    def test_customers_cannot_use_sales(self):
        self.assertEqual(self.sale(self.as_user(self.c1), [{"product_id": self.rice.pk, "quantity": 1}]).status_code, 403)
        self.assertEqual(self.as_user(self.c1).get(V1 + "sales/").status_code, 403)


class PurchaseSupplierApiTests(ApiBase):
    def test_supplier_crud_owner_only(self):
        o = self.as_user(self.owner)
        r = o.post(V1 + "suppliers/", {"name": "Metro", "phone": "03001112222"}, format="json")
        self.assertEqual(r.status_code, 201)
        sid = r.json()["id"]
        self.assertEqual(o.patch(f"{V1}suppliers/{sid}/", {"is_active": False}, format="json").status_code, 200)
        self.assertEqual(o.post(V1 + "suppliers/", {"name": "Bad", "phone": "x"}, format="json").status_code, 400)
        self.assertEqual(self.as_user(self.staff).get(V1 + "suppliers/").status_code, 403)

    def test_purchase_create_receive_cancel(self):
        sup = Supplier.objects.create(name="Metro")
        o = self.as_user(self.owner)
        body = {"supplier": sup.pk, "invoice_reference": "INV-1", "amount_paid": "100.00",
                "items": [{"product": self.rice.pk, "quantity": 10, "unit_cost": "70.00"}, {"product": self.tea.pk, "quantity": 5, "unit_cost": "130.00"}]}
        r = o.post(V1 + "purchases/", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        data = r.json()
        self.assertEqual((data["total"], data["status"], data["balance_due"]), ("1350.00", "pending", "1250.00"))
        self.assertEqual(self.stock(self.rice), 10)                       # not received yet
        self.assertEqual(o.post(f"{V1}purchases/{data['id']}/receive/").status_code, 200)
        self.assertEqual((self.stock(self.rice), self.stock(self.tea)), (20, 7))
        self.assertEqual(o.post(f"{V1}purchases/{data['id']}/receive/").status_code, 400)
        self.assertEqual(o.post(f"{V1}purchases/{data['id']}/cancel/").status_code, 400)

    def test_purchase_validation(self):
        sup = Supplier.objects.create(name="Metro")
        o = self.as_user(self.owner)
        item = {"product": self.rice.pk, "quantity": 1, "unit_cost": "10.00"}
        for bad in ({"items": []}, {"items": [{**item, "quantity": 0}]}, {"items": [{**item, "unit_cost": "0"}]},
                    {"items": [item], "amount_paid": "999"}, {"supplier": 9999, "items": [item]}):
            self.assertEqual(o.post(V1 + "purchases/", {"supplier": sup.pk, **bad}, format="json").status_code, 400, bad)
        self.assertEqual(Purchase.objects.count(), 0)
        self.assertEqual(self.as_user(self.staff).post(V1 + "purchases/", {}, format="json").status_code, 403)


class StorefrontApiTests(ApiBase):
    def checkout(self, client, key=None, **kw):
        d = {"customer_name": "Ali Khan", "phone": "03001234567", "address": "House 1, Street 2, Lahore",
             "idempotency_key": key or str(uuid.uuid4())}
        d.update(kw)
        return client.post(V1 + "checkout/", d, format="json")

    def test_cart_flow_and_isolation(self):
        c1 = self.as_user(self.c1)
        r = c1.post(V1 + "cart/", {"product_id": self.rice.pk, "quantity": 500}, format="json")
        self.assertEqual(r.status_code, 400)                      # quantity above the per-line API cap
        r = c1.post(V1 + "cart/", {"product_id": self.rice.pk, "quantity": 20}, format="json")
        self.assertEqual(r.status_code, 201)
        item = r.json()["items"][0]
        self.assertEqual(item["quantity"], 10)                    # clamped to stock
        self.assertEqual(self.as_user(self.c2).patch(f"{V1}cart/items/{item['id']}/", {"quantity": 1}, format="json").status_code, 404)
        self.assertEqual(c1.patch(f"{V1}cart/items/{item['id']}/", {"quantity": 2}, format="json").json()["items"][0]["quantity"], 2)
        self.assertEqual(c1.delete(f"{V1}cart/items/{item['id']}/").status_code, 204)
        self.assertEqual(self.as_user(self.staff).get(V1 + "cart/").status_code, 403)

    def test_checkout_creates_one_order_per_key(self):
        c1 = self.as_user(self.c1)
        c1.post(V1 + "cart/", {"product_id": self.rice.pk, "quantity": 2}, format="json")
        key = str(uuid.uuid4())
        a = self.checkout(c1, key)
        self.assertEqual(a.status_code, 201, a.content)
        b = self.checkout(c1, key)
        self.assertEqual((b.status_code, b.json()["id"]), (200, a.json()["id"]))
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(self.stock(self.rice), 8)
        self.assertEqual(a.json()["status"], "pending")

    def test_checkout_errors(self):
        c1 = self.as_user(self.c1)
        self.assertEqual(self.checkout(c1).status_code, 400)                          # empty cart
        c1.post(V1 + "cart/", {"product_id": self.tea.pk, "quantity": 2}, format="json")
        change_stock(self.tea, -1, StockMovement.Type.SALE)
        self.assertEqual(self.checkout(c1).status_code, 409)                          # stock vanished
        for bad in ({"phone": "abc"}, {"address": "short"}, {"customer_name": ""}, {"idempotency_key": "nope"}):
            self.assertEqual(self.checkout(c1, **bad).status_code, 400, bad)
        self.assertEqual(Order.objects.count(), 0)

    def test_order_visibility_cancel_and_staff_status(self):
        c1, c2, st = self.as_user(self.c1), self.as_user(self.c2), self.as_user(self.staff)
        c1.post(V1 + "cart/", {"product_id": self.rice.pk, "quantity": 3}, format="json")
        oid = self.checkout(c1).json()["id"]
        self.assertEqual(c2.get(f"{V1}orders/{oid}/").status_code, 404)
        self.assertEqual(c2.get(V1 + "orders/").json()["count"], 0)
        self.assertEqual(c2.post(f"{V1}orders/{oid}/cancel/", {}, format="json").status_code, 404)
        self.assertEqual(c1.post(f"{V1}orders/{oid}/status/", {"status": "confirmed"}, format="json").status_code, 403)
        self.assertEqual(st.get(V1 + "orders/").json()["count"], 1)
        self.assertEqual(st.post(f"{V1}orders/{oid}/status/", {"status": "delivered"}, format="json").status_code, 400)
        self.assertEqual(st.post(f"{V1}orders/{oid}/status/", {"status": "bogus"}, format="json").status_code, 400)
        self.assertEqual(st.post(f"{V1}orders/{oid}/status/", {"status": "confirmed"}, format="json").json()["status"], "confirmed")
        r = c1.post(f"{V1}orders/{oid}/cancel/", {}, format="json")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "cancelled"))
        self.assertEqual(self.stock(self.rice), 10)

    def test_customers_listing_staff_only(self):
        self.assertEqual(self.as_user(self.staff).get(V1 + "customers/?search=ali").json()["count"], 1)
        self.assertEqual(self.as_user(self.c1).get(V1 + "customers/").status_code, 403)
        self.assertNotIn("password", str(self.as_user(self.staff).get(V1 + "customers/").json()))


class ReportApiTests(ApiBase):
    def test_owner_only_and_figures(self):
        self.as_user(self.staff).post(V1 + "sales/", {"items": [{"product_id": self.rice.pk, "quantity": 3}], "payment_method": "cash"}, format="json")
        o = self.as_user(self.owner)
        s = o.get(V1 + "reports/summary/").json()
        self.assertEqual((s["revenue"], s["cogs"], s["gross_profit"]), ("300.00", "180.00", "120.00"))
        self.assertEqual(o.get(V1 + "reports/daily/?date_from=2000-01-01&date_to=2000-01-03").json()["days"][0]["revenue"], "0.00")
        self.assertEqual(o.get(V1 + "reports/best-sellers/").json()["results"][0]["units"], 3)
        self.assertEqual(o.get(V1 + "reports/summary/?date_from=nonsense").status_code, 400)
        for who in (self.staff, self.c1):
            self.assertEqual(self.as_user(who).get(V1 + "reports/summary/").status_code, 403)
