from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("login/", views.StoreLoginView.as_view(), name="login"),
    path("sign-in/", views.StoreLoginView.as_view(), name="sign-in"),
    path("2fa/setup/", views.two_factor_setup, name="2fa-setup"),
    path("2fa/challenge/", views.two_factor_challenge, name="2fa-challenge"),
    path("security/", views.security_settings, name="security-settings"),
    path("security/recovery-codes/saved/", views.accept_recovery_codes, name="accept-recovery-codes"),
    path("logout/", LogoutView.as_view(), name="logout"),  # POST only (Django 5)
    path("register/", views.RegisterView.as_view(), name="register"),
    path("redirect/", views.post_login, name="post-login"),
]
