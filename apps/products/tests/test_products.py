from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from apps.core.models import AuditLog
from apps.inventory.models import StockMovement
from apps.products.forms import ProductForm
from apps.products.models import Product

PW = "S3cure-pass-987"


def base_data(**kw):
    d = {"name": "Tea 250g", "description": "", "category": "", "sku": "tea250", "barcode": "",
         "cost_price": "80.00", "selling_price": "120.00", "discount_percent": "0",
         "low_stock_threshold": "5", "is_online": "on", "opening_stock": "5"}
    d.update(kw)
    return d


class ProductTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password=PW, role="owner")
        self.staff = User.objects.create_user("cash", password=PW, role="staff")
        self.cust = User.objects.create_user("cust", password=PW, role="customer")

    def test_discounted_price(self):
        p = Product(selling_price=Decimal("100.00"), discount_percent=Decimal("10"))
        self.assertEqual(p.discounted_price, Decimal("90.00"))

    def test_invalid_prices_and_discount_rejected(self):
        for bad in ({"selling_price": "-1"}, {"selling_price": "0"}, {"discount_percent": "101"}, {"cost_price": "-5"}):
            data = {k: v for k, v in base_data(**bad).items() if k != "opening_stock"}
            self.assertFalse(ProductForm(data).is_valid(), bad)

    def test_owner_creates_product_with_opening_stock(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse("products:create"), base_data())
        p = Product.objects.get(sku="TEA250")
        self.assertRedirects(r, reverse("products:detail", args=[p.pk]))
        self.assertEqual(p.stock_quantity, 5)
        self.assertEqual(StockMovement.objects.get(product=p).movement_type, StockMovement.Type.OPENING)

    def test_product_image_upload_is_saved_under_media_root(self):
        image_data = BytesIO()
        Image.new("RGB", (1, 1), color="green").save(image_data, format="PNG")

        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                self.client.force_login(self.owner)
                response = self.client.post(
                    reverse("products:create"),
                    {**base_data(), "image": SimpleUploadedFile("tea.png", image_data.getvalue(), "image/png")},
                )

                product = Product.objects.get(sku="TEA250")
                self.assertRedirects(response, reverse("products:detail", args=[product.pk]))
                self.assertEqual(product.image.name, "products/tea.png")
                self.assertEqual(product.image.url, "/media/products/tea.png")
                self.assertTrue((Path(media_root) / product.image.name).is_file())

    def test_blank_barcodes_do_not_collide(self):
        first = Product.objects.create(name="A", sku="A", selling_price=1, barcode="")
        second = Product.objects.create(name="B", sku="B", selling_price=1, barcode="")
        self.assertEqual(Product.objects.count(), 2)
        self.assertTrue(first.barcode.startswith("SM"))
        self.assertTrue(second.barcode.startswith("SM"))
        self.assertNotEqual(first.barcode, second.barcode)
        self.assertTrue(first.product_code.startswith("LOCAL-"))

    def test_manufacturer_barcode_is_preserved_exactly(self):
        p = Product.objects.create(name="A", sku="A", selling_price=1, barcode="0001234567890")
        self.assertEqual(p.barcode, "0001234567890")
        self.assertTrue(p.has_manufacturer_barcode)

    def test_duplicate_sku_rejected(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("products:create"), base_data())
        r = self.client.post(reverse("products:create"), base_data(name="Other"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Product.objects.count(), 1)

    def test_staff_can_view_but_not_change(self):
        p = Product.objects.create(name="A", sku="A", selling_price=10)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("products:list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("products:detail", args=[p.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse("products:create"), base_data()).status_code, 403)
        self.assertEqual(self.client.post(reverse("products:edit", args=[p.pk]), base_data()).status_code, 403)
        self.assertEqual(self.client.post(reverse("products:archive", args=[p.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("products:adjust", args=[p.pk]), {"quantity_change": 5, "reason": "x"}).status_code, 403)

    def test_customer_has_no_access(self):
        self.client.force_login(self.cust)
        self.assertEqual(self.client.get(reverse("products:list")).status_code, 403)

    def test_price_change_is_audited(self):
        p = Product.objects.create(name="A", sku="A", selling_price=Decimal("10.00"))
        self.client.force_login(self.owner)
        self.client.post(reverse("products:edit", args=[p.pk]), base_data(name="A", sku="A", selling_price="15.00"))
        p.refresh_from_db()
        self.assertEqual(p.selling_price, Decimal("15.00"))
        self.assertTrue(AuditLog.objects.filter(action="product.price_changed", target="A").exists())

    def test_base_unit_cannot_change_after_stock_history(self):
        p = Product.objects.create(name="A", sku="A", selling_price=10)
        from apps.inventory.services import change_stock
        change_stock(p, 3, StockMovement.Type.OPENING)
        self.assertFalse(ProductForm({**base_data(name="A", sku="A"), "base_unit": Product.Unit.KG}, instance=p).is_valid())

    def test_archive_hides_from_default_list(self):
        p = Product.objects.create(name="Hidden", sku="H", selling_price=10)
        self.client.force_login(self.owner)
        self.client.post(reverse("products:archive", args=[p.pk]))
        self.assertNotContains(self.client.get(reverse("products:list")), "Hidden")
        self.assertContains(self.client.get(reverse("products:list") + "?archived=1"), "Hidden")

    def test_search_by_barcode_and_stock_filters(self):
        Product.objects.create(name="Scanned", sku="S", selling_price=10, barcode="123456")
        Product.objects.create(name="Other", sku="O", selling_price=10)
        self.client.force_login(self.staff)
        r = self.client.get(reverse("products:list") + "?q=123456")
        self.assertContains(r, "Scanned"); self.assertNotContains(r, "Other")
        r = self.client.get(reverse("products:list") + "?stock=out")
        self.assertContains(r, "Scanned")

    def test_adjust_requires_reason_and_blocks_negative(self):
        p = Product.objects.create(name="A", sku="A", selling_price=10)
        self.client.force_login(self.owner)
        url = reverse("products:adjust", args=[p.pk])
        self.client.post(url, {"quantity_change": 5, "reason": ""})
        p.refresh_from_db(); self.assertEqual(p.stock_quantity, 0)
        self.client.post(url, {"quantity_change": 5, "reason": "Stock count"})
        p.refresh_from_db(); self.assertEqual(p.stock_quantity, 5)
        self.client.post(url, {"quantity_change": -9, "reason": "Oops"})
        p.refresh_from_db(); self.assertEqual(p.stock_quantity, 5)

    def test_low_and_out_flags(self):
        p = Product(stock_quantity=0, low_stock_threshold=5)
        self.assertTrue(p.is_out_of_stock); self.assertFalse(p.is_low_stock)
        p.stock_quantity = 3
        self.assertTrue(p.is_low_stock)
        p.stock_quantity = 6
        self.assertFalse(p.is_low_stock)
