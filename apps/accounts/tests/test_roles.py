from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.core.models import AuditLog

PW = "S3cure-pass-987"


def make(username, role):
    return User.objects.create_user(username=username, password=PW, role=role, first_name=username)


class RoleAccessTests(TestCase):
    def setUp(self):
        self.owner = make("owner1", User.Role.OWNER)
        self.staff = make("cashier1", User.Role.STAFF)
        self.customer = make("cust1", User.Role.CUSTOMER)

    def test_storefront_is_default_landing_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "store/home.html")

        for name in ("accounts:login", "accounts:sign-in"):
            self.assertRedirects(self.client.get(reverse(name)), reverse("store:home"))

    def test_anonymous_redirected_to_login(self):
        r = self.client.get(reverse("dashboard:home"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("accounts:login"), r["Location"])

    def test_customer_forbidden_from_dashboard(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 403)

    def test_staff_and_owner_can_open_dashboard(self):
        for u in (self.staff, self.owner):
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 200)

    def test_staff_cannot_manage_staff(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("dashboard:staff-list")).status_code, 403)
        r = self.client.post(reverse("dashboard:staff-create"), {})
        self.assertEqual(r.status_code, 403)

    def test_owner_can_create_staff_and_it_is_audited(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse("dashboard:staff-create"), {
            "username": "newcashier", "first_name": "New", "last_name": "Cashier",
            "phone": "03001234567", "password1": PW, "password2": PW,
        })
        self.assertRedirects(r, reverse("dashboard:staff-list"))
        self.assertEqual(User.objects.get(username="newcashier").role, User.Role.STAFF)
        self.assertTrue(AuditLog.objects.filter(action="staff.created", target="newcashier").exists())

    def test_login_redirects_by_role(self):
        self.client.force_login(self.staff)
        self.assertRedirects(self.client.get(reverse("accounts:post-login")), reverse("dashboard:home"))
        self.client.force_login(self.customer)
        self.assertRedirects(self.client.get(reverse("accounts:post-login")), reverse("store:home"))

    def test_superuser_is_owner(self):
        su = User.objects.create_superuser("root", "r@example.com", PW)
        self.assertEqual(su.role, User.Role.OWNER)


class RegistrationTests(TestCase):
    data = {
        "username": "ali", "first_name": "Ali", "last_name": "Khan", "email": "ali@example.com",
        "phone": "03001234567", "password1": PW, "password2": PW,
    }

    def test_registration_creates_customer(self):
        r = self.client.post(reverse("accounts:register"), self.data)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(User.objects.get(username="ali").role, User.Role.CUSTOMER)

    def test_cannot_self_assign_owner_role(self):
        self.client.post(reverse("accounts:register"), {**self.data, "role": "owner", "is_superuser": "on", "is_staff": "on"})
        user = User.objects.get(username="ali")
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertFalse(user.is_superuser)

    def test_invalid_phone_rejected(self):
        r = self.client.post(reverse("accounts:register"), {**self.data, "phone": "abc"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="ali").exists())

    def test_logout_requires_post(self):
        self.client.force_login(make("x", User.Role.CUSTOMER))
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
