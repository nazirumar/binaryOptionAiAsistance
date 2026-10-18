# apps/research/views.py
"""Research APIs — datasets, backtests, performance, calibration, registry.

Every endpoint reads **persisted, owner-scoped** rows (Phase 11 CP3):

* the previous ``GET /backtests/<pk>/`` returned ``{"id": pk}`` for *any*
  id — now it 404s unless the run belongs to the caller;
* ``POST /backtests/`` queues the real ``run_backtest_task`` against an
  owned or shared dataset instead of a placeholder 202;
* performance numbers are the stored results of actual runs (with explicit
  "not_evaluated" accuracy statuses preserved) — nothing is computed into
  existence;
* calibration state is derived from persisted ``CalibratedModel`` evidence;
  an uncalibrated account reads exactly "unavailable_uncalibrated";
* the model registry exposes approval/calibration columns only — never
  ``model_data`` internals.
"""

from __future__ import annotations

from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.pagination import StandardResultsSetPagination
from apps.research import serializers
from apps.research.models import BacktestRun, CalibratedModel, HistoricalDataset
from apps.research.tasks import run_backtest_task


class ResearchBaseView(APIView):
    permission_classes = [IsAuthenticated]


class DatasetListView(ResearchBaseView):
    """Owner-scoped + shared (ownerless) historical datasets."""

    def get(self, request):
        datasets = HistoricalDataset.objects.filter(
            Q(owner=request.user) | Q(owner__isnull=True)
        ).order_by("-created_at")
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(datasets, request)
        serializer = serializers.HistoricalDatasetSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class DatasetDetailView(ResearchBaseView):
    def get(self, request, pk: int):
        dataset = HistoricalDataset.objects.filter(
            Q(owner=request.user) | Q(owner__isnull=True), pk=pk
        ).first()
        if dataset is None:
            return Response({"detail": "Not found"}, status=404)
        return Response(serializers.HistoricalDatasetSerializer(dataset).data)


class BacktestListView(ResearchBaseView):
    def get(self, request):
        runs = BacktestRun.objects.filter(owner=request.user).order_by("-created_at")
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(runs, request)
        serializer = serializers.BacktestRunSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        create = serializers.BacktestCreateSerializer(data=request.data)
        create.is_valid(raise_exception=True)
        data = create.validated_data

        # IDOR guard: only the caller's own or a shared (ownerless) dataset.
        dataset = HistoricalDataset.objects.filter(
            Q(owner=request.user) | Q(owner__isnull=True), pk=data["dataset_id"]
        ).first()
        if dataset is None:
            return Response({"detail": "Dataset not found."}, status=404)

        run = BacktestRun.objects.create(
            owner=request.user,
            dataset=dataset,
            name=data.get("name") or f"Backtest {dataset.name}",
            status="pending",
            strategy_config={
                "strategy": data.get("strategy", ""),
                "instrument": data.get("instrument") or dataset.instrument,
                "timeframe": data.get("timeframe") or dataset.timeframe,
            },
        )
        run_backtest_task.delay(run.pk)
        # Eager execution (dev/tests) may already have advanced the run;
        # report the actual persisted state, not the pre-dispatch snapshot.
        run.refresh_from_db()
        return Response(serializers.BacktestRunSerializer(run).data, status=202)


class BacktestDetailView(ResearchBaseView):
    def get(self, request, pk: int):
        run = BacktestRun.objects.filter(owner=request.user, pk=pk).first()
        if run is None:
            return Response({"detail": "Not found"}, status=404)
        return Response(serializers.BacktestRunSerializer(run).data)


class PerformanceView(ResearchBaseView):
    """Aggregate *stored* backtest outcomes for the caller.

    Only real rows are summarised: per-run metrics dicts (including honest
    ``accuracy_status`` values) and sample counts exactly as persisted by the
    backtest task. No synthetic totals, no invented win rates.
    """

    def get(self, request):
        runs = list(BacktestRun.objects.filter(owner=request.user).order_by("-created_at"))
        status_counts: dict[str, int] = {}
        for run in runs:
            status_counts[run.status] = status_counts.get(run.status, 0) + 1
        return Response(
            {
                "runs_total": len(runs),
                "status_counts": status_counts,
                "sample_counts": {str(run.pk): run.sample_count for run in runs},
                "metrics": {str(run.pk): run.metrics for run in runs},
            }
        )


class CalibrationView(ResearchBaseView):
    """Calibration state derived from persisted model evidence only."""

    def get(self, request):
        models = list(CalibratedModel.objects.filter(owner=request.user).order_by("-created_at"))
        approved = [m for m in models if m.is_approved and m.is_active]
        if not approved:
            return Response(
                {
                    "calibrated": False,
                    "status": "unavailable_uncalibrated",
                    "models_total": len(models),
                }
            )
        best = approved[0]
        return Response(
            {
                "calibrated": True,
                "status": "calibrated",
                "model_version": best.version,
                "calibration_method": best.calibration_method,
                "brier_score": best.brier_score,
                "calibration_error": best.calibration_error,
                "evaluation_metrics": best.evaluation_metrics,
                "models_total": len(models),
            }
        )


class ModelRegistryView(ResearchBaseView):
    def get(self, request):
        models = CalibratedModel.objects.filter(owner=request.user).order_by("-created_at")
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(models, request)
        serializer = serializers.CalibratedModelSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
