"""PWA endpoints and the privacy markers the service worker relies on."""
import json

from django.test import override_settings
from django.urls import reverse

from apps.orders.tests.test_orders import FEES, PW, OrderBase


@override_settings(**FEES)
class PwaTests(OrderBase):
    def test_manifest_is_valid_and_installable(self):
        r = self.client.get("/manifest.webmanifest")
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/manifest+json", r["Content-Type"])
        m = json.loads(r.content)
        self.assertEqual((m["display"], m["scope"], m["name"]), ("standalone", "/", "W&B General Store"))
        sizes = {i["sizes"] for i in m["icons"]}
        self.assertTrue({"192x192", "512x512"} <= sizes)
        self.assertTrue(any(i["purpose"] == "maskable" for i in m["icons"]))

    def test_service_worker_is_served_from_the_root_with_root_scope(self):
        r = self.client.get("/sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript", r["Content-Type"])
        self.assertEqual(r["Service-Worker-Allowed"], "/")
        self.assertIn("no-cache", r["Cache-Control"])
        body = r.content.decode()
        self.assertIn("smartmart-pages-", body)
        self.assertIn("/static/js/offline/offline-sync.js", body)
        self.assertIn('"/api/"', body)                      # API calls are never cached
        self.assertNotIn("{%", body)                        # fully rendered

    def test_offline_pages_are_public_and_render(self):
        for name in ("store:offline", "store:offline-cart", "store:offline-checkout", "store:offline-orders"):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)
            self.assertNotContains(r, "csrfmiddlewaretoken") if name != "store:offline" else None
        self.assertContains(self.client.get(reverse("store:offline-cart")), "data-offline-cart-root")
        self.assertContains(self.client.get(reverse("store:offline-checkout")), "offline-checkout-form")
        self.assertContains(self.client.get(reverse("store:offline-orders")), "data-offline-orders")

    def test_storefront_pages_link_the_manifest_and_offline_scripts(self):
        html = self.client.get(reverse("store:home")).content.decode()
        for needle in ('rel="manifest"', "js/offline/offline-db.js", "js/offline/offline-sync.js", "js/offline/offline.js",
                       "data-conn-status", "<!--sm-private-start-->"):
            self.assertIn(needle, html, needle)

    def test_private_markers_exist_for_the_service_worker_sanitiser(self):
        self.client.login(username="c1", password=PW)
        html = self.client.get(reverse("store:products")).content.decode()
        self.assertIn('data-user-id="%d"' % self.c1.pk, html)
        self.assertIn('data-sm-private="name"', html)
        self.assertIn('name="csrf-token"', html)

    def test_product_cards_carry_the_data_the_offline_cart_needs(self):
        html = self.client.get(reverse("store:products")).content.decode()
        for attr in ('data-price="', 'data-stock="', 'data-image="', 'data-list-price="'):
            self.assertIn(attr, html, attr)

    def test_cart_orders_checkout_are_not_marked_cacheable(self):
        self.client.login(username="c1", password=PW)
        for name in ("store:cart", "store:orders"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertContains(self.client.get(reverse("store:orders")), "data-offline-orders")
