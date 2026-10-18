"""Root URL configuration. See :mod:`config.settings.base` for routing intent."""

from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.core.views import HealthCheckView, HealthDetailView, home

urlpatterns = [
    path("", home, name="home"),
    path("healthz/", HealthCheckView.as_view(), name="healthz"),
    # Full operational diagnostics (staff only): database, cache, Celery
    # workers, MT5 worker heartbeat and market-data freshness.
    path("healthz/detail/", HealthDetailView.as_view(), name="healthz-detail"),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("api/", include("apps.api.urls")),
    path("api/market/", include("apps.market_data.urls")),
    path("api/vision/", include("apps.chart_vision.urls")),
    path("api/sync/", include("apps.market_sync.urls")),
    path("api/strategies/", include("apps.strategy_engine.urls")),
    path("api/research/", include("apps.research.urls")),
    path("api/assistant/", include("apps.ai_assistant.urls")),
    path("api/dashboard/", include("apps.dashboard.api_urls")),
    path("api/journal/", include("apps.trading_journal.urls")),
]

# API documentation (drf-spectacular).
if settings.API_DOCS_ENABLED:  # pragma: no cover - configuration dependent
    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
        path(
            "api/docs/",
            SpectacularSwaggerView.as_view(url_name="api-schema"),
            name="api-docs",
        ),
    ]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
