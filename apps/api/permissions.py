from rest_framework.permissions import SAFE_METHODS, BasePermission


def _role(request):
    u = request.user
    return u.role if u and u.is_authenticated else None


class IsOwner(BasePermission):
    def has_permission(self, request, view):
        return _role(request) == "owner"


class IsStaffOrOwner(BasePermission):
    def has_permission(self, request, view):
        return _role(request) in ("owner", "staff")


class IsCustomer(BasePermission):
    def has_permission(self, request, view):
        return _role(request) == "customer"


class IsAnyRole(BasePermission):
    def has_permission(self, request, view):
        return _role(request) in ("owner", "staff", "customer")


class OwnerWriteStaffRead(BasePermission):
    """Staff and owner may read; only the owner may change anything."""

    def has_permission(self, request, view):
        role = _role(request)
        if request.method in SAFE_METHODS:
            return role in ("owner", "staff")
        return role == "owner"
