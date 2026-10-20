"""Phase 16 Checkpoint 5 - signal timing analysis (real rows only)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from apps.live_signals.models import LiveSignal  # noqa: E402

SLA_SECONDS = 300  # >5 min after close is "late" for an M5 monitor poll of 15s


def main() -> int:
    rows = list(LiveSignal.objects.order_by("signal_candle_open_time"))
    print(f"total signals: {len(rows)}")
    print()
    print("candle_open            detected_at            latency_s   key")
    lats = []
    for s in rows:
        lat = (s.detected_at - s.signal_candle_close_time).total_seconds()
        lats.append(lat)
        flag = "  <-- LATE" if lat > SLA_SECONDS else ""
        print(f"{s.signal_candle_open_time}  {s.detected_at:%Y-%m-%d %H:%M:%S}  "
              f"{lat:10.1f}  {s.strategy_key}{flag}")
    if lats:
        print()
        print(f"latency  min={min(lats):.1f}s  median={median(lats):.1f}s  "
              f"mean={mean(lats):.1f}s  max={max(lats):.1f}s")
        late = [x for x in lats if x > SLA_SECONDS]
        print(f"late (>{SLA_SECONDS}s): {len(late)}/{len(lats)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
