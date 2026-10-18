"""Account URLs: login, logout and sign-up."""

from __future__ import annotations

from django.contrib.auth import views as auth_views
from django.urls import path

from apps.accounts.views import LoginView, SignUpView

app_name = "accounts"

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", SignUpView.as_view(), name="signup"),
]
