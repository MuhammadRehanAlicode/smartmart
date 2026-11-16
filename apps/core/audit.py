from .models import AuditLog


def log_action(user, action, target="", **details):
    actor = user if getattr(user, "is_authenticated", False) else None
    return AuditLog.objects.create(user=actor, action=action, target=str(target), details=details)
