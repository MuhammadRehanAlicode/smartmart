"""Progressive Web App endpoints: web app manifest, service worker (must live at the site root) and offline pages."""
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.generic import TemplateView

# Bump when the service worker's caching rules change; old caches are deleted when the new worker activates.
PWA_CACHE_VERSION = "v1"


def manifest(request):
    data = {
        "name": "W&B General Store",
        "short_name": "W&B General Store",
        "description": "Fresh groceries and everyday essentials, delivered. Keeps working when your connection drops.",
        "id": "/",
        "start_url": "/?source=pwa",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": "#f5f9ff",
        "theme_color": "#082b60",
        "categories": ["shopping", "food"],
        "icons": [
            {"src": static("img/pwa/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": static("img/pwa/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": static("img/pwa/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Shop", "url": "/shop/"},
            {"name": "My cart", "url": "/cart/"},
            {"name": "My orders", "url": "/orders/"},
        ],
    }
    response = JsonResponse(data, content_type="application/manifest+json")
    response["Cache-Control"] = "no-cache"
    return response


def service_worker(request):
    response = render(request, "pwa/sw.js", {
        "version": PWA_CACHE_VERSION,
        "admin_url": settings.ADMIN_URL.lstrip("/"),
        "USE_TAILWIND_CDN": settings.USE_TAILWIND_CDN,
    }, content_type="application/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"   # browsers must always be able to see a new worker
    return response


class OfflinePage(TemplateView):
    """Public pages (no account data). The service worker stores them so they can be shown with no connection."""
    template_name = "store/offline.html"
    page = "fallback"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["offline_page"] = self.page
        return ctx
