# apps/trading_journal/views.py
"""Trading-journal API views (Phase 9, Step 16)."""

from __future__ import annotations

from rest_framework import status
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.api.pagination import StandardResultsSetPagination
from apps.trading_journal.models import JournalTrade
from apps.trading_journal.serializers import JournalTradeSerializer
from apps.trading_journal.services.journal_performance import JournalPerformance


class JournalBaseMixin:
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "journal"


class TradeListCreateView(JournalBaseMixin, ListCreateAPIView):
    """List the current user's trades or create a new one."""

    serializer_class = JournalTradeSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = JournalTrade.objects.filter(owner=self.request.user)
        trade_type = self.request.query_params.get("trade_type")
        if trade_type:
            queryset = queryset.filter(trade_type=trade_type)
        instrument = self.request.query_params.get("instrument")
        if instrument:
            queryset = queryset.filter(instrument__iexact=instrument)
        result = self.request.query_params.get("result")
        if result:
            queryset = queryset.filter(result=result)
        direction = self.request.query_params.get("direction")
        if direction:
            queryset = queryset.filter(direction=direction)
        return queryset

    def perform_create(self, serializer):  # type: ignore[no-untyped-def]
        serializer.save(owner=self.request.user)


class TradeDetailView(JournalBaseMixin, RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete one of the current user's trades."""

    serializer_class = JournalTradeSerializer

    def get_queryset(self):  # type: ignore[no-untyped-def]
        return JournalTrade.objects.filter(owner=self.request.user)


class PerformanceView(JournalBaseMixin, APIView):
    """Performance summary, always segmented by provenance.

    A single ``trade_type`` may be requested; otherwise every segment is
    returned separately so real and simulated results are never blended.
    """

    def get(self, request):  # type: ignore[no-untyped-def]
        queryset = JournalTrade.objects.filter(owner=request.user)
        performance = JournalPerformance(queryset)
        requested_type = request.query_params.get("trade_type")
        if requested_type:
            summary = performance.summary(requested_type)
            payload = {"trade_type": requested_type, "summary": summary.to_dict()}
        else:
            payload = {
                "segments": {
                    segment: summary.to_dict()
                    for segment, summary in performance.segmented_summary().items()
                }
            }
        return Response(payload, status=status.HTTP_200_OK)
