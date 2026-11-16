"""Remembers a guest's "Add to cart" intent so it can be completed exactly once after login / sign-up.

The intent lives only in the visitor's server-side session (never in the cart) until authentication succeeds.
"""
import time

from django.contrib import messages

from apps.orders.services import MAX_LINE_QTY, OrderError, cart_add, storefront_products

PENDING_KEY = "pending_cart_add"
PENDING_TTL = 10 * 60  # seconds; an abandoned intent must not surprise the visitor later


def is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def remember_pending(request, product_id, quantity):
    """Store the intent if the product can really be bought. Returns True when stored."""
    if not storefront_products().filter(pk=product_id, stock_quantity__gt=0).exists():
        request.session.pop(PENDING_KEY, None)
        return False
    request.session[PENDING_KEY] = {"product_id": int(product_id),
                                    "quantity": max(1, min(int(quantity), MAX_LINE_QTY)), "ts": int(time.time())}
    return True


def clear_pending(request):
    request.session.pop(PENDING_KEY, None)


def complete_pending(request):
    """Call right after a successful login/registration. Adds the remembered product once.

    The intent is removed *before* the cart is touched, so a retry or a refresh can never add it twice.
    Returns the CartItem or None.
    """
    data = request.session.pop(PENDING_KEY, None)
    user = request.user
    if not data or not user.is_authenticated or not user.is_customer:
        return None
    if time.time() - data.get("ts", 0) > PENDING_TTL:
        return None
    try:
        item = cart_add(user, data["product_id"], data["quantity"])
    except OrderError as exc:
        messages.error(request, str(exc))
        return None
    messages.success(request, "Product added to your cart")
    return item
