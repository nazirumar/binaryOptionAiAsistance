"""API views."""

from __future__ import annotations

from django.db import connection
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.serializers import HealthSerializer, UserSerializer
from apps.core import __version__


class HealthAPIView(APIView):
    """Unauthenticated health endpoint for API clients and load balancers."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    serializer_class = HealthSerializer
    throttle_classes: list = []

    def get(self, request: Request) -> Response:
        healthy = True
        checks: dict = {}
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            checks["database"] = {"status": "ok", "vendor": connection.vendor}
        except Exception as exc:  # pragma: no cover - failure path
            healthy = False
            checks["database"] = {"status": "error", "error": type(exc).__name__}

        payload = {
            "status": "ok" if healthy else "degraded",
            "application": "nazbeen-academy-binary-ai",
            "version": __version__,
            "timestamp": timezone.now(),
            "checks": checks,
        }
        http_status = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(payload, status=http_status)


class MeView(APIView):
    """Return the authenticated user. Demonstrates the default auth policy."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)
