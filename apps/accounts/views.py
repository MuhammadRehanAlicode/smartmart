from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView
from django.utils import timezone

from apps.core.audit import log_action

from apps.store.pending import complete_pending, is_ajax

from . import lockout
from . import two_factor

from .forms import CustomerRegistrationForm, LoginForm, StaffCreateForm, StaffEditForm
from .models import User
from .permissions import OwnerRequiredMixin


def _errors(form):
    """Field errors as JSON-friendly {field: [messages]} (form-level errors under "__all__")."""
    return {k: [str(e) for e in v] for k, v in form.errors.items()}


class StoreLoginView(LoginView):
    template_name = "auth/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get(self, request, *args, **kwargs):
        # Keep direct visits to sign-in URLs on the public storefront. The
        # storefront's login modal submits credentials to this view with POST.
        return redirect("store:home")

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "")
        if lockout.is_locked(request, username):
            form = self.get_form()
            form.full_clean()
            form.add_error(None, "Too many failed attempts. Please wait 15 minutes and try again.")
            if is_ajax(request):
                return JsonResponse({"ok": False, "errors": _errors(form)}, status=429)
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        lockout.clear(self.request, self.request.POST.get("username", ""))
        user = form.get_user()
        if user.is_superuser:
            two_factor.set_preauth(self.request, user)
            destination = "accounts:2fa-setup" if not user.totp_confirmed_at else "accounts:2fa-challenge"
            if is_ajax(self.request):
                return JsonResponse({"ok": True, "requires_2fa": True, "redirect": str(reverse_lazy(destination))})
            return redirect(destination)
        if is_ajax(self.request):
            login(self.request, user)
            complete_pending(self.request)
            redirect_to = reverse_lazy("dashboard:home") if self.request.user.is_store_staff else None
            return JsonResponse({"ok": True, "redirect": str(redirect_to) if redirect_to else None})
        response = super().form_valid(form)
        complete_pending(self.request)
        return response

    def get_success_url(self):
        # Send store owners and staff to the back office after sign-in, even if
        # the login form included a storefront `next` URL.
        if self.request.user.is_store_staff:
            return str(reverse_lazy("dashboard:home"))
        return super().get_success_url()

    def form_invalid(self, form):
        lockout.register_failure(self.request, self.request.POST.get("username", ""))
        if is_ajax(self.request):
            return JsonResponse({"ok": False, "errors": _errors(form)}, status=400)
        return super().form_invalid(form)


def _preauth_user(request):
    user = two_factor.get_preauth_user(request)
    if not user:
        return None
    return user


def _render_2fa(request, template, context=None, status=200):
    response = render(request, template, context or {}, status=status)
    response["Cache-Control"] = "no-store, private"
    # `no-referrer` makes Chrome send `Origin: null` for same-origin form POSTs,
    # which Django correctly rejects. Keep full referrers within this origin
    # (needed by CSRF) and suppress referrers to other origins.
    response["Referrer-Policy"] = "same-origin"
    return response


def two_factor_setup(request):
    user = _preauth_user(request)
    if not user:
        return redirect("accounts:sign-in")
    if user.totp_confirmed_at:
        return redirect("accounts:2fa-challenge")
    if not user.totp_secret_encrypted:
        secret = two_factor.new_secret()
        user.totp_secret_encrypted = two_factor.encrypt_secret(secret)
        user.save(update_fields=["totp_secret_encrypted"])
    secret = two_factor.decrypt_secret(user.totp_secret_encrypted)
    uri = two_factor.provisioning_uri(user, secret)
    if request.method == "POST":
        if two_factor.is_rate_limited(user.pk):
            return _render_2fa(request, "auth/2fa_setup.html", {"manual_key": secret, "qr_code": two_factor.qr_data_uri(uri), "error": "Too many attempts. Try again in 15 minutes."}, 429)
        step = two_factor.matching_totp_step(secret, request.POST.get("code"))
        if step is None:
            two_factor.record_failure(user.pk)
            return _render_2fa(request, "auth/2fa_setup.html", {"manual_key": secret, "qr_code": two_factor.qr_data_uri(uri), "error": "That code could not be verified. Check your device time and try again."}, 400)
        if user.totp_last_step is not None and step <= user.totp_last_step:
            return _render_2fa(request, "auth/2fa_setup.html", {"manual_key": secret, "qr_code": two_factor.qr_data_uri(uri), "error": "This code was already used. Enter the next code."}, 400)
        display_codes, hashes = two_factor.generate_recovery_codes()
        user.totp_confirmed_at = timezone.now()
        user.totp_last_step = step
        user.totp_last_verified_at = timezone.now()
        user.recovery_code_hashes = hashes
        user.save(update_fields=["totp_confirmed_at", "totp_last_step", "totp_last_verified_at", "recovery_code_hashes"])
        two_factor.clear_failures(user.pk)
        two_factor.complete_login(request, user)
        log_action(user, "security.2fa_enabled", user.username)
        return _render_2fa(request, "auth/2fa_recovery_codes.html", {"codes": display_codes, "first_setup": True})
    return _render_2fa(request, "auth/2fa_setup.html", {"manual_key": secret, "qr_code": two_factor.qr_data_uri(uri)})


def two_factor_challenge(request):
    user = _preauth_user(request)
    if not user:
        return redirect("accounts:sign-in")
    if not user.totp_confirmed_at:
        return redirect("accounts:2fa-setup")
    error = ""
    status = 200
    if request.method == "POST":
        if two_factor.is_rate_limited(user.pk):
            error, status = "Too many attempts. Try again in 15 minutes.", 429
        else:
            method = two_factor.verify_and_consume(user, request.POST.get("code"))
            if method:
                two_factor.complete_login(request, user)
                log_action(user, "security.2fa_verified", user.username, method=method)
                complete_pending(request)
                return redirect("dashboard:home")
            error, status = "The verification code is invalid or has already been used.", 400
    return _render_2fa(request, "auth/2fa_challenge.html", {"error": error}, status)


@login_required
def security_settings(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    user = request.user
    codes = None
    error = ""
    if request.method == "POST":
        action = request.POST.get("action")
        password = request.POST.get("password", "")
        code = request.POST.get("code", "")
        if two_factor.is_rate_limited(user.pk):
            error = "Too many verification attempts. Try again in 15 minutes."
        elif not check_password(password, user.password):
            error = "Password confirmation failed."
        elif not two_factor.verify_and_consume(user, code):
            error = "Enter a valid unused authenticator or recovery code."
        elif action == "regenerate":
            codes, hashes = two_factor.generate_recovery_codes()
            user.recovery_code_hashes = hashes
            user.save(update_fields=["recovery_code_hashes"])
            log_action(user, "security.recovery_codes_regenerated", user.username)
        elif action == "disable":
            user.totp_secret_encrypted = ""
            user.totp_confirmed_at = None
            user.totp_last_step = None
            user.totp_last_verified_at = None
            user.recovery_code_hashes = []
            user.save(update_fields=["totp_secret_encrypted", "totp_confirmed_at", "totp_last_step", "totp_last_verified_at", "recovery_code_hashes"])
            request.session.pop(two_factor.VERIFIED_SESSION_KEY, None)
            log_action(user, "security.2fa_disabled", user.username)
            from django.contrib.auth import logout
            logout(request)
            messages.success(request, "Two-factor authentication has been disabled. Sign in again to set it up.")
            return redirect("accounts:sign-in")
        user.refresh_from_db()
    response = render(request, "auth/security_settings.html", {"codes": codes, "error": error, "remaining_codes": len(user.recovery_code_hashes or [])})
    response["Cache-Control"] = "no-store, private"
    response["Referrer-Policy"] = "same-origin"
    return response


@login_required
def accept_recovery_codes(request):
    if request.method != "POST":
        return redirect("accounts:security-settings")
    return redirect("accounts:post-login")


@login_required
def post_login(request):
    """Send each role to its own home after login."""
    if request.user.is_store_staff:
        return redirect("dashboard:home")
    return redirect("store:home")


class RegisterView(CreateView):
    form_class = CustomerRegistrationForm
    template_name = "auth/register.html"
    success_url = reverse_lazy("store:home")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("accounts:post-login")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        messages.success(self.request, "Welcome! Your account has been created.")
        complete_pending(self.request)
        if is_ajax(self.request):
            return JsonResponse({"ok": True, "redirect": None})
        return response

    def form_invalid(self, form):
        if is_ajax(self.request):
            return JsonResponse({"ok": False, "errors": _errors(form)}, status=400)
        return super().form_invalid(form)


class StaffListView(OwnerRequiredMixin, ListView):
    template_name = "dashboard/staff_list.html"
    context_object_name = "staff_members"

    def get_queryset(self):
        return User.objects.filter(role=User.Role.STAFF).order_by("first_name", "username")


class StaffCreateView(OwnerRequiredMixin, CreateView):
    form_class = StaffCreateForm
    template_name = "dashboard/staff_form.html"
    success_url = reverse_lazy("dashboard:staff-list")

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(self.request.user, "staff.created", self.object.username)
        messages.success(self.request, f"Staff account '{self.object.username}' created.")
        return response


class StaffEditView(OwnerRequiredMixin, UpdateView):
    model = User
    form_class = StaffEditForm
    template_name = "dashboard/staff_edit.html"
    success_url = reverse_lazy("dashboard:staff-list")

    def get_queryset(self):
        return User.objects.filter(role=User.Role.STAFF)

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(self.request.user, "staff.updated", self.object.username, duty=self.object.duty)
        messages.success(self.request, f"Staff details for '{self.object.username}' updated.")
        return response
