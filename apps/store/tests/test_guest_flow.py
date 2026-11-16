"""Guest browsing + login-required Add to Cart (acceptance scenarios 1-9)."""
import time

from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.orders.models import Cart, CartItem
from apps.orders.tests.test_orders import FEES, PW, OrderBase
from apps.store.pending import PENDING_KEY

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
REG = {"username": "newbie", "first_name": "Nida", "last_name": "Khan", "email": "n@example.com",
       "phone": "03001112222", "password1": "Fr3sh-Mart-Pass-77", "password2": "Fr3sh-Mart-Pass-77"}


@override_settings(**FEES)
class GuestFlowTests(OrderBase):
    def guest_add(self, product=None, qty=1):
        return self.client.post(reverse("store:cart-add"), {"product_id": (product or self.rice).pk, "quantity": qty}, **AJAX)

    def login_ajax(self, username="c1", password=PW):
        return self.client.post(reverse("accounts:login"), {"username": username, "password": password}, **AJAX)

    def rows(self, user):
        return list(CartItem.objects.filter(cart__user=user))

    # 1 + 2
    def test_homepage_opens_for_guest_and_browsing_works(self):
        r = self.client.get(reverse("store:home"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertContains(r, "Fresh Products")
        self.assertContains(r, "Login to Continue")  # the modal is on the page for guests
        for name in ("store:products", "store:search", "store:help"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("store:products"), {"offers": "1"}).status_code, 200)
        self.assertEqual(self.client.get(reverse("store:products"), {"sort": "price_desc"}).status_code, 200)
        self.assertEqual(self.client.get(reverse("store:product", args=[self.rice.pk])).status_code, 200)

    # 3
    def test_guest_add_to_cart_asks_for_login_and_adds_nothing(self):
        r = self.guest_add()
        self.assertEqual(r.status_code, 401)
        self.assertTrue(r.json()["login_required"])
        self.assertEqual(CartItem.objects.count(), 0)
        self.assertEqual(Cart.objects.count(), 0)
        self.assertEqual(self.client.session[PENDING_KEY]["product_id"], self.rice.pk)

    def test_guest_add_without_javascript_redirects_to_login(self):
        r = self.client.post(reverse("store:cart-add"), {"product_id": self.rice.pk, "next": "/shop/"})
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("accounts:login"), r["Location"])
        self.assertEqual(CartItem.objects.count(), 0)

    # 4
    def test_closing_the_modal_forgets_the_product(self):
        self.guest_add()
        self.assertEqual(self.client.post(reverse("store:pending-clear")).status_code, 204)
        self.assertNotIn(PENDING_KEY, self.client.session)
        self.assertEqual(self.client.get(reverse("store:products")).status_code, 200)
        self.assertTrue(self.login_ajax().json()["ok"])
        self.assertEqual(self.rows(self.c1), [])

    # 5
    def test_login_completes_the_pending_add_exactly_once(self):
        self.guest_add(qty=2)
        r = self.login_ajax()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        items = self.rows(self.c1)
        self.assertEqual([(i.product_id, i.quantity) for i in items], [(self.rice.pk, 2)])
        self.assertNotIn(PENDING_KEY, self.client.session)
        self.client.post(reverse("accounts:logout"))
        self.login_ajax()  # a later login must not add it again
        self.assertEqual(self.rows(self.c1)[0].quantity, 2)

    def test_plain_form_login_also_completes_pending_add(self):
        self.client.post(reverse("store:cart-add"), {"product_id": self.rice.pk})
        r = self.client.post(reverse("accounts:login"), {"username": "c1", "password": PW})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.rows(self.c1)[0].quantity, 1)

    # 6
    def test_registration_completes_the_pending_add_exactly_once(self):
        self.guest_add()
        r = self.client.post(reverse("accounts:register"), REG, **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        user = User.objects.get(username="newbie")
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertEqual([(i.product_id, i.quantity) for i in self.rows(user)], [(self.rice.pk, 1)])
        self.assertEqual(CartItem.objects.count(), 1)

    # errors
    def test_wrong_password_shows_error_and_adds_nothing(self):
        self.guest_add()
        r = self.login_ajax(password="wrong-password-1")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])
        self.assertIn("__all__", r.json()["errors"])
        self.assertEqual(CartItem.objects.count(), 0)
        self.assertIn(PENDING_KEY, self.client.session)  # still waiting for a successful login

    def test_invalid_registration_returns_field_errors_and_creates_nothing(self):
        self.guest_add()
        r = self.client.post(reverse("accounts:register"), {**REG, "phone": "abc", "password2": "different"}, **AJAX)
        self.assertEqual(r.status_code, 400)
        errors = r.json()["errors"]
        self.assertIn("phone", errors)
        self.assertIn("password2", errors)
        self.assertFalse(User.objects.filter(username="newbie").exists())
        self.assertEqual(CartItem.objects.count(), 0)

    def test_staff_login_never_receives_a_pending_cart_item(self):
        self.guest_add()
        r = self.login_ajax("cash")
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["redirect"], reverse("dashboard:home"))
        self.assertEqual(CartItem.objects.count(), 0)

    def test_stale_pending_add_is_ignored(self):
        self.guest_add()
        session = self.client.session
        session[PENDING_KEY]["ts"] = int(time.time()) - 3600
        session.save()
        self.login_ajax()
        self.assertEqual(self.rows(self.c1), [])

    def test_out_of_stock_product_is_not_remembered(self):
        empty = self.make("Empty", "E1", 10, 5, 0)
        self.assertEqual(self.guest_add(empty).status_code, 401)
        self.assertNotIn(PENDING_KEY, self.client.session)

    # 7
    def test_cart_and_login_state_survive_a_refresh(self):
        self.guest_add()
        self.login_ajax()
        for _ in range(2):
            r = self.client.get(reverse("store:home"))
            self.assertEqual(r.status_code, 200)
            self.assertNotContains(r, "Login to Continue")
        self.assertContains(self.client.get(reverse("store:cart")), "Rice")
        self.assertEqual(self.rows(self.c1)[0].quantity, 1)

    def test_logged_in_ajax_add_returns_cart_count(self):
        self.client.force_login(self.c1)
        r = self.guest_add(qty=3)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["cart_count"], 3)
        self.assertEqual(self.guest_add().json()["cart_count"], 4)
        self.assertEqual(len(self.rows(self.c1)), 1)  # one line, never a duplicate entry

    # 8
    def test_protected_cart_apis_reject_anonymous_requests(self):
        item = CartItem.objects.create(cart=Cart.objects.create(user=self.c1), product=self.rice, quantity=1)
        for method, url in (("get", "/api/v1/cart/"), ("post", "/api/v1/cart/"),
                            ("patch", f"/api/v1/cart/items/{item.pk}/"), ("delete", f"/api/v1/cart/items/{item.pk}/"),
                            ("post", "/api/v1/checkout/")):
            r = getattr(self.client, method)(url, {"product_id": self.rice.pk, "quantity": 1}, content_type="application/json")
            self.assertIn(r.status_code, (401, 403), f"{method} {url}")
        self.assertEqual(self.client.get(reverse("store:cart")).status_code, 302)
        self.assertEqual(self.client.get(reverse("store:orders")).status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 1)

    # 9
    def test_another_customer_cannot_see_or_touch_the_first_customers_data(self):
        self.client.force_login(self.c1)
        self.guest_add(qty=2)
        order = self.order(user=self.c1)
        self.client.logout()
        self.assertTrue(self.login_ajax("c2").json()["ok"])
        self.assertEqual(self.client.get("/api/v1/cart/").json()["items"], [])
        self.assertNotContains(self.client.get(reverse("store:cart")), "Rice")
        self.assertNotContains(self.client.get(reverse("store:orders")), order.number)
        self.assertEqual(self.client.get(reverse("store:order-detail", args=[order.pk])).status_code, 404)
        item = self.rows(self.c1)[0]
        self.client.patch(f"/api/v1/cart/items/{item.pk}/", {"quantity": 9}, content_type="application/json")
        self.client.delete(f"/api/v1/cart/items/{item.pk}/")
        item.refresh_from_db()
        self.assertEqual(item.quantity, 2)
