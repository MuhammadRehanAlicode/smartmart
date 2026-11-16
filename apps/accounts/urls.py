from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("login/", views.StoreLoginView.as_view(), name="login"),
    path("sign-in/", views.StoreLoginView.as_view(), name="sign-in"),
    path("logout/", LogoutView.as_view(), name="logout"),  # POST only (Django 5)
    path("register/", views.RegisterView.as_view(), name="register"),
    path("redirect/", views.post_login, name="post-login"),
]
