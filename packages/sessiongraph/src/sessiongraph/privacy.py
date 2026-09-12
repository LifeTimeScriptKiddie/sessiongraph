from __future__ import annotations

import hashlib
import json
import re
from typing import Any


PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("secret", re.compile(r"(?i)\b(?:api[_-]?key|token|secret|password|passwd)\s*[:=]\s*['\"]?[^\s'\"]+")),
    ("bearer", re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/-]+=*")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
)

SENSITIVE_KEYS = {
    "api_key", "apikey", "authorization", "access_token", "refresh_token", "id_token",
    "password", "passwd", "private_key", "secret", "secret_key", "client_secret",
    "token", "cookie", "set_cookie", "credential", "credentials",
}

SENSITIVE_KEY_SUFFIXES = (
    "_api_key", "_access_token", "_refresh_token", "_id_token", "_password", "_passwd",
    "_private_key", "_secret", "_secret_key", "_cookie", "_credential", "_credentials",
)


def redact(value: str) -> tuple[str, list[str]]:
    labels: list[str] = []
    result = value
    for label, pattern in PATTERNS:
        result, count = pattern.subn(f"<redacted:{label}>", result)
        if count:
            labels.extend([label] * count)
    return result, labels


def sanitize(value: Any) -> tuple[Any, list[str]]:
    """Recursively redact strings and values stored under sensitive keys."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        result: list[Any] = []
        labels: list[str] = []
        for item in value:
            safe, found = sanitize(item)
            result.append(safe)
            labels.extend(found)
        return result, labels
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        labels: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            normalized = re.sub(r"[^a-z0-9]+", "_", key_text.lower()).strip("_")
            if normalized in SENSITIVE_KEYS or normalized.endswith(SENSITIVE_KEY_SUFFIXES):
                result[key_text] = f"<redacted:{normalized}>"
                labels.append(normalized)
            else:
                result[key_text], found = sanitize(item)
                labels.extend(found)
        return result, labels
    return value, []


def canonicalize(value: Any) -> str:
    """Stable, redacted representation used for comparisons and never displayed."""
    if isinstance(value, str):
        value, _ = redact(value)
        value = re.sub(r"\b\d+\b", "<n>", value.lower())
        value = re.sub(r"\s+", " ", value).strip()
        return value
    if isinstance(value, dict):
        value, _ = sanitize(value)
        safe = {str(k): canonicalize(v) for k, v in sorted(value.items())}
        return json.dumps(safe, sort_keys=True, separators=(",", ":"))
    if isinstance(value, list):
        return json.dumps([canonicalize(v) for v in value], separators=(",", ":"))
    return json.dumps(value, sort_keys=True)


def fingerprint(*parts: Any) -> str:
    body = "\x1f".join(canonicalize(part) for part in parts)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
