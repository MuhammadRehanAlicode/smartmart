# Offline-first storefront

Adds a PWA layer, an offline cart, offline orders and automatic background sync. Existing online flows are unchanged.

**Run:** `python manage.py migrate` (applies `orders.0002_offline_orders`), then `python manage.py runserver`
(use `http://localhost:8000`; service workers need localhost or HTTPS). Tests: `python manage.py test apps.orders apps.store`.

**Flow:** offline "Place order" -> order saved in IndexedDB with a UUID, status `pending_sync` -> on reconnect (online event,
Background Sync, or 30 s timer) it is POSTed to `/api/v1/offline/orders/` -> the server recomputes prices/totals, locks product rows,
validates stock, creates the Order (UUID = `Order.idempotency_key`) -> local status becomes `confirmed`, `rejected` or `requires_attention`.
Retries use exponential backoff (5 s doubling, max 15 min). Local orders are never deleted by sync.

**Never cached:** `/api/`, `/cart/`, `/checkout/`, `/orders/`, `/profile/`, `/accounts/`, `/dashboard/`, admin. Cached catalogue pages have the
CSRF token, flash messages, user name and cart count removed. No card data is ever stored (cash on delivery only).

**Bump** `PWA_CACHE_VERSION` in `apps/store/pwa.py` when changing service-worker caching rules.
