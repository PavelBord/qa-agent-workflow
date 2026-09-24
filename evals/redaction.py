"""Redact credentials and personal data before logging or persistence."""

from __future__ import annotations

import re


_EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Z0-9._~+/=-]+")
_KEY_VALUE_RE = re.compile(
    r"(?i)(\b(?:password|passwd|pwd|token|api[_-]?key|api[_-]?token|"
    r"access[_-]?token|refresh[_-]?token|client[_-]?secret|secret|"
    r"authorization|cookie)\b\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_URL_SECRET_RE = re.compile(
    r"(?i)([?&](?:token|code|key|secret|signature|password|auth)="
    r")[^&#\s]+"
)


def mask_sensitive(value: object) -> str:
    """Return a safe, human-readable representation with sensitive values hidden."""

    text = str(value)
    text = _BEARER_RE.sub("Bearer [MASKED]", text)
    text = _KEY_VALUE_RE.sub(r"\1[MASKED]", text)
    text = _URL_SECRET_RE.sub(r"\1[MASKED]", text)
    text = _EMAIL_RE.sub("[EMAIL_MASKED]", text)
    return text


def mask_object(value: object) -> object:
    """Recursively redact strings in JSON-compatible data."""

    if isinstance(value, str):
        return mask_sensitive(value)
    if isinstance(value, list):
        return [mask_object(item) for item in value]
    if isinstance(value, dict):
        return {key: mask_object(item) for key, item in value.items()}
    return value
