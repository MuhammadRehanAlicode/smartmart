from django.contrib import messages
from django.contrib.auth import login
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView

from apps.core.audit import log_action

from apps.store.pending import complete_pending, is_ajax

from . import lockout

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
        if is_ajax(self.request):
            login(self.request, form.get_user())
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
