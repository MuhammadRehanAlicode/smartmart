# SmartMart: General Store Management and E-Commerce (Django)

One Django project with a shared database and shared inventory for:
- **Back office** (owner and cashiers): products, suppliers, purchases, stock, POS sales with receipts, returns, expenses, orders, dashboard and reports.
- **Online storefront** (customers): browse, cart, cash-on-delivery checkout, order tracking, profile.
- **REST API** under `/api/v1/` (see `docs/API.md`).

## First run
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                       # set DJANGO_SECRET_KEY
python manage.py migrate
python manage.py test                      # fix anything that fails before going further
npm install && npm run build:css           # or keep USE_TAILWIND_CDN=True in .env while developing
python manage.py createsuperuser           # superusers are always the Owner role
python manage.py runserver
```

The migration files are included in the repository. The GitHub Actions workflow (`.github/workflows/ci.yml`) runs the test
suite against PostgreSQL on every push and pull request.

## Deploy to Railway
Connect this repository to Railway and add a PostgreSQL service. Set the Django service's `DATABASE_URL` to the PostgreSQL
service's `DATABASE_URL` reference, then configure these variables:

```text
DJANGO_SETTINGS_MODULE=config.settings.prod
DJANGO_SECRET_KEY=<generate a unique long random value>
DJANGO_ALLOWED_HOSTS=<your Railway domain, without https://>
```

Generate a Railway public domain for the web service. Railway builds CSS and static files, applies migrations before each
deploy, and starts Gunicorn using `railway.json`. Add any store, mail, and contact settings needed from `.env.example` in
Railway's Variables panel. Do not set `DJANGO_DEBUG=True` in production.

Railway's filesystem is ephemeral unless a volume is configured. Uploaded product photos and dashboard banners can be lost
on redeploy; configure persistent media storage before relying on uploads in production. The bundled catalog images are part
of the repository and are deployed with the app.

**Sample data**: `python manage.py seed_demo` creates clearly marked sample products (`DEMO-…`, “(Sample)”), a supplier, a
purchase, two sales, one online order and three demo accounts (random password printed once). Never run it on a live store.

## Product image storage
New product images uploaded in the dashboard are saved under `MEDIA_ROOT/products/`. The built-in catalog product artwork
is stored under `media/catalog/products/`; uploaded product files and catalog artwork are both served from `MEDIA_URL`.
Development serves media while `DEBUG=True`. In production, configure the web server to serve `/media/` from
`MEDIA_ROOT` (see `docs/DEPLOYMENT.md`) and include the media folder in backups.

## Roles
| Role | Access |
|---|---|
| Owner | everything: prices, stock adjustments, purchases, suppliers, returns, expenses, reports, staff accounts |
| Cashier / Staff | POS sales and receipts, view products and stock, manage online order status, limited dashboard (no profit or cost figures) |
| Customer | storefront, own cart, own orders and profile |

Roles are enforced on the server (`apps/accounts/permissions.py`, `apps/api/permissions.py`). Registration always creates a Customer.

## Project layout
```
config/            settings (base/dev/prod), urls, wsgi
apps/accounts      custom user + roles, login/lockout, staff management
apps/products      categories, products, images, discounts
apps/inventory     stock ledger; services.change_stock is the ONLY code that changes stock
apps/suppliers, purchases      suppliers, multi-item purchases (stock rises on "received")
apps/sales         POS, receipts, returns          apps/finance   expenses + all profit calculations
apps/orders, payments, customers, store   cart, checkout, orders, payment abstraction, storefront
apps/reports       dashboard figures, reports, CSV   apps/api   REST API v1   apps/core   audit log, commands
docs/              API.md, ACCOUNTING.md, VALUATION.md, BACKUP_RESTORE.md, DEPLOYMENT.md
```

## Key design rules
- Stock changes only through `change_stock` (row-locked, never negative, ledger row each time). The row locks use
  `SELECT … FOR UPDATE`, which only has effect on PostgreSQL, so run the concurrency-sensitive code on PostgreSQL.
- Sale and order lines snapshot price, discount and cost, so later price edits never rewrite history.
- Money is `DecimalField`; inventory valuation is weighted average cost (`docs/VALUATION.md`); profit definitions are in `docs/ACCOUNTING.md`.
- Duplicate submissions are blocked with idempotency keys (POS, checkout, API).
- A payment can only become *paid* online through a verified provider result (`apps/payments`).

## Security summary
Hashed passwords with Django validators, CSRF on every form and API write, session cookies HttpOnly/SameSite, HTTPS-only
cookies and HSTS in production, per-IP+username login lockout and API throttling, image type/size validation, security
headers, audit log of important changes and logins (never passwords), no secrets in Git (`.env`, `.gitignore`), custom
error pages that leak nothing, configurable admin URL. Remaining risks to review yourself: no Content-Security-Policy
(templates use some inline scripts), lockout needs a shared cache (Redis) with multiple workers, no two-factor login.

## Known gaps
Not built: returns of already-delivered online orders (handled by phone per the Help page), a password-change/reset page,
Urdu text support, online payment gateway (only the abstraction), SMS/email notifications, editing a pending purchase
through the API, order printing. Product images use the uploaded file as-is (no thumbnails).

## Docs
`docs/API.md` · `docs/DEPLOYMENT.md` · `docs/BACKUP_RESTORE.md` · `docs/ACCOUNTING.md` · `docs/VALUATION.md`
