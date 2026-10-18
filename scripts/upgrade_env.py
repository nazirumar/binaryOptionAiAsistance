"""Synchronise ``.env`` with ``.env.example`` — add keys that are missing.

The Phase 10 hardening added several settings to ``.env.example`` (Celery
reliability, throttle rates, transport security). Any of those absent from the
local ``.env`` falls back to a code default, which is usually correct but makes
the file misleading: an operator editing ``CELERY_TASK_SOFT_TIME_LIMIT`` in
``.env`` would have no effect because the key was never there.

This script appends the missing keys using the *example* value (a placeholder
or a documented default) and leaves every existing line byte-for-byte intact.

**Secrets never enter this script's output**: only key NAMES are printed,
never values. Existing values are preserved without being read into the report.

Usage:
    python scripts/upgrade_env.py            # apply (writes .env)
    python scripts/upgrade_env.py --check    # report only, exit 1 if behind
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

#: Matches a plain ``KEY=value`` line (both files use this form).
KEY_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _read_keys(path: Path) -> dict[str, str]:
    """Return ``{key: full_line}`` for each assignment line."""
    if not path.exists():
        return {}
    keys: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = KEY_LINE.match(line)
        if match:
            keys[match.group(1)] = line
    return keys


def _value_of(line: str) -> str:
    return line.split("=", 1)[1].strip().strip("\"'")


def _is_empty_value(line: str) -> bool:
    return _value_of(line) == ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env", help="local environment file")
    parser.add_argument("--example", default=".env.example", help="template file")
    parser.add_argument("--check", action="store_true", help="report only; do not write")
    args = parser.parse_args(argv)

    env_path = Path(args.env)
    example_path = Path(args.example)

    if not example_path.exists():
        print(f"ERROR: {example_path} not found.")
        return 2
    if not env_path.exists():
        print(f"ERROR: {env_path} not found. Copy {example_path} first.")
        return 2

    env_keys = _read_keys(env_path)
    example_keys = _read_keys(example_path)

    # Never overwrite an existing value — that is where the real secrets live.
    absent = [key for key in example_keys if key not in env_keys]

    # An empty template entry (``KEY=``) means "unconfigured: use the code
    # default". Writing ``KEY=`` into .env would *replace* that default with an
    # empty string, which is a behaviour change rather than a documentation
    # update — django-environ returns "" and does not fall back. Skip them.
    missing = [key for key in absent if not _is_empty_value(example_keys[key])]
    skipped_empty = [key for key in absent if _is_empty_value(example_keys[key])]
    # Keys in .env that no longer appear in the template (kept, just reported).
    orphaned = [key for key in env_keys if key not in example_keys]

    print(f"existing keys in {env_path}: {len(env_keys)}")
    print(f"keys in {example_path}:   {len(example_keys)}")
    print(f"missing keys to add:      {len(missing)}")
    print(f"empty-template keys skipped: {len(skipped_empty)}")

    if not missing:
        print(f"\n{env_path} is already in sync with {example_path}.")
    else:
        print("\nKeys to be added (names only; values are placeholders/defaults):")
        for key in sorted(missing):
            # Print the KEY only. The example value is a placeholder by
            # contract, but we never echo value material of any file here.
            print(f"  + {key}")
        if skipped_empty:
            print("\nIntentionally left unset (empty in the template => code default applies):")
            for key in sorted(skipped_empty):
                print(f"  - {key}")

    if orphaned:
        print(
            f"\nKeys present in {env_path} but absent from the template "
            f"(left untouched): {len(orphaned)}"
        )
        for key in sorted(orphaned):
            print(f"  * {key}")

    if args.check:
        return 1 if missing else 0

    if not missing:
        return 0

    existing = env_path.read_text(encoding="utf-8")
    if not existing.endswith("\n"):
        existing += "\n"
    block = [
        "",
        "# --- Added by scripts/upgrade_env.py (placeholders/defaults) ---",
    ]
    block.extend(example_keys[key] for key in sorted(missing))
    block.append("")
    env_path.write_text(existing + "\n".join(block), encoding="utf-8")
    print(f"\nWrote {len(missing)} new key(s) to {env_path}.")
    print("Review them: every added value is a placeholder or a default.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
