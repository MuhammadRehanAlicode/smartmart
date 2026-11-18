# Deployment (Ubuntu + PostgreSQL + gunicorn + nginx)

## Railway

The repository includes `railway.json`. Create a Railway project from the GitHub repository, add a PostgreSQL service, and
reference its `DATABASE_URL` variable from the Django service. Generate a public domain for the Django service and set:

```text
DJANGO_SETTINGS_MODULE=config.settings.prod
DJANGO_SECRET_KEY=<unique long random value>
DJANGO_ALLOWED_HOSTS=<Railway public domain, without https://>
```

Railway builds CSS and bundled ZXing camera scanning and runs `collectstatic` during build, runs `migrate` as a pre-deploy command, and starts Gunicorn on
Railway's assigned `$PORT`. Production settings also recognize `RAILWAY_PUBLIC_DOMAIN` for allowed hosts and CSRF origins.
Add storefront and mail variables from `.env.example` as needed. Do not set `DJANGO_DEBUG=True`.

Railway's container filesystem is ephemeral by default. Uploaded product images and dashboard banners need persistent
storage before they can be relied on in production. The bundled `media/catalog/` artwork is shipped with the source.

1. **Server packages**: `sudo apt install python3-venv postgresql nginx nodejs npm`.
2. **Database**:
   ```bash
   sudo -u postgres psql -c "CREATE USER smartmart_user WITH PASSWORD '<strong-password>';"
   sudo -u postgres createdb -O smartmart_user smartmart
   ```
3. **Code**: `git clone <your private repo> /srv/smartmart && cd /srv/smartmart && python3 -m venv venv && venv/bin/pip install -r requirements.txt`.
4. **Configuration** (`/srv/smartmart/.env`, mode 600, never in Git):
   ```
   DJANGO_SETTINGS_MODULE=config.settings.prod
   DJANGO_SECRET_KEY=<python -c "import secrets;print(secrets.token_urlsafe(64))">
   DJANGO_ALLOWED_HOSTS=shop.example.com
   DATABASE_URL=postgres://smartmart_user:<password>@localhost:5432/smartmart
   ADMIN_URL=some-secret-path/
   STORE_PHONE=...
   ```
5. **Build & migrate**:
   ```bash
   npm install && npm run build:css && npm run build:js
   venv/bin/python manage.py migrate
   venv/bin/python manage.py collectstatic --noinput
   venv/bin/python manage.py createsuperuser        # becomes the Owner
   venv/bin/python manage.py check --deploy         # review every warning it prints
   ```
6. **gunicorn** (`/etc/systemd/system/smartmart.service`): `ExecStart=/srv/smartmart/venv/bin/gunicorn config.wsgi:application --bind unix:/run/smartmart.sock --workers 3`,
   with `EnvironmentFile=/srv/smartmart/.env`, `WorkingDirectory=/srv/smartmart`, a non-root `User=`.
7. **nginx**: proxy to the socket, set `proxy_set_header X-Forwarded-Proto $scheme; proxy_set_header Host $host;`, serve `/media/` from
   `/srv/smartmart/media/` (static files are served by WhiteNoise), `client_max_body_size 5m;`.
8. **HTTPS**: `sudo certbot --nginx -d shop.example.com`. The production settings redirect to HTTPS, set secure cookies and HSTS.
9. **Shared cache** (recommended): login lockout and API throttles use Django's cache. The default per-process cache is not shared
   between gunicorn workers; configure Redis (`CACHES` with `django.core.cache.backends.redis.RedisCache`) so limits are accurate.
10. **Backups**: set up the nightly cron job from `docs/BACKUP_RESTORE.md`.

## Before going live checklist
- [ ] Tests pass on a PostgreSQL database (`python manage.py test`), including concurrency-sensitive code paths.
- [ ] Do **not** run `seed_demo` on the live database; remove any `DEMO-` data if it was ever loaded.
- [ ] Owner password is long and unique; staff accounts created from Dashboard → Staff.
- [ ] `DEBUG` is off (prod settings enforce it); `ADMIN_URL` changed; firewall allows only 80/443/SSH.
- [ ] A backup has been restored once into a scratch database.
- [ ] Phone/address/delivery fee settings in `.env` are correct.
