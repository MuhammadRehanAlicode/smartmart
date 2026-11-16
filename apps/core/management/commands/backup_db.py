"""python manage.py backup_db [--output-dir backups] [--keep 14] [--no-media]

PostgreSQL: runs pg_dump in custom format (restore with pg_restore). SQLite: uses SQLite's online backup API.
The database password is passed through the PGPASSWORD environment variable, never on the command line.
See docs/BACKUP_RESTORE.md for the restore procedure.
"""
import os
import sqlite3
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def build_pg_dump_command(db, path):
    cmd = ["pg_dump", "--format=custom", "--no-owner", "--file", str(path)]
    if db.get("HOST"):
        cmd += ["--host", str(db["HOST"])]
    if db.get("PORT"):
        cmd += ["--port", str(db["PORT"])]
    if db.get("USER"):
        cmd += ["--username", str(db["USER"])]
    cmd.append(str(db["NAME"]))
    return cmd


class Command(BaseCommand):
    help = "Create a timestamped database backup (and a media archive)."

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", default=str(settings.BASE_DIR / "backups"))
        parser.add_argument("--keep", type=int, default=14, help="Keep this many newest backups of each kind.")
        parser.add_argument("--no-media", action="store_true")

    def handle(self, *args, **opts):
        out = Path(opts["output_dir"])
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        db = settings.DATABASES["default"]
        vendor = connection.vendor
        if vendor == "postgresql":
            target = out / f"smartmart_{stamp}.dump"
            env = dict(os.environ)
            if db.get("PASSWORD"):
                env["PGPASSWORD"] = str(db["PASSWORD"])
            try:
                subprocess.run(build_pg_dump_command(db, target), check=True, env=env)
            except FileNotFoundError:
                raise CommandError("pg_dump was not found. Install the PostgreSQL client tools.")
            except subprocess.CalledProcessError as exc:
                raise CommandError(f"pg_dump failed with exit code {exc.returncode}.")
        elif vendor == "sqlite":
            target = out / f"smartmart_{stamp}.sqlite3"
            src, dst = sqlite3.connect(str(db["NAME"])), sqlite3.connect(str(target))
            with dst:
                src.backup(dst)
            src.close(); dst.close()
        else:
            raise CommandError(f"Unsupported database: {vendor}")
        os.chmod(target, 0o600)
        self.stdout.write(self.style.SUCCESS(f"Database backup written to {target}"))

        media = Path(settings.MEDIA_ROOT)
        if not opts["no_media"] and media.exists() and any(media.iterdir()):
            archive = out / f"smartmart_media_{stamp}.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(media, arcname="media")
            os.chmod(archive, 0o600)
            self.stdout.write(self.style.SUCCESS(f"Media backup written to {archive}"))

        for pattern in ("smartmart_2*.dump", "smartmart_2*.sqlite3", "smartmart_media_*.tar.gz"):
            old = sorted(out.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)[opts["keep"]:]
            for p in old:
                p.unlink()
