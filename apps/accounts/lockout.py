"""Small cache-based brute-force guard shared by the web login and the API login.

5 failures per (IP, username) within 15 minutes lock that pair out. The cache must be shared across
processes in production (e.g. Redis; see README). REMOTE_ADDR is used as the client IP: if you run behind a
proxy, configure it to set REMOTE_ADDR correctly rather than trusting X-Forwarded-For.
"""
import hashlib

from django.core.cache import cache

LIMIT = 5
WINDOW = 15 * 60


def _key(request, username):
    raw = f"{request.META.get('REMOTE_ADDR', '')}|{(username or '').strip().lower()}"
    return "login-fail:" + hashlib.sha256(raw.encode()).hexdigest()


def is_locked(request, username):
    return cache.get(_key(request, username), 0) >= LIMIT


def register_failure(request, username):
    key = _key(request, username)
    cache.add(key, 0, WINDOW)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, WINDOW)


def clear(request, username):
    cache.delete(_key(request, username))
