# ai_assistant/services/safety_validator.py
"""Safety validation (Step 19).

Treats screenshot text and user-supplied content as untrusted input. Guards
against prompt injection and never allows external content to override system
instructions or strategy rules.
"""

from __future__ import annotations

INJECTION_PATTERNS = (
    "ignore previous instructions",
    "ignore all previous",
    "disregard prior",
    "system prompt",
    "you are now",
    "new instructions",
    "override the",
)


def is_prompt_injection(text: str) -> bool:
    lowered = (text or "").lower()
    return any(pattern in lowered for pattern in INJECTION_PATTERNS)


def sanitize_user_text(text: str, max_len: int = 4000) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    if is_prompt_injection(cleaned):
        return "[content filtered: potential prompt injection]"
    return cleaned


class SafetyValidator:
    def validate_user_message(self, text: str) -> dict[str, bool]:
        injection = is_prompt_injection(text)
        return {"ok": not injection, "flagged_injection": injection}

    def validate_screenshot_text(self, text: str) -> dict[str, bool]:
        injection = is_prompt_injection(text)
        return {"ok": not injection, "flagged_injection": injection}


__all__ = ["SafetyValidator", "is_prompt_injection", "sanitize_user_text"]
