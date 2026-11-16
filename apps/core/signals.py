from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .audit import log_action


@receiver(user_logged_in)
def _logged_in(sender, request, user, **kwargs):
    log_action(user, "auth.login", user.username)


@receiver(user_logged_out)
def _logged_out(sender, request, user, **kwargs):
    if user is not None:
        log_action(user, "auth.logout", user.username)


@receiver(user_login_failed)
def _failed(sender, credentials, request=None, **kwargs):
    # Never store the password; the attempted username is useful for spotting attacks.
    log_action(None, "auth.login_failed", str(credentials.get("username", ""))[:150])
