import uuid
from decimal import Decimal
from types import SimpleNamespace

from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.customers.models import CustomerProfile
from apps.orders.models import Cart, CartItem, Order
from apps.orders.services import OrderError, cart_add, place_order
from apps.orders.tests.test_orders import FEES, PW, OrderBase
from apps.store.templatetags.store_extras import (
    best_seller_product_art,
    featured_product_art,
    product_art,
    product_art_url,
)


def checkout_data(key=None, **kw):
    d = {"customer_name": "Ali Khan", "phone": "03001234567", "address": "House 1, Street 2, Lahore",
         "delivery_instructions": "Ring the bell", "idempotency_key": str(key or uuid.uuid4())}
    d.update(kw)
    return d


@override_settings(**FEES)
class StorefrontTests(OrderBase):
    def test_public_pages_render(self):
        for name in ("store:home", "store:products", "store:search", "store:help", "store:contact"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        home = self.client.get(reverse("store:home"))
        self.assertContains(home, "/media/catalog/products/organic-rice.webp")
        self.assertContains(home, "/media/catalog/products/cooking-oil.webp")
        self.assertContains(self.client.get(reverse("store:contact")), "contact-shopping-cart.webp")
        self.assertEqual(self.client.get(reverse("store:product", args=[self.rice.pk])).status_code, 200)

    def test_home_hero_renders_all_uploaded_banners_and_controls(self):
        response = self.client.get(reverse("store:home"))
        html = response.content.decode()

        self.assertContains(response, 'data-hero-slides')
        self.assertEqual(html.count('class="sm-banner-slide'), 4)
        self.assertContains(response, "W&amp;B General Store_ Shop Local, Live Better.png")
        self.assertContains(response, "W&amp;B General Store_ Shop Smart, Live Better.png")
        self.assertContains(response, "W&amp;B General Store Promotional Banner (1).png")
        self.assertContains(response, "W&amp;B General Store Promotional Banner.png")
        self.assertEqual(html.count('data-hero-dot='), 4)
        self.assertContains(response, 'aria-label="Previous slide"')
        self.assertContains(response, 'aria-label="Next slide"')
        hero = html.partition('<section class="sm-home-hero')[2].partition("</section>")[0]
        self.assertNotIn("<form", hero)

    def test_tomato_paste_and_haldi_use_matching_product_art(self):
        tomato_paste = SimpleNamespace(name="Tomato Paste 400g", category_id=None)
        haldi = SimpleNamespace(name="Haldi", category_id=None)

        self.assertEqual(product_art_url(tomato_paste), "/media/catalog/products/tomato-sauce.webp")
        self.assertEqual(product_art_url(haldi), "/media/catalog/products/turmeric.webp")

    def test_milk_uses_uploaded_art_across_product_cards(self):
        milk = SimpleNamespace(name="Milk", category_id=None)
        milk_powder = SimpleNamespace(name="Milk Powder 500g", category_id=None)
        milk_image = "/media/catalog/products/milk-carton.webp"

        self.assertEqual(product_art(milk), "catalog/products/milk-carton.webp")
        self.assertEqual(product_art_url(milk), milk_image)
        self.assertEqual(featured_product_art(milk), milk_image)
        self.assertEqual(best_seller_product_art(milk), milk_image)
        self.assertEqual(product_art_url(milk_powder), "/media/catalog/products/milk-powder.webp")

    def test_product_artwork_files_are_in_media(self):
        from django.conf import settings
        from apps.store.templatetags.store_extras import PRODUCT_PHOTO_ART

        product_art_dir = settings.MEDIA_ROOT / "catalog" / "products"
        self.assertTrue(product_art_dir.is_dir())
        self.assertTrue(all((product_art_dir / filename).is_file() for filename in set(PRODUCT_PHOTO_ART.values())))

    def test_home_shop_and_categories_navigation(self):
        home = self.client.get(reverse("store:home"))
        self.assertTemplateUsed(home, "store/home.html")
        self.assertContains(home, 'id="categories"')

        shop = self.client.get(reverse("store:products"))
        self.assertTemplateUsed(shop, "store/product_list.html")

        categories = self.client.get(reverse("store:categories"))
        self.assertRedirects(categories, "/#categories")
        categories_page = self.client.get(categories["Location"], follow=True)
        self.assertTemplateUsed(categories_page, "store/home.html")
        self.assertContains(categories_page, 'id="categories"')

    def test_home_categories_feature_cooking_oil_instead_of_fruits(self):
        from apps.products.models import Category

        fruits = Category.objects.create(name="Fruits & Vegetables")
        oil = self.make("Cooking Oil 1L", "OIL", 620, 510, 12)
        oil.category = fruits
        oil.save()

        home = self.client.get(reverse("store:home"))

        self.assertEqual(home.context["spotlight_product"], oil)
        self.assertContains(home, f'href="{reverse("store:product", args=[oil.pk])}"')
        self.assertContains(home, "Cooking Oil 1L")
        self.assertContains(home, "Rs. 620.00")
        self.assertNotContains(home, 'aria-label="Browse Fruits &amp; Vegetables')

    def test_home_featured_products_replace_fruit_cards_three_and_four(self):
        tea = self.make("Black Tea 450g", "BLACK-TEA-450", 780, 620, 14)
        turmeric = self.make("Turmeric Powder 100g", "TURMERIC-100", 110, 70, 24)
        milk = self.make("Milk", "FEATURED-MILK", 180, 120, 25, discount=11)
        pasta = self.make("Pasta 400g", "FEATURED-PASTA", 190, 130, 24)
        self.make("Pantry Rice", "PANTRY-RICE", 300, 240, 12)

        home = self.client.get(reverse("store:home"))
        featured = home.context["featured"]

        self.assertEqual(len(featured), 6)
        self.assertEqual(featured[2], tea)
        self.assertEqual(featured[3], turmeric)
        self.assertEqual(featured[4], milk)
        self.assertEqual(featured[5], pasta)
        self.assertEqual(len({product.pk for product in featured}), 6)
        self.assertContains(home, "Black Tea 450g")
        self.assertContains(home, "Turmeric Powder 100g")
        self.assertContains(home, "Milk")
        self.assertContains(home, "Pasta 400g")
        self.assertContains(home, "/media/catalog/products/black-tea.webp")
        self.assertContains(home, "/media/catalog/products/milk-carton.webp")

    def test_inactive_produce_category_is_hidden_from_customer_storefront(self):
        from apps.products.models import Category

        fruits = Category.objects.create(name="Fruits & Vegetables", is_active=False)
        orange = self.make("Storefront Orange", "STORE-ORANGE", 180, 90, 8)
        orange.category = fruits
        orange.save()

        home = self.client.get(reverse("store:home"))
        shop = self.client.get(reverse("store:products"))
        search = self.client.get(reverse("store:search"), {"q": "Storefront Orange"})
        categories = self.client.get(reverse("store:categories"))

        self.assertNotContains(home, "Storefront Orange")
        self.assertNotContains(shop, "Storefront Orange")
        self.assertEqual(search.context["page_obj"].paginator.count, 0)
        self.assertNotContains(categories, "Fruits &amp; Vegetables")
        self.assertEqual(
            self.client.get(reverse("store:product", args=[orange.pk])).status_code,
            404,
        )

    def test_inactive_category_cart_item_is_unavailable_and_cannot_be_ordered(self):
        from apps.products.models import Category

        fruits = Category.objects.create(name="Fruits & Vegetables", is_active=False)
        orange = self.make("Storefront Orange", "CART-ORANGE", 180, 90, 8)
        orange.category = fruits
        orange.save()
        cart = Cart.objects.create(user=self.c1)
        CartItem.objects.create(cart=cart, product=orange, quantity=1)
        self.client.force_login(self.c1)

        cart_response = self.client.get(reverse("store:cart"))
        self.assertContains(cart_response, "Currently unavailable")
        self.assertContains(cart_response, "Review item quantities")
        self.assertRedirects(self.client.get(reverse("store:checkout")), reverse("store:cart"))
        with self.assertRaises(OrderError):
            place_order(
                user=self.c1,
                name="Ali Khan",
                phone="03001234567",
                address="House 1, Lahore",
                instructions="",
                idempotency_key=uuid.uuid4(),
            )
        self.assertFalse(Order.objects.filter(customer=self.c1).exists())

    def test_listing_hides_offline_and_archived_products(self):
        self.tea.is_archived = True; self.tea.save()
        r = self.client.get(reverse("store:products"))
        self.assertContains(r, "Rice")
        self.assertNotContains(r, "Offline")
        self.assertNotContains(r, ">Tea<")
        self.assertEqual(self.client.get(reverse("store:product", args=[self.offline.pk])).status_code, 404)

    def test_search_sort_and_filters(self):
        r = self.client.get(reverse("store:search"), {"q": "rice"})
        self.assertContains(r, "Rice"); self.assertNotContains(r, "Generator")
        for sort in ("price_asc", "price_desc", "popular", "name", "bogus"):
            self.assertEqual(self.client.get(reverse("store:products"), {"sort": sort}).status_code, 200, sort)
        names = [p.name for p in self.client.get(reverse("store:products"), {"sort": "price_desc"}).context["products"]]
        self.assertEqual(names[0], "Generator")

    def test_availability_and_discount_labels(self):
        empty = self.make("Empty", "E", 10, 5, 0)
        r = self.client.get(reverse("store:product", args=[empty.pk]))
        self.assertContains(r, "Out of stock")
        r = self.client.get(reverse("store:product", args=[self.tea.pk]))
        self.assertContains(r, "-10%")

    def test_category_page(self):
        from apps.products.models import Category
        cat = Category.objects.create(name="Drinks")
        self.tea.category = cat; self.tea.save()
        r = self.client.get(reverse("store:category", args=[cat.slug]))
        self.assertContains(r, "Tea"); self.assertNotContains(r, "Rice")
        self.assertEqual(self.client.get(reverse("store:category", args=["nope"])).status_code, 404)

    def test_cart_requires_customer_login(self):
        r = self.client.get(reverse("store:cart"))
        self.assertEqual(r.status_code, 302); self.assertIn(reverse("accounts:login"), r["Location"])
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("store:cart")).status_code, 403)
        self.assertEqual(self.client.post(reverse("store:cart-add"), {"product_id": self.rice.pk}).status_code, 403)

    def test_add_to_cart_and_update(self):
        self.client.force_login(self.c1)
        self.client.post(reverse("store:cart-add"), {"product_id": self.rice.pk, "quantity": "2"})
        item = Cart.objects.get(user=self.c1).items.get()
        self.assertEqual(item.quantity, 2)
        self.assertContains(self.client.get(reverse("store:cart")), "Rice")
        self.client.post(reverse("store:cart-update"), {"item_id": item.pk, "quantity": "0"})
        self.assertEqual(Cart.objects.get(user=self.c1).items.count(), 0)

    def test_cart_add_ignores_external_redirect(self):
        self.client.force_login(self.c1)
        r = self.client.post(reverse("store:cart-add"), {"product_id": self.rice.pk, "next": "//evil.example"})
        self.assertRedirects(r, reverse("store:cart"))

    def test_cart_update_rejects_other_customers_line(self):
        item = cart_add(self.c1, self.rice.pk, 2)
        self.client.force_login(self.c2)
        self.client.post(reverse("store:cart-update"), {"item_id": item.pk, "quantity": "0"})
        item.refresh_from_db()
        self.assertEqual(item.quantity, 2)

    def test_checkout_places_order_and_double_post_makes_one(self):
        cart_add(self.c1, self.rice.pk, 2)
        self.client.force_login(self.c1)
        self.assertEqual(self.client.get(reverse("store:checkout")).status_code, 200)
        key = uuid.uuid4()
        r1 = self.client.post(reverse("store:checkout"), checkout_data(key))
        order = Order.objects.get()
        self.assertRedirects(r1, reverse("store:order-detail", args=[order.pk]))
        r2 = self.client.post(reverse("store:checkout"), checkout_data(key))
        self.assertRedirects(r2, reverse("store:order-detail", args=[order.pk]))
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(self.stock(self.rice), 8)
        self.assertContains(self.client.get(reverse("store:order-detail", args=[order.pk])), order.number)

    def test_checkout_validation(self):
        cart_add(self.c1, self.rice.pk, 1)
        self.client.force_login(self.c1)
        for bad in ({"phone": "abc"}, {"phone": "123"}, {"address": "x"}, {"customer_name": "  "}):
            r = self.client.post(reverse("store:checkout"), checkout_data(**bad))
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(self.stock(self.rice), 10)

    def test_checkout_with_empty_cart_redirects(self):
        self.client.force_login(self.c1)
        self.assertRedirects(self.client.get(reverse("store:checkout")), reverse("store:cart"))

    def test_checkout_stock_conflict_shows_error(self):
        cart_add(self.c1, self.tea.pk, 3)
        from apps.inventory.models import StockMovement
        from apps.inventory.services import change_stock
        change_stock(self.tea, -2, StockMovement.Type.SALE)
        self.client.force_login(self.c1)
        r = self.client.post(reverse("store:checkout"), checkout_data())
        self.assertEqual(r.status_code, 409)
        self.assertContains(r, "in stock", status_code=409)
        self.assertEqual(Order.objects.count(), 0)

    def test_customers_cannot_see_or_cancel_each_others_orders(self):
        o = self.order(user=self.c1)
        self.client.force_login(self.c2)
        self.assertEqual(self.client.get(reverse("store:order-detail", args=[o.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("store:order-cancel", args=[o.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("store:orders")), o.number)
        o.refresh_from_db()
        self.assertEqual(o.status, "pending")

    def test_anonymous_cannot_see_orders(self):
        o = self.order(user=self.c1)
        self.assertEqual(self.client.get(reverse("store:order-detail", args=[o.pk])).status_code, 302)

    def test_customer_cancel_via_view_restocks(self):
        o = self.order(user=self.c1, lines=((self.rice, 3),))
        self.client.force_login(self.c1)
        self.client.post(reverse("store:order-cancel", args=[o.pk]))
        o.refresh_from_db()
        self.assertEqual(o.status, "cancelled")
        self.assertEqual(self.stock(self.rice), 10)

    def test_profile_update(self):
        self.client.force_login(self.c1)
        self.assertEqual(self.client.get(reverse("store:profile")).status_code, 200)
        self.client.post(reverse("store:profile"), {"first_name": "Ali", "last_name": "K", "email": "a@example.com",
                                                    "phone": "03111111111", "default_address": "New address 123"})
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.phone, "03111111111")
        self.assertEqual(CustomerProfile.objects.get(user=self.c1).default_address, "New address 123")
        r = self.client.post(reverse("store:profile"), {"first_name": "Ali", "phone": "bad"})
        self.assertEqual(r.status_code, 400)

    def test_cannot_change_role_through_profile(self):
        self.client.force_login(self.c1)
        self.client.post(reverse("store:profile"), {"first_name": "Ali", "phone": "03001234567", "role": "owner"})
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.role, "customer")


@override_settings(**FEES)
class OrderManagementViewTests(OrderBase):
    def test_staff_can_manage_orders_customers_cannot(self):
        o = self.order()
        self.client.force_login(self.c1)
        self.assertEqual(self.client.get(reverse("orders:list")).status_code, 403)
        self.assertEqual(self.client.post(reverse("orders:status", args=[o.pk]), {"status": "confirmed"}).status_code, 403)
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("orders:list"), {"q": o.number}), o.number)
        self.assertEqual(self.client.get(reverse("orders:detail", args=[o.pk])).status_code, 200)
        self.client.post(reverse("orders:status", args=[o.pk]), {"status": "confirmed"})
        o.refresh_from_db(); self.assertEqual(o.status, "confirmed")

    def test_cancel_needs_reason_and_bad_status_is_safe(self):
        o = self.order(lines=((self.rice, 2),))
        self.client.force_login(self.staff)
        self.client.post(reverse("orders:status", args=[o.pk]), {"status": "cancelled", "note": ""})
        self.client.post(reverse("orders:status", args=[o.pk]), {"status": "nonsense"})
        o.refresh_from_db()
        self.assertEqual(o.status, "pending")
        self.assertEqual(self.stock(self.rice), 8)
        self.client.post(reverse("orders:status", args=[o.pk]), {"status": "cancelled", "note": "Unreachable"})
        self.assertEqual(self.stock(self.rice), 10)

    def test_dashboard_shows_online_orders_and_channel_report(self):
        o = self.order()
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("dashboard:home")), o.number)
        self.assertEqual(self.client.get(reverse("reports:report", args=["channels"])).status_code, 200)
