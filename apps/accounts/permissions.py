from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


class RoleRequiredMixin(LoginRequiredMixin):
    """Anonymous -> redirect to login. Wrong role -> 403. Enforced server-side."""

    allowed_roles: tuple = ()

    def dispatch(self, request, *args, **kwargs):
        if (request.user.is_authenticated and not request.user.is_superuser
                and request.user.role not in self.allowed_roles):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class StaffRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("owner", "staff")


class OwnerRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("owner",)
