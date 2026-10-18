"""Optional production observability wiring.

Sentry error tracking is configured through ``SENTRY_DSN`` and initialized
**only** by ``config.settings.prod``. The module deliberately imports nothing
beyond the standard library so it can be imported while Django settings are
still being evaluated.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def init_sentry(dsn: str, environment: str = "", release: str | None = None) -> bool:
    """Initialize the Sentry SDK when a DSN is configured.

    Returns ``True`` when the SDK was initialized, ``False`` when Sentry is
    disabled (empty/absent ``SENTRY_DSN``).

    Raises ``django.core.exceptions.ImproperlyConfigured`` when a DSN **is**
    set but ``sentry-sdk`` is not installed: silently dropping production error
    reports would be worse than refusing to boot, and the fix is unambiguous
    (install ``requirements/prod.txt`` or clear ``SENTRY_DSN``).

    Privacy posture: ``send_default_pii=False`` so request bodies, cookies and
    headers never leave the host, and ``traces_sample_rate=0.0`` so only errors
    are sampled unless that is deliberately changed in code.
    """
    if not dsn:
        logger.info("sentry disabled (SENTRY_DSN not set)")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
    except ImportError as exc:  # pragma: no cover - depends on prod extras
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            "SENTRY_DSN is set but sentry-sdk is not installed. "
            "Install requirements/prod.txt or clear SENTRY_DSN."
        ) from exc

    init_kwargs: dict[str, Any] = {
        "dsn": dsn,
        "integrations": [DjangoIntegration()],
        "traces_sample_rate": 0.0,
        "send_default_pii": False,
    }
    if environment:
        init_kwargs["environment"] = environment
    if release:
        init_kwargs["release"] = release

    sentry_sdk.init(**init_kwargs)
    logger.info("sentry initialized (environment=%s)", environment or "-")
    return True


__all__ = ["init_sentry"]
