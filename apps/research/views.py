# apps/research/views.py
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class ResearchBaseView(APIView):
    permission_classes = [IsAuthenticated]


class BacktestListView(ResearchBaseView):
    def get(self, request):
        return Response({"results": []})

    def post(self, request):
        return Response({"detail": "Backtesting implemented incrementally"}, status=202)


class BacktestDetailView(ResearchBaseView):
    def get(self, request, pk: int):
        return Response({"id": pk})


class PerformanceView(ResearchBaseView):
    def get(self, request):
        return Response({"sample_counts": {}, "metrics": {}})


class CalibrationView(ResearchBaseView):
    def get(self, request):
        return Response({"calibrated": False, "status": "unavailable_uncalibrated"})


class ModelRegistryView(ResearchBaseView):
    def get(self, request):
        return Response({"models": []})
