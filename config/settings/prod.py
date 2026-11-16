from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa

DEBUG = False
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in production.")
if not ALLOWED_HOSTS:
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if railway_domain:
        ALLOWED_HOSTS = [railway_domain]
    else:
        raise ImproperlyConfigured(
            "Set DJANGO_ALLOWED_HOSTS or expose the service with a Railway public domain."
        )

railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
if railway_domain:
    CSRF_TRUSTED_ORIGINS.append(f"https://{railway_domain}")

SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_CONTENT_TYPE_NOSNIFF = True
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
