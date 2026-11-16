"""python manage.py seed_demo [--password PW]

Creates clearly marked SAMPLE data for trying the system: SKUs start with DEMO-, names end with "(Sample)",
and the demo accounts are called demo_owner / demo_cashier / demo_customer. Never run this on a live store.
"""
import secrets
import uuid
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import User
from apps.orders.services import cart_add, place_order
from apps.products.models import Category, Product
from apps.purchases.models import Purchase, PurchaseItem
from apps.purchases.services import receive_purchase
from apps.sales.services import create_sale
from apps.suppliers.models import Supplier

# name, category, price, cost, quantity, discount %, low-stock alert
PRODUCTS = [
    ("Basmati Rice 5kg", "Grains", 1450, 1200, 40, 0, 8), ("Wheat Flour 10kg", "Grains", 1300, 1100, 30, 0, 6),
    ("Cooking Oil 1L", "Pantry", 520, 440, 60, 5, 12), ("Sugar 1kg", "Pantry", 160, 135, 80, 0, 15),
    ("Black Tea 475g", "Beverages", 780, 640, 25, 10, 5), ("Mineral Water 1.5L", "Beverages", 90, 60, 120, 0, 24),
    ("Milk Pack 1L", "Dairy", 290, 250, 50, 0, 10), ("Eggs (Dozen)", "Dairy", 380, 320, 20, 0, 5),
    ("Laundry Detergent 1kg", "Household", 640, 520, 18, 0, 4), ("Dish Soap 500ml", "Household", 260, 190, 3, 0, 5),
    ("Biscuits Family Pack", "Snacks", 150, 110, 70, 0, 12), ("Imported Chocolate Bar", "Snacks", 450, 350, 0, 0, 5),
]


class Command(BaseCommand):
    help = "Create clearly marked sample data (never run on a live store)."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Password for the demo accounts (random if omitted).")

    @transaction.atomic
    def handle(self, *args, **opts):
        if Product.objects.filter(sku__startswith="DEMO-").exists():
            self.stdout.write("Sample data already present; nothing to do.")
            return
        password = opts.get("password") or secrets.token_urlsafe(12)
        owner = self._user("demo_owner", "owner", "Demo", "Owner", password)
        cashier = self._user("demo_cashier", "staff", "Demo", "Cashier", password)
        customer = self._user("demo_customer", "customer", "Demo", "Customer", password, phone="03001234567")

        cats = {n: Category.objects.get_or_create(name=n)[0] for n in {p[1] for p in PRODUCTS}}
        products = []
        for i, (name, cat, price, cost, qty, disc, low) in enumerate(PRODUCTS, start=1):
            products.append((Product.objects.create(
                name=f"{name} (Sample)", category=cats[cat], sku=f"DEMO-{i:03d}", selling_price=Decimal(price),
                discount_percent=Decimal(disc), low_stock_threshold=low,
                description="SAMPLE DATA: delete before using the store for real."), cost, qty))

        supplier = Supplier.objects.create(name="Sample Supplier (Demo)", notes="SAMPLE DATA")
        purchase = Purchase.objects.create(supplier=supplier, invoice_reference="DEMO-INV-1", created_by=owner)
        PurchaseItem.objects.bulk_create([PurchaseItem(purchase=purchase, product=p, quantity=q, unit_cost=Decimal(c))
                                          for p, c, q in products if q > 0])
        receive_purchase(purchase.pk, owner)

        by_sku = {p.sku: p for p, _, _ in products}
        create_sale(user=cashier, items=[(by_sku["DEMO-001"].pk, 2), (by_sku["DEMO-003"].pk, 3)], payment_method="cash")
        create_sale(user=cashier, items=[(by_sku["DEMO-006"].pk, 12), (by_sku["DEMO-011"].pk, 4)], payment_method="card")
        cart_add(customer, by_sku["DEMO-007"].pk, 4)
        cart_add(customer, by_sku["DEMO-005"].pk, 1)
        place_order(user=customer, name="Demo Customer", phone="03001234567", address="Sample address, Sample Town",
                    instructions="SAMPLE ORDER", idempotency_key=uuid.uuid4())

        self.stdout.write(self.style.SUCCESS("Sample data created (SKUs start with DEMO-)."))
        self.stdout.write(f"Demo accounts: demo_owner, demo_cashier, demo_customer. Password: {password}")
        self.stdout.write("Shown once, so save it now.")

    def _user(self, username, role, first, last, password, phone=""):
        return User.objects.create_user(username=username, password=password, role=role, first_name=first,
                                        last_name=last, phone=phone)
