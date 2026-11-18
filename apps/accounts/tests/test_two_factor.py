import time

import pyotp
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.two_factor import VERIFIED_SESSION_KEY, encrypt_secret

PASSWORD = "S3cure-pass-987"


class SuperuserTwoFactorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("root2fa", "root@example.com", PASSWORD)

    def password_login(self):
        return self.client.post(reverse("accounts:sign-in"), {"username": "root2fa", "password": PASSWORD})

    def current_code(self, secret):
        return pyotp.TOTP(secret, interval=30).at(time.time())

    def login_verified(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[VERIFIED_SESSION_KEY] = self.user.pk
        session.save()

    def test_superuser_password_login_only_creates_temporary_setup_state(self):
        response = self.password_login()
        self.assertRedirects(response, reverse("accounts:2fa-setup"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 302)

    def test_setup_rejects_invalid_otp_and_enables_after_valid_otp(self):
        self.password_login()
        setup = self.client.get(reverse("accounts:2fa-setup"))
        self.assertContains(setup, "Manual setup key")
        self.assertEqual(setup["Referrer-Policy"], "same-origin")
        secret = self.user.__class__.objects.get(pk=self.user.pk).totp_secret_encrypted
        from apps.accounts.two_factor import decrypt_secret
        raw = decrypt_secret(secret)
        bad = self.client.post(reverse("accounts:2fa-setup"), {"code": "000000"})
        self.assertEqual(bad.status_code, 400)
        good = self.client.post(reverse("accounts:2fa-setup"), {"code": self.current_code(raw)})
        self.assertContains(good, "Shown only once")
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.totp_confirmed_at)
        self.assertEqual(len(self.user.recovery_code_hashes), 10)
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 200)

    def test_subsequent_login_requires_otp_and_replay_is_rejected(self):
        secret = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
        self.user.totp_secret_encrypted = encrypt_secret(secret)
        from django.utils import timezone
        self.user.totp_confirmed_at = timezone.now()
        self.user.save()
        self.password_login()
        self.assertNotIn("_auth_user_id", self.client.session)
        code = self.current_code(secret)
        success = self.client.post(reverse("accounts:2fa-challenge"), {"code": code})
        self.assertRedirects(success, reverse("dashboard:home"))
        self.client.post(reverse("accounts:logout"))
        self.password_login()
        replay = self.client.post(reverse("accounts:2fa-challenge"), {"code": code})
        self.assertEqual(replay.status_code, 400)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_recovery_code_is_single_use(self):
        from django.contrib.auth.hashers import make_password
        from django.utils import timezone
        self.user.totp_secret_encrypted = encrypt_secret("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP")
        self.user.totp_confirmed_at = timezone.now()
        self.user.recovery_code_hashes = [make_password("ABCDEF1234")]
        self.user.save()
        self.password_login()
        response = self.client.post(reverse("accounts:2fa-challenge"), {"code": "ABCDE-F1234"})
        self.assertRedirects(response, reverse("dashboard:home"))
        self.assertEqual(self.user.__class__.objects.get(pk=self.user.pk).recovery_code_hashes, [])

    def test_api_password_login_returns_challenge_without_authenticating(self):
        response = self.client.post(reverse("api:login"), {"username": "root2fa", "password": PASSWORD}, content_type="application/json")
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()["requires_2fa"])
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_api_otp_completes_the_superuser_session(self):
        from django.utils import timezone
        secret = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
        self.user.totp_secret_encrypted = encrypt_secret(secret)
        self.user.totp_confirmed_at = timezone.now()
        self.user.save()
        self.client.post(reverse("api:login"), {"username": "root2fa", "password": PASSWORD}, content_type="application/json")
        response = self.client.post(reverse("api:2fa-verify"), {"code": self.current_code(secret)}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], self.user.username)
        self.assertIn("_auth_user_id", self.client.session)

    def test_regular_staff_login_does_not_require_two_factor(self):
        staff = User.objects.create_user("cashier", password=PASSWORD, role=User.Role.STAFF)
        response = self.client.post(reverse("accounts:sign-in"), {"username": staff.username, "password": PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_direct_admin_access_cannot_bypass_two_factor(self):
        self.client.force_login(self.user)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:sign-in"), response["Location"])

    def test_admin_password_form_rejects_superuser_before_authentication(self):
        response = self.client.post(reverse("admin:login"), {"username": "root2fa", "password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "Use the SmartMart sign-in page")

    def test_authenticated_owner_can_regenerate_recovery_codes_with_password_and_otp(self):
        from django.utils import timezone
        secret = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
        self.user.totp_secret_encrypted = encrypt_secret(secret)
        self.user.totp_confirmed_at = timezone.now()
        self.user.save()
        self.login_verified()
        response = self.client.post(reverse("accounts:security-settings"), {
            "action": "regenerate", "password": PASSWORD, "code": self.current_code(secret),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["codes"]), 10)
        self.user.refresh_from_db()
        self.assertEqual(len(self.user.recovery_code_hashes), 10)
        self.assertIsNotNone(self.user.totp_last_verified_at)

    def test_disable_requires_password_and_second_factor_then_clears_configuration(self):
        from django.utils import timezone
        secret = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
        self.user.totp_secret_encrypted = encrypt_secret(secret)
        self.user.totp_confirmed_at = timezone.now()
        self.user.save()
        self.login_verified()
        response = self.client.post(reverse("accounts:security-settings"), {
            "action": "disable", "password": "wrong", "code": self.current_code(secret),
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.totp_confirmed_at)
        response = self.client.post(reverse("accounts:security-settings"), {
            "action": "disable", "password": PASSWORD, "code": self.current_code(secret),
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.totp_confirmed_at)
        self.assertEqual(self.user.totp_secret_encrypted, "")
