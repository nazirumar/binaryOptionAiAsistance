# apps/strategy_engine/views.py
"""Strategy evaluation API views (Phase 6; completed in Phase 11 CP2).

The evaluate endpoint previously returned HTTP 501. It now runs the real
``EvaluationService`` on **server-derived** evidence:

* screenshot analyses and sync sessions are looked up by id **scoped to the
  requesting user** (404/403 otherwise);
* ``sync_status``, ``feed_compatibility``, ``data_freshness`` and
  ``market_type`` come from the owned ``MarketSyncSession`` row — never from
  the request body;
* client-supplied ``price_action_result`` is *ignored*: the price-action
  engine always runs over the candles, so evidence cannot be fabricated;
* client candles are a last resort (labelled unverified) and must carry
  timezone offsets — ambiguous timestamps are rejected, never shifted;
* the mandatory NO TRADE conditions in ``InvalidationEngine`` are enforced by
  the engine itself: without ``VERIFIED_ALIGNMENT`` the decision is
  NO TRADE, whatever the client claims.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.api.pagination import StandardResultsSetPagination
from apps.market_sync.constants import SyncStatus
from apps.strategy_engine import serializers
from apps.strategy_engine.exceptions import InvalidStrategyInputError
from apps.strategy_engine.models import StrategyEvaluation, StrategyRuleConfiguration
from apps.strategy_engine.services.evaluation_service import EvaluationService
from apps.strategy_engine.services.trusted_input_builder import (
    CandleValidationError,
    EvidenceNotFound,
    TrustedInputBuilder,
)


class StrategyBaseMixin:
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "sync_read"  # reuse existing scope; can be tuned later


class EvaluateAPIView(StrategyBaseMixin, APIView):
    """Evaluate a strategy setup and return UP/DOWN/NO_TRADE.

    Evidence is *referenced*, never asserted: any client fields resembling
    trusted verdicts (``sync_status`` and friends) are dropped by the
    serializer and re-derived server-side.
    """

    def post(self, request):
        serializer = serializers.StrategyEvaluateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            evidence = TrustedInputBuilder().build(
                owner=request.user,
                screenshot_analysis_id=data.get("screenshot_analysis_id"),
                sync_session_id=data.get("sync_session_id"),
                requested_instrument=data.get("instrument", ""),
                requested_timeframe=data.get("timeframe", ""),
                client_candles=data.get("candles") or None,
            )
        except EvidenceNotFound as exc:
            return Response(
                {"code": "evidence_not_found", "detail": str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )
        except PermissionDenied as exc:
            return Response(
                {"code": "forbidden", "detail": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except CandleValidationError as exc:
            return Response(
                {"code": "invalid_candles", "detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not evidence.input_data.get("completed_candles"):
            return Response(
                {
                    "code": "no_reference_candles",
                    "detail": (
                        "No stored MT5 candles and no client candles available for "
                        "this instrument/timeframe."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = EvaluationService()
        try:
            evaluation, _result = service.evaluate_and_persist(
                evidence.input_data, owner=request.user, now=data.get("now")
            )
        except InvalidStrategyInputError as exc:
            return Response(
                {"code": "invalid_strategy_input", "detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = serializers.StrategyEvaluationSerializer(evaluation).data
        payload["sync_evidence"] = {
            "sync_session_id": evidence.sync_session.pk if evidence.sync_session else None,
            "sync_status": evidence.sync_status,
            "verified": evidence.sync_status == SyncStatus.VERIFIED_ALIGNMENT,
            "candle_provenance": evidence.candle_provenance,
            "warnings": evidence.warnings,
        }
        return Response(payload, status=status.HTTP_201_CREATED)


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
    """Get the active strategy rule configuration (Phase 11 CP2).

    Returns the persisted ``StrategyRuleConfiguration`` rows — active ones
    when any exist, otherwise the most recent configuration. No fabricated
    probabilities are ever attached.
    """

    def get(self, request):
        active = StrategyRuleConfiguration.objects.filter(is_active=True).order_by(
            "-config_version", "-created_at"
        )
        configs = list(active)
        if not configs:
            configs = list(StrategyRuleConfiguration.objects.order_by("-created_at")[:1])
        rules = [
            {
                "name": c.name,
                "config_version": c.config_version,
                "rule_version": c.rule_version,
                "is_active": c.is_active,
                "description": c.description,
                "config": c.config,
            }
            for c in configs
        ]
        return Response(
            {
                "rules": rules,
                "note": "No fabricated probabilities. Probability status: unavailable_uncalibrated",
            }
        )
