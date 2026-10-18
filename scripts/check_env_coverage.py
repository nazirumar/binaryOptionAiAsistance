"""Verify that every environment variable the project reads is actually wired up.

"Connected" means, for each variable name referenced anywhere in the project:

* ``code -> .env``           a supplier provides a value (``.env``, compose,
  entrypoint/backup shell scripts, GitHub Actions)
* ``code -> .env.example``   the template documents it, so the next machine
  inherits it
* ``.env -> code``           the value is consumed by something (not a dead knob)

Detection is done on the **AST**, never on raw text, so names that merely
appear inside docstrings, comments or pattern examples (``"KEY"``,
``"MY_SECRET"``) are not mistaken for reads:

* ``env("X")`` / ``env.bool("X", ...)`` / ``env.db("X", ...)``  — django-environ
* ``os.environ["X"]`` / ``os.environ.get("X")`` / ``os.getenv("X")``
* keys declared in the ``environ.Env(...)`` **scheme** count as having a
  default, even when the read itself passes no ``default=``
* ``${X}`` / ``$X`` / ``environment:`` entries in compose + shell scripts
* ``${{ secrets.X }}`` / ``${{ vars.X }}`` in GitHub workflows

Severity:

* ``MISSING-REQUIRED``  read with **no default** and no supplier anywhere ->
  the process raises at import time. Must never ship.
* ``UNDOCUMENTED``      referenced by code but absent from ``.env.example``.
* ``CONFIG-UNDOCUMENTED`` compose ``${KEY:?}``/``${KEY}`` reference that the
  template does not mention — an operator copying the template would hit a
  hard compose failure with no hint where the key came from.
* ``MISSING-OPTIONAL``  has a code default, but no supplier and no template
  entry — runs, yet the knob is undiscoverable.
* ``DEAD-IN-ENV``       present in ``.env`` but referenced by nothing.
* ``TEMPLATE-ONLY``     present in ``.env.example`` but referenced by nothing.
* ``UNQUOTED-DOLLAR``   an ``.env``/``.env.example`` value contains ``$...``
  without single quotes: django-environ keeps it literal but docker compose
  interpolates it to empty, so the container would run with a *different*
  secret than the host (found and fixed for ``DJANGO_SECRET_KEY``).
* ``COMPOSE-UNSET``     (informational) compose-required key absent from the
  local ``.env`` — ``docker compose up`` refuses until an operator fills it.

Exit code: 1 on any ``MISSING-REQUIRED`` or ``UNDOCUMENTED`` finding (or, with
``--strict``, on any finding at all), else 0.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Directories never worth parsing as project sources.
PYTHON_SKIP_DIRS = {".venv", "venv", "__pycache__", "node_modules", ".git", "staticfiles"}

#: ``os.environ`` / ``os.getenv`` reader names.
_OS_ENVIRON = "environ"
_OS_GETENV = "getenv"

#: Compose / shell variable reference: ``${KEY}`` or ``$KEY`` (``$$`` escaped).
DOLLAR = re.compile(r"(?<!\$)\$\{?([A-Z_][A-Z0-9_]*)\}?")

#: Compose interpolation with its modifier: ``${KEY:?required}``, ``${KEY:-x}``.
COMPOSE_VAR = re.compile(r"(?<!\$)\$\{([A-Za-z_][A-Za-z0-9_]*)([^}]*)\}")


def _name(node: ast.AST) -> str | None:
    """Dotted name of an expression, e.g. ``env.bool`` -> ``env.bool``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _const_str(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


class _EnvReader(ast.NodeVisitor):
    """Collect django-environ / os.environ reads and their required-ness."""

    def __init__(self) -> None:
        self.reads: set[str] = set()
        self.required: set[str] = set()
        self.scheme_keys: set[str] = set()

    # -- django-environ ----------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        func = _name(node.func) or ""
        head = func.split(".")[0]

        if func == "environ.Env":
            # Scheme constructor: ``Env(KEY=(type, default), ...)`` — must be
            # checked before the generic ``env.`` prefix branch below.
            self._visit_scheme(node)
        elif head == "env":
            # ``env("KEY", ...)`` and ``env.bool("KEY", ...)`` alike.
            self._visit_env_call(node, func)
        elif func in {f"os.{_OS_ENVIRON}.get", f"os.{_OS_GETENV}"}:
            self._visit_os_read(node, func)

        self.generic_visit(node)

    def _visit_env_call(self, node: ast.Call, func: str) -> None:
        # ``env("KEY", ...)`` / ``env.bool("KEY", ...)``: first positional arg.
        if not node.args:
            return
        key = _const_str(node.args[0])
        if key is None:
            return
        self.reads.add(key)
        has_default = any(arg.arg == "default" for arg in node.keywords) or len(node.args) > 1
        if not has_default:
            self.required.add(key)

    def _visit_os_read(self, node: ast.Call, func: str) -> None:
        if not node.args:
            return
        key = _const_str(node.args[0])
        if key is None:
            return
        self.reads.add(key)
        if func.endswith("getenv") or func.endswith(".get"):
            has_default = any(arg.arg == "default" for arg in node.keywords) or len(node.args) > 1
            if not has_default:
                self.required.add(key)
        # ``os.environ["X"]`` is handled in visit_Subscript; a bare
        # ``os.environ.get("X")`` without default is required.

    def _visit_scheme(self, node: ast.Call) -> None:
        """``environ.Env(KEY=(type, default), ...)`` — every key has a default."""
        for keyword in node.keywords:
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", keyword.arg or ""):
                self.scheme_keys.add(keyword.arg)

    # -- ``os.environ["X"]`` ----------------------------------------------
    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _name(node.value) in {f"os.{_OS_ENVIRON}", _OS_ENVIRON}:
            key = _const_str(node.slice)
            if key is not None:
                self.reads.add(key)
                self.required.add(key)
        self.generic_visit(node)


def scan_python(root: Path) -> tuple[set[str], set[str]]:
    """Return ``(all_keys, required_keys)`` referenced by Python sources."""
    reader = _EnvReader()
    for path in root.rglob("*.py"):
        if any(part in PYTHON_SKIP_DIRS for part in path.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (UnicodeDecodeError, SyntaxError, OSError):
            continue
        reader.visit(tree)

    # Scheme declarations provide defaults the read itself omits.
    required = reader.required - reader.scheme_keys
    return reader.reads, required


def scan_compose_consumers(root: Path) -> tuple[set[str], set[str]]:
    """Keys the compose files read *from* ``.env`` at interpolation time.

    Returns ``(required, optional)``:

    * ``${KEY}`` / ``${KEY:?msg}`` -> **required**: compose refuses (or warns
      and injects a blank) when the value is absent or empty, so the key must
      be documented in ``.env.example`` and filled before ``compose up``.
    * ``${KEY:-default}`` / ``${KEY-default}`` -> optional (default supplied).

    These are consumers, not suppliers: compose *reads* ``.env``, it does not
    provide values to it. Shell ``$VAR`` inside ``docker/*.sh`` is deliberately
    not scanned — those values are handed in by compose/Dockerfile env, whose
    ``.env`` interface is the compose layer itself.
    """
    required: set[str] = set()
    optional: set[str] = set()
    for path in [*root.glob("compose*.yaml"), *root.glob("compose*.yml")]:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in COMPOSE_VAR.finditer(text):
            key, modifier = match.group(1), (match.group(2) or "")
            if modifier.startswith(": -"):
                modifier = modifier[1:]
            if modifier.startswith(":-") or modifier.startswith("-"):
                optional.add(key)
            else:  # plain, ``:?``, ``:?error message``
                required.add(key)
    return required, optional


def scan_ci_secrets(root: Path) -> set[str]:
    """``${{ secrets.X }}`` / ``${{ vars.X }}`` supplied by GitHub Actions."""
    supplied: set[str] = set()
    for path in [
        *root.glob(".github/workflows/*.yml"),
        *root.glob(".github/workflows/*.yaml"),
    ]:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        supplied.update(re.findall(r"\$\{\{\s*(?:secrets|vars)\.([A-Z0-9_]+)\s*\}\}", text))
    return supplied


def scan_config_files(root: Path) -> set[str]:
    """Every key referenced by any config file (dead-knob checks need this)."""
    supplied: set[str] = set()
    required, optional = scan_compose_consumers(root)
    supplied |= required | optional
    supplied |= scan_ci_secrets(root)
    for path in [*root.glob("docker/*.sh"), *root.glob("scripts/*.sh")]:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        supplied.update(DOLLAR.findall(text))
    return supplied


def read_env_keys(path: Path) -> set[str]:
    return set(read_env_pairs(path))


def read_env_pairs(path: Path) -> dict[str, str]:
    """``{key: value}`` for assignment lines.

    Values are used **only** for empty/non-empty classification inside this
    script and are never printed anywhere in the report.
    """
    if not path.exists():
        return {}
    pairs: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if match:
            pairs[match.group(1)] = match.group(2).strip()
    return pairs


def unquoted_dollar_keys(path: Path) -> list[str]:
    """Keys whose value contains ``$`` without protective single quotes.

    django-environ keeps such values byte-for-byte, but docker compose runs
    dotenv interpolation over ``.env`` and replaces ``$name`` with an empty
    string — the host and the container would silently disagree (e.g. two
    different ``DJANGO_SECRET_KEY`` values). Single quotes are literal in
    *both* parsers (verified), so quoting is the fix.
    """
    if not path.exists():
        return []
    keys: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value.startswith("'"):
            continue
        if "$" in value:
            keys.append(key.strip())
    return sorted(keys)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT), help="project root")
    parser.add_argument("--strict", action="store_true", help="fail on any finding")
    args = parser.parse_args(argv)

    root = Path(args.root)
    code_keys, required_keys = scan_python(root)
    config_keys = scan_config_files(root)  # every config reference (dead-knob checks)
    compose_required, compose_optional = scan_compose_consumers(root)
    ci_secrets = scan_ci_secrets(root)
    env_keys = read_env_keys(root / ".env")
    example_keys = read_env_keys(root / ".env.example")

    # Python reads get their value from `.env` or from GitHub Actions at deploy
    # time; compose consumes from `.env` but never provides values to it.
    suppliers = env_keys | ci_secrets

    missing_required = sorted(required_keys - suppliers)
    undocumented = sorted(code_keys - example_keys)
    # Compose `:?`/plain refs that the template does not mention at all: an
    # operator copying `.env.example` would hit a hard compose failure with no
    # hint where the key came from.
    config_undocumented = sorted(compose_required - example_keys)
    # Documented in the template but deliberately not overridden in `.env`
    # (template value empty -> "use the code default"). Expected, informational.
    documented_unset = sorted((code_keys - suppliers) & example_keys)
    missing_optional = sorted((code_keys - suppliers) - example_keys - set(missing_required))
    # Compose-required keys absent from `.env` **or present but empty** —
    # `${KEY:?}` fails on empty too, so `docker compose up` refuses until an
    # operator fills them. Expected for deployment-specific values (dev leaves
    # DATABASE_URL/REDIS_URL empty on purpose), but it must be visible here.
    env_pairs = read_env_pairs(root / ".env")
    compose_unset = sorted(
        key for key in compose_required if env_pairs.get(key, "").strip().strip("\"'") == ""
    )
    dead_env = sorted(env_keys - code_keys - config_keys)
    template_only = sorted(example_keys - code_keys - config_keys - compose_optional)
    # `$...` values that compose would interpolate but the app would not.
    dollar_keys = sorted(
        set(unquoted_dollar_keys(root / ".env")) | set(unquoted_dollar_keys(root / ".env.example"))
    )

    print("=== .env connectivity report ===")
    print(f"keys read by code:             {len(code_keys)}")
    print(f"keys read with no default:     {len(required_keys)}")
    print(f"compose required / optional:    {len(compose_required)} / {len(compose_optional)}")
    print(f"keys in .env:                  {len(env_keys)}")
    print(f"keys in .env.example:          {len(example_keys)}")

    def _section(title: str, keys: list[str], note: str) -> None:
        print(f"\n[{title}] {len(keys)} - {note}")
        for key in keys:
            print(f"  {key}")

    _section("MISSING-REQUIRED", missing_required, "no default and supplied nowhere")
    _section("UNDOCUMENTED", undocumented, "read by code but absent from .env.example")
    _section("CONFIG-UNDOCUMENTED", config_undocumented, "compose-required but not in template")
    _section("MISSING-OPTIONAL", missing_optional, "neither supplied nor documented")
    _section("DEAD-IN-ENV", dead_env, "in .env but referenced nowhere (informational)")
    _section("TEMPLATE-ONLY", template_only, "in .env.example but referenced nowhere")
    _section(
        "UNQUOTED-DOLLAR",
        dollar_keys,
        "value contains $ without single quotes -> compose would corrupt it",
    )
    _section(
        "DEFAULT-OR-UNSET",
        documented_unset,
        "documented in template, not overridden in .env -> code default applies",
    )
    _section(
        "COMPOSE-UNSET",
        compose_unset,
        "compose-required, not in .env -> `compose up` refuses until set",
    )

    hard_fail = bool(missing_required or undocumented or config_undocumented or dollar_keys)
    soft_fail = bool(missing_optional or dead_env or template_only or compose_unset)
    if hard_fail:
        print("\nRESULT: FAIL - required wiring is missing.")
        return 1
    if soft_fail and args.strict:
        print("\nRESULT: FAIL (strict) - informational findings present.")
        return 1
    print("\nRESULT: OK - every variable the code reads has a supplier.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
