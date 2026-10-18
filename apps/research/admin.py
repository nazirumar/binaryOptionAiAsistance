# apps/research/admin.py
from __future__ import annotations

from django.contrib import admin

from apps.research.models import (
    BacktestRun,
    CalibratedModel,
    HistoricalCandle,
    HistoricalDataset,
)

admin.site.register(HistoricalDataset)
admin.site.register(HistoricalCandle)
admin.site.register(BacktestRun)
admin.site.register(CalibratedModel)
