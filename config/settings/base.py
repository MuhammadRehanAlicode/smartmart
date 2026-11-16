import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.core",
    "apps.accounts",
    "apps.products",
    "apps.inventory",
    "apps.suppliers",
    "apps.purchases",
    "apps.sales",
    "apps.finance",
    "apps.reports",
    "apps.customers",
    "apps.payments",
    "apps.orders",
    "apps.store",
    "apps.api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "django.template.context_processors.media",
        "apps.core.context_processors.ui",
    ]},
}]

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=600
    )
}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:sign-in"
LOGIN_REDIRECT_URL = "accounts:post-login"
LOGOUT_REDIRECT_URL = "store:home"

LANGUAGE_CODE = "en"
TIME_ZONE = "Asia/Karachi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
from decimal import Decimal  # noqa: E402

DELIVERY_FEE = Decimal(os.environ.get("DELIVERY_FEE", "150.00"))
FREE_DELIVERY_THRESHOLD = Decimal(os.environ.get("FREE_DELIVERY_THRESHOLD", "2000.00"))
STORE_PHONE = os.environ.get("STORE_PHONE", "")
STORE_ADDRESS = os.environ.get("STORE_ADDRESS", "")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")
CONTACT_WHATSAPP = os.environ.get("CONTACT_WHATSAPP", "")
CONTACT_BUSINESS_HOURS = os.environ.get("CONTACT_BUSINESS_HOURS", "")
CONTACT_MAP_EMBED_URL = os.environ.get("CONTACT_MAP_EMBED_URL", "").strip()
if not CONTACT_MAP_EMBED_URL.startswith("https://"):
    CONTACT_MAP_EMBED_URL = ""
CONTACT_SOCIAL_LINKS = [
    (label, os.environ.get(env_name, ""))
    for label, env_name in (("Facebook", "CONTACT_FACEBOOK"), ("Instagram", "CONTACT_INSTAGRAM"),
                            ("X", "CONTACT_X"), ("YouTube", "CONTACT_YOUTUBE"))
    if os.environ.get(env_name, "").strip().startswith("https://")
]
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "False").lower() == "true"
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "False").lower() == "true"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "webmaster@localhost")
USE_TAILWIND_CDN = os.environ.get("USE_TAILWIND_CDN", "False") == "True"

# Preview defaults follow the About page design brief. Set verified business figures in the environment before publishing.
ABOUT_STATS = [
    {"value": os.environ.get("ABOUT_HAPPY_CUSTOMERS", "10K+"), "label": "Happy Customers", "icon": "users"},
    {"value": os.environ.get("ABOUT_PRODUCTS_AVAILABLE", "5K+"), "label": "Products Available", "icon": "grid"},
    {"value": os.environ.get("ABOUT_ON_TIME_DELIVERY", "99%"), "label": "On-Time Delivery", "icon": "truck"},
    {"value": os.environ.get("ABOUT_FRESH_NATURAL", "100%"), "label": "Fresh & Natural", "icon": "leaf"},
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],  # session + CSRF
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.api.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "apps.api.exceptions.api_exception_handler",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle", "rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "60/min", "user": "300/min", "login": "10/min"},
}

# Uploads and request size limits
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 3 * 1024 * 1024

# Cookies / headers
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
ADMIN_URL = os.environ.get("ADMIN_URL", "admin/")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
