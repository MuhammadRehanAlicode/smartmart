from .base import *  # noqa
import os

DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"
SECRET_KEY = SECRET_KEY or "dev-only-insecure-key"
ALLOWED_HOSTS = ALLOWED_HOSTS or ["localhost", "127.0.0.1", "testserver"]

# The generated Tailwind bundle is intentionally ignored by git. Use Tailwind's
# browser build in development unless the developer explicitly opts out, so a
# fresh checkout does not render dashboard utility classes without any styles.
USE_TAILWIND_CDN = os.environ.get("USE_TAILWIND_CDN", "True") == "True"

REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_RENDERER_CLASSES": [  # noqa: F405
    "rest_framework.renderers.JSONRenderer", "rest_framework.renderers.BrowsableAPIRenderer"]}
