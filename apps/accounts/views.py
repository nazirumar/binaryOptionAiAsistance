"""Authentication views."""

from __future__ import annotations

from django.contrib.auth import login
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.urls import reverse_lazy
from django.views.generic.edit import CreateView

from apps.accounts.forms import SignUpForm, StyledAuthenticationForm
from apps.accounts.models import User


class LoginView(DjangoLoginView):
    template_name = "accounts/login.html"
    authentication_form = StyledAuthenticationForm
    redirect_authenticated_user = True


class SignUpView(CreateView):
    model = User
    form_class = SignUpForm
    template_name = "accounts/signup.html"
    success_url = reverse_lazy("dashboard:index")

    def form_valid(self, form):  # type: ignore[no-untyped-def]
        response = super().form_valid(form)
        login(self.request, self.object)
        return response
