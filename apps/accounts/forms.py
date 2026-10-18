"""Authentication forms with Tailwind-friendly widgets."""

from __future__ import annotations

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    UserCreationForm,
)

from apps.accounts.models import User, UserPreference
from apps.market_data.constants import Timeframe


class _TailwindFormMixin:
    """Apply consistent Tailwind classes to all widgets."""

    default_classes = (
        "block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm "
        "text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-indigo-500 "
        "focus:outline-none focus:ring-1 focus:ring-indigo-500 "
        "dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
    )

    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} {self.default_classes}".strip()


class StyledAuthenticationForm(_TailwindFormMixin, AuthenticationForm):
    pass


class SignUpForm(_TailwindFormMixin, UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")


class StyledPasswordChangeForm(_TailwindFormMixin, PasswordChangeForm):
    """Password change with the shared Tailwind widget styling."""


class ProfileForm(_TailwindFormMixin, forms.ModelForm):
    """Editable profile fields (non-sensitive)."""

    class Meta:
        model = User
        fields = ("display_name", "email", "timezone", "preferred_theme")


class PreferenceForm(_TailwindFormMixin, forms.ModelForm):
    """Analysis, screenshot and notification preferences."""

    class Meta:
        model = UserPreference
        fields = (
            "preferred_instrument",
            "preferred_timeframe",
            "market_type",
            "data_retention_days",
        )

    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.fields["preferred_timeframe"].choices = [("", "—"), *list(Timeframe.choices)]
