# Database backups and restore

What to protect: the **PostgreSQL database** (all business data and the audit log), the **`media/`** folder (product
images) and your **`.env`** (store it in a password manager, not in Git).

## Taking a backup
```bash
python manage.py backup_db                 # writes backups/smartmart_YYYYmmdd_HHMMSS.dump (+ media archive)
python manage.py backup_db --keep 30 --output-dir /var/backups/smartmart
```
- PostgreSQL: `pg_dump` custom format. The password goes through the `PGPASSWORD` environment variable, never the command line.
- SQLite (development only): SQLite's online backup, safe while the app runs.
- Files are created readable by their owner only (mode 600). Old backups beyond `--keep` are deleted.

### Automate (Linux cron, every night at 02:30)
```
30 2 * * * cd /srv/smartmart && /srv/smartmart/venv/bin/python manage.py backup_db --keep 30 >> /var/log/smartmart-backup.log 2>&1
```
Also copy the `backups/` folder **off the server** (another machine or encrypted cloud storage). A backup on the same disk
does not survive a disk failure. Encrypt it if it leaves your control (e.g. `gpg -c file.dump`).

## Restoring (PostgreSQL)
1. Stop the app: `sudo systemctl stop smartmart`.
2. Make a safety copy of the current state first: `python manage.py backup_db --output-dir /tmp/before-restore`.
3. Recreate an empty database (**this destroys the current data**):
   ```bash
   sudo -u postgres dropdb smartmart
   sudo -u postgres createdb -O smartmart_user smartmart
   ```
4. Restore:
   ```bash
   pg_restore --no-owner --role=smartmart_user -d smartmart backups/smartmart_20261016_023000.dump
   ```
5. Restore media: `tar -xzf backups/smartmart_media_20261016_023000.tar.gz -C /srv/smartmart/`
6. Apply any newer migrations: `python manage.py migrate`, then start: `sudo systemctl start smartmart`.
7. Check: log in, open Reports → Stock valuation, and open a recent sale and order.

## Restoring (SQLite, development)
Stop the server, copy the `.sqlite3` backup over `db.sqlite3`, start the server.

## Test your backups
A backup you have never restored is a hope, not a backup. Once a quarter restore the latest dump into a scratch database
(`createdb smartmart_test; pg_restore -d smartmart_test file.dump`) and confirm the product and sales counts look right.
