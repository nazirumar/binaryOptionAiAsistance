"""Secret scanner used by Phase 10 audit (and CI)."""

from __future__ import annotations

import pathlib
import re
import sys

PATTERNS = {
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "OpenAI-style key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"ghp_[A-Za-z0-9]{36}"),
    "Slack token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    "hardcoded SECRET_KEY": re.compile(r"""SECRET_KEY\s*=\s*["'][A-Za-z0-9!@#$%^&*._-]{16,}["']"""),
}

# Files/dirs that legitimately contain placeholders or vendored deps.
EXCLUDE_DIRS = {
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".git",
    ".ruff_cache",
    ".pytest_cache",
    "staticfiles",
    "private_media",
    ".mypy_cache",
}
# Files allowed to contain marker strings (templates/docs with examples).
EXCLUDE_FILES = {".env.example"}

SCAN_EXTENSIONS = {
    ".py",
    ".html",
    ".js",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".cfg",
    ".ini",
    ".sh",
    ".ps1",
}

# Lines that are clearly placeholders rather than real secrets.
PLACEHOLDER_HINTS = (
    "placeholder",
    "example",
    "your-key",
    "your_key",
    "<your",
    "changeme",
    "change-me",
    "xxx",
    "...",
    "redacted",
)


def iter_files(root: pathlib.Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if path.name in EXCLUDE_FILES:
            continue
        if path.suffix.lower() not in SCAN_EXTENSIONS:
            continue
        yield path


def main() -> int:
    root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path.cwd()
    findings: list[str] = []
    for path in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line_no = text[: match.start()].count("\n") + 1
                snippet = match.group(0)
                line_text = text.splitlines()[line_no - 1].lower()
                if any(hint in line_text for hint in PLACEHOLDER_HINTS):
                    continue  # documented placeholder, not a live secret
                findings.append(f"{name}: {path}:{line_no}: {snippet[:12]}...")

    if findings:
        print("POSSIBLE SECRETS FOUND:")
        for item in findings:
            print("  " + item)
        return 1
    print("No possible secrets found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
