# Superuser two-factor authentication

All Django superuser accounts must complete authenticator verification before a management session is created. This policy
applies to the storefront login, REST API login, Django admin and any other route that might create a superuser session.
Ordinary staff and customer authentication is unchanged.

## Sign-in flow

1. Password validation creates a five-minute, session-bound pre-authentication state, not an authenticated session.
2. A first-time user scans the locally generated QR code (or types the displayed secret) into Google Authenticator or a
   compatible TOTP application, then proves enrollment with a six-digit code.
3. Later sign-ins require a current code or one unused recovery code. TOTP accepts the current 30-second interval and one
   adjacent interval on either side. A successfully used interval cannot be replayed.
4. The REST API returns a verification challenge after password validation and exposes `POST /api/v1/auth/2fa/verify/`.
   API clients must obtain the CSRF token and submit the same-origin session cookie with the code.

Rate limits are stored in Django's cache. Configure Redis or another shared cache for production deployments with more than
one worker. Unverified authenticated superuser sessions are logged out and redirected by middleware, including sessions
created through an alternate auth route.

## Recovery and settings

Enrollment generates ten random recovery codes. Their plaintext is shown once; only Django password hashes are stored.
Each code is single-use. A logged-in superuser can regenerate codes or disable the authenticator under Dashboard → Security;
both actions require the current password and an authenticator or unused recovery code. Disabling signs the account out.
Because superusers are required to enroll, the next superuser login starts enrollment again.

## Deployment and key management

Install the pinned-minimum dependencies with `pip install -r requirements.txt`, then apply migrations with
`python manage.py migrate`. PyOTP creates and validates standards-compatible TOTP codes and provisioning URIs; its
timecode verification result is stored transactionally to prevent replay. TOTP secrets are encrypted with Fernet from
`cryptography`; QR images are generated locally by `qrcode` and are not sent to a third party.

Set `TOTP_ENCRYPTION_KEY` to a unique long random value in production and keep it stable and backed up. If it is omitted,
the Django `SECRET_KEY` is used. Changing the key makes existing encrypted authenticator secrets unreadable; users then
need an account recovery/reset operation. Never log the key, provisioning URI, QR data or manual setup secret.

Generate a key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Verification

Run the focused authentication coverage with `python manage.py test apps.accounts.tests.test_two_factor`. The tests cover
temporary pre-authentication, initial setup, invalid codes, replay prevention, recovery-code use, recovery-code
regeneration and disable confirmation, ordinary staff login, API challenge verification and direct admin access.
