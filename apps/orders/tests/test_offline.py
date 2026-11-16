"""Offline order synchronisation: idempotency, server-side pricing, stock safety and permissions."""
import uuid
from decimal import Decimal

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import AuditLog
from apps.inventory.models import StockMovement
from apps.orders.models import Cart, Order, OfflineOrderSync
from apps.orders.offline import cart_snapshot, replace_cart
from apps.orders.services import cart_add
from apps.orders.tests.test_orders import FEES, PW, OrderBase
from apps.payments.models import Payment

URL = "/api/v1/offline/orders/"
CART_URL = "/api/v1/offline/cart/"


def payload(items, key=None, **kw):
    d = {"client_order_id": str(key or uuid.uuid4()), "payment_method": "cod", "customer_name": "Ali Khan",
         "phone": "03001234567", "address": "House 1, Street 2, Lahore", "delivery_instructions": "Ring the bell",
         "created_at": "2026-11-05T09:00:00Z", "items": [{"product_id": p.pk, "quantity": q, "unit_price": str(price)}
                                                          for p, q, price in items]}
    d.update(kw)
    return d


@override_settings(**FEES)
class OfflineOrderTests(OrderBase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def client_for(self, user, **kw):
        c = APIClient(**kw)
        if user:
            c.force_authenticate(user)
        return c

    def send(self, data, user=None):
        return self.client_for(user or self.c1).post(URL, data, format="json")

    # ---- happy path ----
    def test_offline_order_is_created_with_server_prices_and_stock_deducted(self):
        r = self.send(payload([(self.rice, 2, "100.00"), (self.tea, 1, "180.00")], customer_ref=self.c1.pk,
                              client_total="530.00"))
        self.assertEqual(r.status_code, 201, r.json())
        self.assertEqual(r.json()["status"], "confirmed")
        order = Order.objects.get()
        self.assertEqual((order.source, order.status, order.customer), ("offline", "pending", self.c1))
        self.assertEqual(order.client_created_at.isoformat(), "2026-11-05T09:00:00+00:00")
        self.assertEqual(order.subtotal, Decimal("400.00"))
        self.assertEqual(order.discount_total, Decimal("20.00"))
        self.assertEqual(order.delivery_fee, Decimal("150.00"))
        self.assertEqual(order.total, Decimal("530.00"))
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(order.payments.get().method, Payment.Method.COD)
        self.assertEqual((self.stock(self.rice), self.stock(self.tea)), (8, 2))
        self.assertEqual(StockMovement.objects.filter(reference=order.number).count(), 2)
        self.assertEqual(OfflineOrderSync.objects.get().outcome, "confirmed")
        self.assertTrue(AuditLog.objects.filter(action="order.placed", target=order.number).exists())

    def test_same_product_listed_twice_is_one_line(self):
        r = self.send(payload([(self.rice, 1, "100.00"), (self.rice, 2, "100.00")]))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Order.objects.get().items.get().quantity, 3)

    # ---- idempotency ----
    def test_duplicate_sync_creates_one_order_and_deducts_stock_once(self):
        key = uuid.uuid4()
        data = payload([(self.rice, 3, "100.00")], key=key)
        first, second, third = self.send(data), self.send(data), self.send(data)
        self.assertEqual((first.status_code, second.status_code, third.status_code), (201, 200, 200))
        self.assertEqual(first.json()["order_id"], second.json()["order_id"])
        self.assertFalse(second.json()["created"])
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(self.stock(self.rice), 7)
        self.assertEqual(StockMovement.objects.filter(movement_type="online_order").count(), 1)

    def test_same_uuid_used_by_online_checkout_is_not_duplicated(self):
        key = uuid.uuid4()
        order = self.order(key=key)
        before = self.stock(self.rice)
        r = self.send(payload([(self.rice, 1, "100.00")], key=key))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["order_id"], order.pk)
        self.assertEqual((Order.objects.count(), self.stock(self.rice)), (1, before))

    def test_online_orders_are_marked_online(self):
        self.assertEqual(self.order().source, "online")

    # ---- never trust the client ----
    def test_client_cannot_lower_the_price(self):
        r = self.send(payload([(self.rice, 1, "1.00")], client_total="1.00"))
        body = r.json()
        self.assertEqual((r.status_code, body["status"], body["reason_code"]), (409, "requires_attention", "price_changed"))
        self.assertEqual(body["server_total"], "250.00")
        self.assertEqual((Order.objects.count(), self.stock(self.rice)), (0, 10))

    def test_price_increase_needs_customer_agreement_then_goes_through(self):
        data = payload([(self.rice, 1, "90.00")], client_total="240.00")
        self.assertEqual(self.send(data).json()["reason_code"], "price_changed")
        self.assertEqual(Order.objects.count(), 0)
        data["accepted_total"] = "250.00"                       # the customer tapped "Accept new total"
        r = self.send(data)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Order.objects.get().total, Decimal("250.00"))

    def test_price_drop_is_accepted_at_the_lower_server_price(self):
        r = self.send(payload([(self.rice, 1, "150.00")], client_total="300.00"))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Order.objects.get().total, Decimal("250.00"))

    def test_free_delivery_threshold_is_applied_by_the_server(self):
        r = self.send(payload([(self.big, 1, "2500.00")], client_total="2500.00"))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Order.objects.get().delivery_fee, Decimal("0.00"))

    # ---- stock & availability ----
    def test_insufficient_stock_is_rejected_and_nothing_changes(self):
        r = self.send(payload([(self.rice, 11, "100.00"), (self.tea, 1, "180.00")]))
        body = r.json()
        self.assertEqual((r.status_code, body["status"], body["reason_code"]), (409, "rejected", "insufficient_stock"))
        self.assertIn("Only 10 of", body["reason"])
        self.assertEqual((Order.objects.count(), self.stock(self.rice), self.stock(self.tea)), (0, 10, 3))
        self.assertEqual(OfflineOrderSync.objects.get().outcome, "rejected")

    def test_rejection_is_final_for_the_same_uuid(self):
        key = uuid.uuid4()
        data = payload([(self.rice, 11, "100.00")], key=key)
        self.assertEqual(self.send(data).status_code, 409)
        from apps.inventory.services import change_stock
        change_stock(self.rice, 50, StockMovement.Type.PURCHASE)    # restocked afterwards
        again = self.send(data)
        self.assertEqual((again.status_code, again.json()["status"]), (409, "rejected"))
        self.assertEqual(Order.objects.count(), 0)                  # the customer must press "Try again" (new UUID)

    def test_last_unit_is_never_sold_twice(self):
        data1, data2 = payload([(self.tea, 3, "180.00")]), payload([(self.tea, 1, "180.00")])
        self.assertEqual(self.send(data1).status_code, 201)
        r = self.send(data2)
        self.assertEqual((r.status_code, r.json()["reason_code"]), (409, "insufficient_stock"))
        self.assertEqual(self.stock(self.tea), 0)

    def test_unavailable_products_are_rejected(self):
        self.rice.is_archived = True
        self.rice.save()
        r = self.send(payload([(self.rice, 1, "100.00")]))
        self.assertEqual((r.status_code, r.json()["reason_code"]), (409, "unavailable"))
        r = self.send(payload([(self.offline, 1, "10.00")]))
        self.assertEqual(r.json()["reason_code"], "unavailable")
        self.assertEqual(Order.objects.count(), 0)

    def test_unknown_product_is_rejected(self):
        data = payload([(self.rice, 1, "100.00")])
        data["items"][0]["product_id"] = 999999
        self.assertEqual(self.send(data).json()["reason_code"], "unavailable")

    # ---- validation, permissions, CSRF ----
    def test_invalid_data_is_rejected_with_400(self):
        for bad in ({"phone": "abc"}, {"address": "x"}, {"items": []}, {"client_order_id": "nope"},
                    {"items": [{"product_id": self.rice.pk, "quantity": 0}]},
                    {"items": [{"product_id": self.rice.pk, "quantity": 101}]}):
            r = self.send({**payload([(self.rice, 1, "100.00")]), **bad})
            self.assertEqual((r.status_code, r.json()["status"]), (400, "rejected"), bad)
        self.assertEqual(Order.objects.count(), 0)

    def test_online_payment_cannot_be_completed_offline(self):
        r = self.send(payload([(self.rice, 1, "100.00")], payment_method="card"))
        self.assertEqual((r.status_code, r.json()["reason_code"]), (409, "payment_required"))
        self.assertEqual(Order.objects.count(), 0)

    def test_order_for_another_account_is_refused(self):
        r = self.send(payload([(self.rice, 1, "100.00")], customer_ref=self.c2.pk))
        self.assertEqual((r.status_code, r.json()["reason_code"]), (403, "wrong_account"))
        self.assertEqual(Order.objects.count(), 0)

    def test_another_customer_cannot_replay_or_read_an_order_uuid(self):
        key = uuid.uuid4()
        self.assertEqual(self.send(payload([(self.rice, 1, "100.00")], key=key)).status_code, 201)
        r = self.send(payload([(self.rice, 1, "100.00")], key=key), user=self.c2)
        self.assertEqual((r.status_code, r.json()["reason_code"]), (403, "wrong_account"))
        self.assertEqual((Order.objects.count(), self.stock(self.rice)), (1, 9))

    def test_anonymous_staff_and_owner_cannot_use_the_endpoint(self):
        data = payload([(self.rice, 1, "100.00")])
        self.assertIn(self.client_for(None).post(URL, data, format="json").status_code, (401, 403))
        self.assertEqual(self.client_for(self.staff).post(URL, data, format="json").status_code, 403)
        self.assertEqual(self.client_for(self.owner).post(URL, data, format="json").status_code, 403)
        self.assertEqual(Order.objects.count(), 0)

    def test_csrf_is_enforced(self):
        c = APIClient(enforce_csrf_checks=True)
        c.login(username="c1", password=PW)                      # real session: force_authenticate would skip CSRF
        data = payload([(self.rice, 1, "100.00")])
        self.assertEqual(c.post(URL, data, format="json").status_code, 403)
        self.assertEqual(Order.objects.count(), 0)
        token = c.get("/api/v1/auth/csrf/").json()["csrfToken"]
        self.assertEqual(c.post(URL, data, format="json", HTTP_X_CSRFTOKEN=token).status_code, 201)

    def test_offline_orders_appear_in_the_order_api_and_admin_list(self):
        self.send(payload([(self.rice, 1, "100.00")]))
        r = self.client_for(self.c1).get("/api/v1/orders/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client_for(self.c2).get("/api/v1/orders/").json()["results"], [])


@override_settings(**FEES)
class OfflineCartTests(OrderBase):
    def client_for(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_replace_cart_sets_exact_contents_clamped_to_stock(self):
        cart_add(self.c1, self.tea.pk, 1)
        r = self.client_for(self.c1).put(CART_URL, {"items": [{"product_id": self.rice.pk, "quantity": 4},
                                                              {"product_id": self.tea.pk, "quantity": 50}]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        lines = {i["product_id"]: i["quantity"] for i in r.json()["items"]}
        self.assertEqual(lines, {self.rice.pk: 4, self.tea.pk: 3})   # tea clamped to its 3 in stock
        again = self.client_for(self.c1).put(CART_URL, {"items": [{"product_id": self.rice.pk, "quantity": 4}]}, format="json")
        self.assertEqual([i["product_id"] for i in again.json()["items"]], [self.rice.pk])   # idempotent replace removes tea

    def test_replace_cart_skips_unavailable_products_and_can_empty_the_cart(self):
        cart_add(self.c1, self.rice.pk, 1)
        r = self.client_for(self.c1).put(CART_URL, {"items": [{"product_id": self.offline.pk, "quantity": 1}]}, format="json")
        self.assertEqual(r.json()["skipped"], [self.offline.pk])
        self.assertEqual(r.json()["items"], [])
        self.assertEqual(Cart.objects.get(user=self.c1).items.count(), 0)

    def test_snapshot_matches_cart_and_is_private(self):
        cart_add(self.c1, self.tea.pk, 2)
        r = self.client_for(self.c1).get(CART_URL)
        item = r.json()["items"][0]
        self.assertEqual((item["product_id"], item["quantity"], item["price"], item["stock"]), (self.tea.pk, 2, "180.00", 3))
        self.assertIn("no-store", r["Cache-Control"])
        self.assertEqual(self.client_for(self.c2).get(CART_URL).json()["items"], [])
        self.assertEqual(self.client_for(self.staff).get(CART_URL).status_code, 403)

    def test_service_functions_directly(self):
        self.assertEqual(replace_cart(self.c1, [{"product_id": self.rice.pk, "quantity": 2}]), [])
        self.assertEqual(cart_snapshot(self.c1)["items"][0]["quantity"], 2)
