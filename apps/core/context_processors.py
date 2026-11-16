from django.conf import settings
from django.db.models import Sum


def ui(request):
    count = 0
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.role == "customer":
        from apps.orders.models import CartItem
        count = CartItem.objects.filter(cart__user=user).aggregate(n=Sum("quantity"))["n"] or 0
    return {
        "USE_TAILWIND_CDN": settings.USE_TAILWIND_CDN, "STORE_NAME": "W&B General Store", "CURRENCY": "Rs.",
        "CART_COUNT": count, "STORE_PHONE": settings.STORE_PHONE, "STORE_ADDRESS": settings.STORE_ADDRESS,
        "DELIVERY_FEE": settings.DELIVERY_FEE, "FREE_DELIVERY_THRESHOLD": settings.FREE_DELIVERY_THRESHOLD,
    }
