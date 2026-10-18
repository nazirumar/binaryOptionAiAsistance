"""Shared test fixtures and factories."""

from __future__ import annotations

import factory
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

User = get_user_model()

TEST_PASSWORD = "test-pass-1234"


class UserFactory(factory.django.DjangoModelFactory):
    """Create a user with a known, already-hashed password."""

    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"analyst{n}")
    email = factory.LazyAttribute(lambda obj: f"{obj.username}@example.com")
    display_name = factory.LazyAttribute(lambda obj: obj.username.title())
    # Hash directly on the field to avoid post-generation save warnings.
    password = factory.LazyFunction(lambda: make_password(TEST_PASSWORD))
