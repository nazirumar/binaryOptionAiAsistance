# apps/strategy_engine/views.py
"""Strategy evaluation API views (Phase 6)."""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.api.pagination import StandardResultsSetPagination
from apps.strategy_engine import serializers
from apps.strategy_engine.models import StrategyEvaluation


class StrategyBaseMixin:
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "sync_read"  # reuse existing scope; can be tuned later


class EvaluateAPIView(StrategyBaseMixin, APIView):
    """Evaluate a strategy setup and return UP/DOWN/NO_TRADE."""

    def post(self, request):
        serializer = serializers.StrategyEvaluateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Evaluation service will be implemented next
        return Response(
            {"detail": "Evaluation service not yet implemented"},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )


class EvaluationDetailAPIView(StrategyBaseMixin, APIView):
    """Get a specific evaluation by ID."""

    def get(self, request, pk: int):
        try:
            evaluation = StrategyEvaluation.objects.get(pk=pk, owner=request.user)
        except StrategyEvaluation.DoesNotExist:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = serializers.StrategyEvaluationSerializer(evaluation)
        return Response(serializer.data)


class EvaluationHistoryAPIView(StrategyBaseMixin, APIView):
    """Get evaluation history for the current user."""

    def get(self, request):
        evaluations = StrategyEvaluation.objects.filter(owner=request.user).order_by("-created_at")
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(evaluations, request)
        serializer = serializers.StrategyEvaluationSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class StrategyRulesAPIView(StrategyBaseMixin, APIView):
    """Get current strategy rules configuration."""

    def get(self, request):
        return Response(
            {
                "rules": [],
                "note": "No fabricated probabilities. Probability status: unavailable_uncalibrated",
            }
        )
