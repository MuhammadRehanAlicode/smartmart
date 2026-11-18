from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.inventory.models import StockMovement
from apps.inventory.services import change_stock
from apps.products.models import Product


class InventoryBarcodeLookupTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner-barcode", password="S3cure-pass-987", role="owner")
        self.staff = User.objects.create_user("staff-barcode", password="S3cure-pass-987", role="staff")
        self.customer = User.objects.create_user("customer-barcode", password="S3cure-pass-987", role="customer")
        self.product = Product.objects.create(name="Rice", sku="RICE", selling_price=100, barcode="001234567890")
        change_stock(self.product, 7, StockMovement.Type.OPENING)

    def test_staff_can_lookup_stock_and_owner_adjust_link_is_not_exposed(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("inventory:barcode_lookup_api"), {"barcode": self.product.barcode})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stock"], "7.000000")
        self.assertEqual(response.json()["base_unit"], Product.Unit.PCS)
        self.assertEqual(response.json()["sku"], "RICE")
        self.assertEqual(response.json()["adjust_url"], "")

    def test_owner_gets_existing_stock_adjustment_workflow(self):
        self.client.force_login(self.owner)
        result = self.client.get(reverse("inventory:barcode_lookup_api"), {"barcode": self.product.barcode}).json()
        self.assertEqual(result["adjust_url"], reverse("products:adjust", args=[self.product.pk]))

    def test_missing_barcode_has_clear_not_found_response(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("inventory:barcode_lookup_api"), {"barcode": "NO-SUCH-CODE"})
        self.assertEqual(response.status_code, 404)
        self.assertIn("No active product", response.json()["error"])

    def test_inventory_barcode_page_is_staff_only_and_has_camera_controls(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("inventory:barcode_lookup"))
        self.assertContains(response, "Start camera scanner")
        self.assertContains(response, "inventory-barcode.js")
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse("inventory:barcode_lookup")).status_code, 403)

    def test_barcode_lookup_does_not_change_stock_or_create_movement(self):
        self.client.force_login(self.owner)
        before = StockMovement.objects.filter(product=self.product).count()
        self.client.get(reverse("inventory:barcode_lookup_api"), {"barcode": self.product.barcode})
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 7)
        self.assertEqual(StockMovement.objects.filter(product=self.product).count(), before)
