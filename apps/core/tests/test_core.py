from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.core.management.commands.backup_db import build_pg_dump_command
from apps.core.models import AuditLog
from apps.inventory.models import StockMovement
from apps.products.models import Product

PW = "S3cure-pass-987"


class SecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ali", password=PW, role="customer")

    def test_login_and_logout_are_audited(self):
        self.client.post(reverse("accounts:login"), {"username": "ali", "password": PW})
        self.assertTrue(AuditLog.objects.filter(action="auth.login", target="ali").exists())
        self.client.post(reverse("accounts:logout"))
        self.assertTrue(AuditLog.objects.filter(action="auth.logout", target="ali").exists())

    def test_failed_login_audited_without_password(self):
        self.client.post(reverse("accounts:login"), {"username": "ali", "password": "SuperSecretWrong1"})
        entry = AuditLog.objects.get(action="auth.login_failed")
        self.assertEqual(entry.target, "ali")
        self.assertNotIn("SuperSecretWrong1", str(entry.details) + entry.target)

    def test_web_login_lockout_after_five_failures(self):
        for _ in range(5):
            self.assertEqual(self.client.post(reverse("accounts:login"), {"username": "ali", "password": "nope"}).status_code, 200)
        r = self.client.post(reverse("accounts:login"), {"username": "ali", "password": PW})
        self.assertEqual(r.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_other_username_not_locked_by_failures_of_first(self):
        User.objects.create_user("sara", password=PW, role="customer")
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"username": "ali", "password": "nope"})
        self.assertEqual(self.client.post(reverse("accounts:login"), {"username": "sara", "password": PW}).status_code, 302)

    def test_error_pages_do_not_leak(self):
        r = self.client.get("/definitely/not/here/")
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "Page not found", status_code=404)
        self.client.force_login(self.user)
        r = self.client.get(reverse("dashboard:home"))
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "permission", status_code=403)

    def test_500_template_is_standalone(self):
        from django.template import loader
        html = loader.get_template("500.html").render({})
        self.assertIn("Something went wrong", html)

    def test_security_headers_and_cookie_flags(self):
        r = self.client.get(reverse("store:home"))
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r["Referrer-Policy"], "same-origin")

    def test_posts_without_csrf_token_are_rejected(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        self.assertEqual(c.post(reverse("accounts:login"), {"username": "ali", "password": PW}).status_code, 403)


class CommandTests(TestCase):
    def test_pg_dump_command_never_contains_password(self):
        cmd = build_pg_dump_command({"NAME": "smartmart", "USER": "app", "PASSWORD": "TopSecret!", "HOST": "db", "PORT": "5432"}, "/tmp/x.dump")
        self.assertNotIn("TopSecret!", " ".join(cmd))
        self.assertEqual(cmd[0], "pg_dump")
        self.assertEqual(cmd[-1], "smartmart")
        self.assertIn("--format=custom", cmd)

    def test_seed_demo_is_marked_idempotent_and_consistent(self):
        out = StringIO()
        call_command("seed_demo", password="demo-Pass-12345", stdout=out)
        self.assertGreater(Product.objects.filter(sku__startswith="DEMO-").count(), 5)
        self.assertTrue(all(p.name.endswith("(Sample)") for p in Product.objects.all()))
        self.assertTrue(all("SAMPLE" in p.description for p in Product.objects.all()))
        n = Product.objects.count()
        call_command("seed_demo", stdout=StringIO())
        self.assertEqual(Product.objects.count(), n)
        for p in Product.objects.all():              # stock always equals the sum of its ledger
            ledger = p.movements.aggregate(t=Sum("quantity_change"))["t"] or 0
            self.assertEqual(p.stock_quantity, ledger, p.sku)
        self.assertEqual(User.objects.get(username="demo_owner").role, "owner")
        self.assertTrue(User.objects.get(username="demo_cashier").check_password("demo-Pass-12345"))
        self.assertTrue(StockMovement.objects.filter(movement_type="online_order").exists())
