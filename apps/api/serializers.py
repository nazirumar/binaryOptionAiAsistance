"""API serializers."""

from __future__ import annotations

from rest_framework import serializers

from apps.accounts.models import User


class UserSerializer(serializers.ModelSerializer):
    """Safe, read-only representation of the authenticated user."""

    class Meta:
        model = User
        fields = ("id", "username", "email", "display_name", "timezone", "preferred_theme")
        read_only_fields = fields


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    application = serializers.CharField()
    version = serializers.CharField()
    timestamp = serializers.DateTimeField()
    checks = serializers.DictField()
