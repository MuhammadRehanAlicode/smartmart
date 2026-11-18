"""TOTP and recovery-code helpers for privileged superuser accounts."""
import base64
import hashlib
import io
import secrets
import time

import pyotp

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone


PREAUTH_SESSION_KEY = "superuser_2fa_preauth"
VERIFIED_SESSION_KEY = "superuser_2fa_verified"
PREAUTH_TTL = 5 * 60
TOTP_PERIOD = 30
TOTP_WINDOW = 1
FAILURE_LIMIT = 5
FAILURE_WINDOW = 15 * 60


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover - production dependency
        raise ImproperlyConfigured("Install cryptography to use superuser two-factor authentication.") from exc
    if not settings.TOTP_ENCRYPTION_KEY:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY or TOTP_ENCRYPTION_KEY before enabling superuser 2FA.")
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.TOTP_ENCRYPTION_KEY.encode()).digest())
    return Fernet(key)


def new_secret():
    return pyotp.random_base32()


def encrypt_secret(secret):
    return _fernet().encrypt(secret.encode()).decode("ascii")


def decrypt_secret(ciphertext):
    return _fernet().decrypt(ciphertext.encode()).decode("ascii")


def provisioning_uri(user, secret):
    totp = pyotp.TOTP(secret, digits=6, interval=TOTP_PERIOD)
    return totp.provisioning_uri(name=user.get_username(), issuer_name="SmartMart")


def qr_data_uri(uri):
    import qrcode
    image = qrcode.make(uri)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def matching_totp_step(secret, code, now=None):
    code = str(code or "").strip()
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    now = time.time() if now is None else now
    try:
        return pyotp.TOTP(secret, digits=6, interval=TOTP_PERIOD).verify_and_get_timecode(
            code, for_time=now, valid_window=TOTP_WINDOW,
        )
    except pyotp.OTPVerificationError:
        return None


def generate_recovery_codes(count=10):
    raw_codes = [secrets.token_hex(5).upper() for _ in range(count)]
    display_codes = [f"{code[:5]}-{code[5:]}" for code in raw_codes]
    return display_codes, [make_password(code) for code in raw_codes]


def _recovery_candidate(code):
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def _failure_key(user_id):
    return f"superuser-2fa-fail:{user_id}"


def is_rate_limited(user_id):
    return cache.get(_failure_key(user_id), 0) >= FAILURE_LIMIT


def record_failure(user_id):
    key = _failure_key(user_id)
    cache.add(key, 0, FAILURE_WINDOW)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, FAILURE_WINDOW)


def clear_failures(user_id):
    cache.delete(_failure_key(user_id))


@transaction.atomic
def verify_and_consume(user, code):
    """Validate an OTP once per time step or consume one recovery code atomically."""
    from .models import User
    locked = User.objects.select_for_update().get(pk=user.pk)
    if locked.totp_confirmed_at and locked.totp_secret_encrypted:
        secret = decrypt_secret(locked.totp_secret_encrypted)
        step = matching_totp_step(secret, code)
        if step is not None and (locked.totp_last_step is None or step > locked.totp_last_step):
            locked.totp_last_step = step
            locked.totp_last_verified_at = timezone.now()
            locked.save(update_fields=["totp_last_step", "totp_last_verified_at"])
            clear_failures(user.pk)
            return "totp"
    candidate = _recovery_candidate(code)
    if len(candidate) == 10:
        for index, code_hash in enumerate(locked.recovery_code_hashes or []):
            if check_password(candidate, code_hash):
                locked.recovery_code_hashes = locked.recovery_code_hashes[:index] + locked.recovery_code_hashes[index + 1:]
                locked.totp_last_verified_at = timezone.now()
                locked.save(update_fields=["recovery_code_hashes", "totp_last_verified_at"])
                clear_failures(user.pk)
                return "recovery"
    record_failure(user.pk)
    return None


def set_preauth(request, user):
    request.session.cycle_key()
    request.session[PREAUTH_SESSION_KEY] = {
        "user_id": user.pk,
        "backend": user.backend,
        "expires": int(time.time()) + PREAUTH_TTL,
    }


def get_preauth_user(request):
    from .models import User
    state = request.session.get(PREAUTH_SESSION_KEY) or {}
    if not state or int(state.get("expires", 0)) < int(time.time()):
        request.session.pop(PREAUTH_SESSION_KEY, None)
        return None
    try:
        user = User.objects.get(pk=state.get("user_id"), is_superuser=True, is_active=True)
    except (User.DoesNotExist, TypeError, ValueError):
        request.session.pop(PREAUTH_SESSION_KEY, None)
        return None
    user.backend = state.get("backend") or settings.AUTHENTICATION_BACKENDS[0]
    return user


def complete_login(request, user):
    from django.contrib.auth import login
    login(request, user, backend=user.backend)
    request.session.pop(PREAUTH_SESSION_KEY, None)
    request.session[VERIFIED_SESSION_KEY] = user.pk
    request.session.set_expiry(0)
    return user


def verified_session(request, user):
    return request.session.get(VERIFIED_SESSION_KEY) == user.pk


