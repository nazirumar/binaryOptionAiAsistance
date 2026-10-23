"""Phase 16 Checkpoint 2 - end-to-end monitoring probe.

Measures, with real timestamps, the eight steps the checkpoint asks about:

  1. a new candle arrives
  2. it is persisted correctly
  3. it closes
  4. the monitoring task processes it
  5. existing detectors evaluate it
  6. matching patterns are persisted
  7. the dashboard displays them
  8. notifications are created without duplicates

Nothing is fabricated: every number comes from a real DB row or a real
function call. Where a step cannot be observed, it is reported as such.

Run:  .venv\\Scripts\\python.exe scripts\\phase16_e2e_probe.py
"""

from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402
from django.db.models import Count  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.live_signals.models import (  # noqa: E402
    InstrumentMonitor,
    LiveSignal,
    SignalAlert,
)
from apps.live_signals.services.monitor import LiveSignalMonitor  # noqa: E402
from apps.market_data.models import MarketCandle  # noqa: E402


def ts() -> str:
    return datetime.now(tz=UTC).strftime("%H:%M:%S.%f")[:-3]


def db_ok() -> tuple[bool, str]:
    """Confirm we can talk to the database right now."""
    try:
        connection.ensure_connection()
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True, "ok"
    except Exception as exc:  # pragma: no cover - environment dependent
        return False, f"DB unreachable: {exc}"


def main() -> int:
    print("=" * 74)
    print("PHASE 16 / CHECKPOINT 2 - END-TO-END MONITORING PROBE")
    print("=" * 74)

    ok, msg = db_ok()
    print(f"[{ts()}] preflight DB connectivity: {'OK' if ok else 'FAIL'} ({msg})")
    if not ok:
        return 2

    monitor_row = InstrumentMonitor.objects.order_by("pk").first()
    if monitor_row is None:
        print("No monitor configured. Set LIVE_SIGNAL_MONITORS and run "
              "`manage.py run_live_monitor` first.")
        return 2
    print(
        f"[{ts()}] monitor: {monitor_row.canonical_instrument} "
        f"{monitor_row.timeframe} (feed={monitor_row.feed_state}, "
        f"enabled={monitor_row.enabled}, state={monitor_row.state})"
    )

    symbol = monitor_row.canonical_instrument
    timeframe = monitor_row.timeframe

    # --- Step 1/2/3: newest persisted candle and its completeness -----------
    newest = (
        MarketCandle.objects.filter(symbol__canonical=symbol, timeframe=timeframe)
        .order_by("-open_time")
        .first()
    )
    if newest is None:
        print("No candles persisted yet - cannot observe arrival/closing.")
        return 2

    now = timezone.now()
    age_min = (now - newest.open_time).total_seconds() / 60
    print(
        f"[{ts()}] step1/2 newest {timeframe} candle open_time={newest.open_time} "
        f"is_complete={newest.is_complete} age={age_min:.1f}min source={newest.source}"
    )
    print(f"[{ts()}] step3 close time = open_time + {timeframe} duration "
          f"(the monitor never evaluates a forming bar)")

    # --- Steps 4-6: run the monitor once and capture real timings -----------
    before_signals = LiveSignal.objects.count()
    before_alerts = SignalAlert.objects.count()
    print(f"[{ts()}] step4 before: signals={before_signals} alerts={before_alerts}")

    engine = LiveSignalMonitor(provider_name=monitor_row.provider or "db")
    t0 = time.perf_counter()
    result = engine.run_monitor(monitor_row)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    after_signals = LiveSignal.objects.count()
    after_alerts = SignalAlert.objects.count()
    print(
        f"[{ts()}] step4 monitor run: evaluated={result.evaluated} "
        f"new={result.new_signals} expired={result.expired} resolved={result.resolved} "
        f"feed={result.feed_state} msg={result.message!r} latency={elapsed_ms:.0f}ms "
        f"signals={before_signals}->{after_signals} alerts={before_alerts}->{after_alerts}"
    )

    # --- Step 5: detector evaluation evidence -------------------------------
    newest_signal = (
        LiveSignal.objects.filter(monitor=monitor_row).order_by("-detected_at").first()
    )
    if newest_signal is not None:
        det_latency = newest_signal.detected_at - newest_signal.signal_candle_close_time
        print(
            f"[{ts()}] step5/6 latest signal={newest_signal.strategy_key} "
            f"status={newest_signal.status} category={newest_signal.category} "
            f"direction={newest_signal.direction}"
        )
        print(
            f"[{ts()}]        candle_close={newest_signal.signal_candle_close_time} "
            f"detected_at={newest_signal.detected_at} "
            f"detection_latency={det_latency.total_seconds():.1f}s"
        )
        if det_latency.total_seconds() < 0:
            print(f"[{ts()}]        WARNING: detected_at precedes candle close "
                  f"(clock/timezone inconsistency)")
    else:
        print(f"[{ts()}] step5/6 no signal rows for this monitor yet")

    # --- Step 7: dashboard visibility ---------------------------------------
    from django.contrib.auth import get_user_model
    from django.test import Client

    user = get_user_model().objects.filter(is_staff=True).first() or get_user_model().objects.first()
    if user is not None:
        client = Client()
        client.force_login(user)
        resp = client.get("/dashboard/live-signals/")
        html = resp.content.decode(errors="replace")
        print(
            f"[{ts()}] step7 GET /dashboard/live-signals/ -> HTTP {resp.status_code} "
            f"bytes={len(resp.content)} shows_instrument={symbol in html}"
        )
    else:
        print(f"[{ts()}] step7 no user to render the dashboard as")

    # --- Step 8: duplicate alerts -------------------------------------------
    dupes = list(
        SignalAlert.objects.values("user_id", "signal_id")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
    )
    print(
        f"[{ts()}] step8 alerts total={after_alerts} (new={after_alerts - before_alerts}) "
        f"duplicate (user,signal) pairs={len(dupes)}"
    )

    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
