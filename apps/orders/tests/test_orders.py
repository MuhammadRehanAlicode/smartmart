import uuid
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.finance.calculations import summary
from apps.inventory.models import StockMovement
from apps.inventory.services import InsufficientStock, change_stock
from apps.orders.models import Cart, Order
from apps.orders.services import (OrderError, cart_add, cart_set, cart_totals, place_order, update_order_status)
from apps.payments.gateways import GATEWAYS, PaymentGateway, VerificationResult
from apps.payments.models import Payment
from apps.payments.services import PaymentError, record_verified_payment
from apps.products.models import Product

PW = "S3cure-pass-987"
FEES = dict(DELIVERY_FEE=Decimal("150.00"), FREE_DELIVERY_THRESHOLD=Decimal("2000.00"))


class OrderBase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password=PW, role="owner")
        self.staff = User.objects.create_user("cash", password=PW, role="staff")
        self.c1 = User.objects.create_user("c1", password=PW, role="customer", first_name="Ali", phone="03001234567")
        self.c2 = User.objects.create_user("c2", password=PW, role="customer", first_name="Sara", phone="03007654321")
        self.rice = self.make("Rice", "R", 100, 60, 10)
        self.tea = self.make("Tea", "T", 200, 120, 3, discount=10)
        self.big = self.make("Generator", "G", 2500, 2000, 5)
        self.offline = self.make("Offline", "O", 10, 5, 5, online=False)

    def make(self, name, sku, price, cost, stock, discount=0, online=True):
        p = Product.objects.create(name=name, sku=sku, selling_price=Decimal(price), cost_price=Decimal(cost),
                                   discount_percent=Decimal(discount), is_online=online)
        change_stock(p, stock, StockMovement.Type.OPENING)
        return p

    def stock(self, p):
        p.refresh_from_db()
        return p.stock_quantity

    def order(self, user=None, key=None, lines=((None, 1),)):
        user = user or self.c1
        for product, qty in lines:
            cart_add(user, (product or self.rice).pk, qty)
        return place_order(user=user, name="Ali Khan", phone="03001234567", address="House 1, Street 2, Lahore",
                           instructions="", idempotency_key=key or uuid.uuid4())[0]


@override_settings(**FEES)
class CartTests(OrderBase):
    def test_add_clamps_to_stock(self):
        cart_add(self.c1, self.tea.pk, 10)
        self.assertEqual(Cart.objects.get(user=self.c1).items.get().quantity, 3)

    def test_unavailable_products_rejected(self):
        for p in (self.offline,):
            with self.assertRaises(OrderError):
                cart_add(self.c1, p.pk, 1)
        self.rice.is_archived = True; self.rice.save()
        with self.assertRaises(OrderError):
            cart_add(self.c1, self.rice.pk, 1)
        empty = self.make("Empty", "E", 1, 1, 0)
        with self.assertRaises(OrderError):
            cart_add(self.c1, empty.pk, 1)

    def test_set_quantity_and_remove_and_ownership(self):
        item = cart_add(self.c1, self.rice.pk, 2)
        cart_set(self.c1, item.pk, 5)
        item.refresh_from_db(); self.assertEqual(item.quantity, 5)
        with self.assertRaises(OrderError):
            cart_set(self.c2, item.pk, 1)               # someone else's cart line
        cart_set(self.c1, item.pk, 0)
        self.assertEqual(Cart.objects.get(user=self.c1).items.count(), 0)

    def test_totals_and_free_delivery(self):
        cart_add(self.c1, self.rice.pk, 2)
        items = list(Cart.objects.get(user=self.c1).items.select_related("product"))
        t = cart_totals(items)
        self.assertEqual((t["goods"], t["delivery_fee"], t["total"]), (Decimal("200.00"), Decimal("150.00"), Decimal("350.00")))
        cart_add(self.c1, self.big.pk, 1)
        items = list(Cart.objects.get(user=self.c1).items.select_related("product"))
        self.assertEqual(cart_totals(items)["delivery_fee"], Decimal("0.00"))


@override_settings(**FEES)
class PlaceOrderTests(OrderBase):
    def test_places_order_reserves_stock_and_snapshots(self):
        o = self.order(lines=((self.rice, 2), (self.tea, 1)))
        self.assertEqual((self.stock(self.rice), self.stock(self.tea)), (8, 2))
        self.assertEqual((o.subtotal, o.discount_total, o.delivery_fee, o.total),
                         (Decimal("400.00"), Decimal("20.00"), Decimal("150.00"), Decimal("530.00")))
        self.assertEqual(o.status, Order.Status.PENDING)
        self.assertEqual(o.items.get(sku="T").sold_price, Decimal("180.00"))
        self.assertEqual(o.items.get(sku="T").unit_cost, Decimal("120.00"))
        self.assertEqual(o.payments.get().status, Payment.Status.PENDING)
        self.assertEqual(o.events.count(), 1)
        self.assertEqual(Cart.objects.get(user=self.c1).items.count(), 0)
        self.assertEqual(StockMovement.objects.filter(reference=o.number, movement_type="online_order").count(), 2)

    def test_prices_frozen_after_later_price_change(self):
        o = self.order(lines=((self.tea, 1),))
        self.tea.selling_price = Decimal("999"); self.tea.save()
        self.assertEqual(o.items.get().unit_price, Decimal("200.00"))

    def test_insufficient_stock_rolls_back_whole_order(self):
        cart_add(self.c1, self.rice.pk, 2); cart_add(self.c1, self.tea.pk, 3)
        change_stock(self.tea, -2, StockMovement.Type.SALE)          # someone bought tea in the shop meanwhile
        with self.assertRaises(InsufficientStock):
            place_order(user=self.c1, name="A", phone="03001234567", address="Some long address", instructions="",
                        idempotency_key=uuid.uuid4())
        self.assertEqual((self.stock(self.rice), self.stock(self.tea)), (10, 1))
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(Cart.objects.get(user=self.c1).items.count(), 2)

    def test_duplicate_submission_returns_same_order(self):
        key = uuid.uuid4()
        cart_add(self.c1, self.rice.pk, 2)
        kw = dict(user=self.c1, name="A", phone="03001234567", address="Some long address", instructions="", idempotency_key=key)
        a, created_a = place_order(**kw)
        b, created_b = place_order(**kw)                       # cart is empty now, key already used
        self.assertEqual((a.pk, created_a, created_b), (b.pk, True, False))
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(self.stock(self.rice), 8)

    def test_idempotency_key_of_another_customer_rejected(self):
        key = uuid.uuid4()
        self.order(key=key)
        cart_add(self.c2, self.rice.pk, 1)
        with self.assertRaises(OrderError):
            place_order(user=self.c2, name="S", phone="03007654321", address="Some long address", instructions="", idempotency_key=key)
        self.assertEqual(self.stock(self.rice), 9)

    def test_empty_cart_rejected(self):
        with self.assertRaises(OrderError):
            place_order(user=self.c1, name="A", phone="03001234567", address="Some long address", instructions="", idempotency_key=uuid.uuid4())

    def test_last_unit_goes_to_first_customer_only(self):
        last = self.make("Last", "L", 50, 20, 1)
        cart_add(self.c1, last.pk, 1); cart_add(self.c2, last.pk, 1)
        place_order(user=self.c1, name="A", phone="03001234567", address="Some long address", instructions="", idempotency_key=uuid.uuid4())
        with self.assertRaises(InsufficientStock):
            place_order(user=self.c2, name="S", phone="03007654321", address="Some long address", instructions="", idempotency_key=uuid.uuid4())
        self.assertEqual(self.stock(last), 0)
        self.assertEqual(Order.objects.count(), 1)

    def test_product_taken_offline_after_adding_to_cart(self):
        cart_add(self.c1, self.rice.pk, 1)
        self.rice.is_online = False; self.rice.save()
        with self.assertRaises(OrderError):
            place_order(user=self.c1, name="A", phone="03001234567", address="Some long address", instructions="", idempotency_key=uuid.uuid4())
        self.assertEqual(self.stock(self.rice), 10)


@override_settings(**FEES)
class StatusTests(OrderBase):
    def go(self, o, status, **kw):
        return update_order_status(order_id=o.pk, new_status=status, user=kw.pop("user", self.staff), **kw)

    def test_full_lifecycle_and_cod_payment(self):
        o = self.order()
        for st in ("confirmed", "processing", "out_for_delivery"):
            self.go(o, st)
        o = self.go(o, "delivered")
        self.assertIsNotNone(o.delivered_at)
        self.assertEqual(o.payments.get().status, Payment.Status.PAID)
        self.assertEqual(o.events.count(), 5)

    def test_invalid_transitions_blocked(self):
        o = self.order()
        for bad in ("delivered", "processing", "bogus", ""):
            with self.assertRaises(OrderError):
                self.go(o, bad)
        o = self.go(o, "cancelled", note="Customer called")
        for st in ("confirmed", "cancelled"):
            with self.assertRaises(OrderError):
                self.go(o, st, note="x")

    def test_delivered_cannot_be_cancelled(self):
        o = self.order()
        for st in ("confirmed", "processing", "out_for_delivery", "delivered"):
            self.go(o, st)
        with self.assertRaises(OrderError):
            self.go(o, "cancelled", note="x")

    def test_cancel_restocks_once_and_cancels_payment(self):
        o = self.order(lines=((self.rice, 3),))
        self.assertEqual(self.stock(self.rice), 7)
        with self.assertRaises(OrderError):
            self.go(o, "cancelled")                                  # staff must give a reason
        self.assertEqual(self.stock(self.rice), 7)
        self.go(o, "cancelled", note="Out of area")
        self.assertEqual(self.stock(self.rice), 10)
        self.assertEqual(o.payments.get().status, Payment.Status.CANCELLED)
        with self.assertRaises(OrderError):
            self.go(o, "cancelled", note="again")
        self.assertEqual(self.stock(self.rice), 10)

    def test_customer_cancellation_rules(self):
        o = self.order()
        with self.assertRaises(OrderError):
            self.go(o, "cancelled", user=self.c2, by_customer=True)  # not their order
        o = self.go(o, "confirmed")
        o = self.go(o, "cancelled", user=self.c1, by_customer=True)
        self.assertEqual((o.status, o.cancel_reason), ("cancelled", "Cancelled by customer"))
        o2 = self.order()
        self.go(o2, "confirmed"); self.go(o2, "processing")
        with self.assertRaises(OrderError):
            self.go(o2, "cancelled", user=self.c1, by_customer=True)
        with self.assertRaises(OrderError):
            self.go(o2, "delivered", user=self.c1, by_customer=True)   # customers can only cancel


class FakeGateway(PaymentGateway):
    code = "fake"
    online = True


@override_settings(**FEES)
class PaymentTests(OrderBase):
    def setUp(self):
        super().setUp()
        GATEWAYS["fake"] = FakeGateway()
        self.order_obj = self.order()
        self.pay = Payment.objects.create(order=self.order_obj, method="fake", amount=self.order_obj.total)

    def tearDown(self):
        GATEWAYS.pop("fake", None)

    def test_unverified_payment_never_marked_paid(self):
        with self.assertRaises(PaymentError):
            record_verified_payment(self.pay, VerificationResult(verified=False, reference="x"))
        self.pay.refresh_from_db()
        self.assertEqual(self.pay.status, Payment.Status.PENDING)

    def test_amount_mismatch_rejected(self):
        with self.assertRaises(PaymentError):
            record_verified_payment(self.pay, VerificationResult(True, "ref", Decimal("1.00")))

    def test_verified_payment_marks_paid(self):
        record_verified_payment(self.pay, VerificationResult(True, "ref-1", self.pay.amount))
        self.pay.refresh_from_db()
        self.assertEqual((self.pay.status, self.pay.provider_reference), (Payment.Status.PAID, "ref-1"))

    def test_cod_cannot_be_marked_via_verification(self):
        cod = self.order_obj.payments.get(method="cod")
        with self.assertRaises(PaymentError):
            record_verified_payment(cod, VerificationResult(True, "ref", cod.amount))


@override_settings(**FEES)
class FinanceIntegrationTests(OrderBase):
    def test_online_revenue_counts_only_when_delivered(self):
        today = timezone.localdate()
        o = self.order(lines=((self.rice, 2),))                       # total 200 + 150 fee = 350
        self.assertEqual(summary(today, today).online_revenue, Decimal("0.00"))
        for st in ("confirmed", "processing", "out_for_delivery", "delivered"):
            update_order_status(order_id=o.pk, new_status=st, user=self.staff)
        s = summary(today, today)
        self.assertEqual((s.online_revenue, s.online_cogs, s.online_count), (Decimal("350.00"), Decimal("120.00"), 1))
        self.assertEqual((s.revenue, s.gross_profit), (Decimal("350.00"), Decimal("230.00")))

    def test_cancelled_order_is_not_revenue(self):
        today = timezone.localdate()
        o = self.order()
        update_order_status(order_id=o.pk, new_status="cancelled", user=self.staff, note="x")
        self.assertEqual(summary(today, today).revenue, Decimal("0.00"))
