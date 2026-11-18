from django.contrib.auth import logout
from django.shortcuts import redirect

from .two_factor import verified_session


class SuperuserTwoFactorMiddleware:
    """Fail closed if any authentication route creates an unverified superuser session."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (request.user.is_authenticated and request.user.is_superuser
                and not verified_session(request, request.user)):
            logout(request)
            return redirect("accounts:sign-in")
        return self.get_response(request)
