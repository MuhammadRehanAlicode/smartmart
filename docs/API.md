# REST API v1

Base URL: `/api/v1/`. JSON only. Authentication is **Django session cookies with CSRF protection** (the same login the
website uses). No token authentication is enabled; if a separate mobile/SPA client on another domain is needed later,
add a short-lived token scheme deliberately rather than loosening CSRF.

## Authentication flow
1. `GET /auth/csrf/` → `{"csrfToken": "..."}` (also sets the `csrftoken` cookie).
2. `POST /auth/login/` with header `X-CSRFToken: <token>` and body `{"username", "password"}` → user profile.
   Superusers receive HTTP 202 with `requires_2fa`, `setup_required` and `verification_url`; the password does not create
   an authenticated session. Enroll through the web setup page if requested, or POST `{"code":"123456"}` to
   `/auth/2fa/verify/` with the same CSRF token/session to complete sign-in. This returns the user profile after verification.
   Limits: 10 requests/min per client; 5 wrong passwords per IP+username lock that pair for 15 minutes (HTTP 429), with a
   separate 5-attempt, 15-minute authenticator/recovery-code limit per superuser.
3. Send the `X-CSRFToken` header on every `POST/PATCH/PUT/DELETE`.
4. `POST /auth/logout/` → 204.  `GET|PATCH /auth/me/` → own profile (`first_name,last_name,email,phone`; role is read-only).

## Roles
| Role | Can |
|---|---|
| Owner | everything |
| Staff (cashier) | read products/stock/sales/orders/customers, create sales, manage order status. Never sees `cost_price`/`unit_cost` |
| Customer | own profile, cart, checkout, own orders only |

## Error format
Every error: `{"error": {"status": 400, "code": "invalid", "message": "...", "details": {...}|null}}`
Codes: `invalid` (400 validation, `details` has per-field messages), `business_rule` (400), `insufficient_stock` (409),
`permission_denied` (403), `not_authenticated` (403), `not_found` (404), `throttled` (429), `locked` (429).

## Lists
Paginated: `{"count","next","previous","results"}`; `?page=2&page_size=50` (max 100). Many lists support `?search=` and `?ordering=`.

## Endpoints
| Method & path | Who | Notes |
|---|---|---|
| `GET/POST /categories/`, `GET/PUT/PATCH /categories/{id}/` | read staff+, write owner | |
| `GET /products/` | staff+ | `?search=` (name/SKU/barcode) `&category=ID&stock=low\|out&online=true&archived=true&ordering=-selling_price` |
| `POST /products/` | owner | `opening_stock` creates an opening movement. SKU is upper-cased; duplicates rejected |
| `GET/PUT/PATCH /products/{id}/` | read staff+, write owner | `stock_quantity` is read-only; price changes are audit-logged. No DELETE (archive instead) |
| `POST /products/{id}/adjust-stock/` | owner | `{"quantity_change": -3, "reason": "Damaged"}`; 409 if it would go negative |
| `POST /products/{id}/archive/` · `/restore/` | owner | |
| `GET /stock-movements/` | staff+ | `?product=ID&type=sale&date_from=YYYY-MM-DD&date_to=` read-only ledger |
| `GET/POST /suppliers/`, `GET/PUT/PATCH /suppliers/{id}/` | owner | `balance` = owed for received purchases |
| `GET/POST /purchases/`, `GET /purchases/{id}/` | owner | create body: `supplier, invoice_reference, amount_paid, notes, items:[{product,quantity,unit_cost}]`; created as *pending* |
| `POST /purchases/{id}/receive/` · `/cancel/` | owner | stock increases only on receive; 400 if not pending |
| `GET /sales/`, `GET /sales/{id}/` | staff+ | `?date_from&date_to` |
| `POST /sales/` | staff+ | `{"items":[{"product_id","quantity"}], "payment_method":"cash\|card\|wallet\|other", "amount_tendered", "idempotency_key"}`. Repeating the same `idempotency_key` returns the original sale. 409 on insufficient stock |
| `POST /sales/{id}/return/` | owner | `{"items":[{"sale_item_id","quantity"}], "reason", "restock": true}` |
| `GET /customers/` | staff+ | `?search=` read-only |
| `GET /cart/`, `POST /cart/` `{"product_id","quantity"}` | customer | quantity clamps to stock |
| `PATCH/DELETE /cart/items/{id}/` | customer | `{"quantity": 0}` removes |
| `POST /checkout/` | customer | `{"customer_name","phone","address","delivery_instructions","idempotency_key"}` → 201 new order, 200 if the key was already used. Cash on delivery |
| `GET /orders/`, `GET /orders/{id}/` | customer (own) / staff+ (all) | other customers' orders return 404 |
| `POST /orders/{id}/status/` | staff+ | `{"status":"confirmed","note":""}`; workflow Pending→Confirmed→Processing→Out for delivery→Delivered; cancelling needs a note |
| `POST /orders/{id}/cancel/` | customer | only while Pending/Confirmed |
| `GET /reports/summary/` | owner | `?date_from&date_to` (default last 30 days): revenue, refunds, cogs, gross/net profit, expenses, purchase spend, inventory value |
| `GET /reports/daily/` · `/reports/best-sellers/` | owner | |

Money values are strings with two decimals. Dates are ISO `YYYY-MM-DD`; timestamps ISO 8601.
