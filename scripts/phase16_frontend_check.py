"""Phase 16 Checkpoint 6 - server-side frontend verification.

No desktop browser is connected to this session, so the browser-based checks
are reported as NOT TESTED. The strongest available evidence is exercised here:
real Django test-client rendering of every relevant page against real data,
checking HTTP status, key content, and basic accessibility markers.

Read-only: nothing is mutated.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402

PAGES = [
    ("live-signals dashboard", "/dashboard/live-signals/"),
    ("dashboard home", "/dashboard/"),
    ("screenshot cases", "/dashboard/screenshot-cases/"),
    ("screenshot case detail", "/dashboard/screenshot-cases/1/"),
]


def markers(html: str) -> dict:
    return {
        "lang": 'lang="en"' in html or "lang='en'" in html,
        "viewport": "viewport" in html,
        "h1": "<h1" in html,
        "skip_link": "skip" in html.lower(),
        "htmx": "hx-get" in html or "hx-post" in html or "htmx" in html,
        "nav_aria": 'aria-label' in html,
    }


def main() -> int:
    User = get_user_model()
    user = User.objects.filter(is_staff=True).first() or User.objects.first()
    if user is None:
        print("No user available to render pages as.")
        return 2
    print(f"rendering as user={user.pk} staff={user.is_staff} superuser={user.is_superuser}")

    client = Client()
    client.force_login(user)

    print()
    for label, url in PAGES:
        try:
            resp = client.get(url)
        except Exception as exc:
            print(f"  [ERR ] {label:26} {url} -> {exc}")
            continue
        html = resp.content.decode(errors="replace")
        m = markers(html)
        ok = resp.status_code == 200
        print(f"  [{'OK ' if ok else str(resp.status_code)}] {label:26} "
              f"{url:34} bytes={len(resp.content):>7}")
        print(f"         markers={m}")

    print()
    print("NOTE: real-browser checks (responsive layout, JS loading states, "
          "notification UX) are NOT TESTED - no browser is connected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
