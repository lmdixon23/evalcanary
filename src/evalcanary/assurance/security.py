"""Privacy, safe-link, and bounded text utilities."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from typing import Any
from urllib.parse import unquote_to_bytes, urlsplit, urlunsplit

from .numeric import canonical_json_bytes

_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "proxy_authorization",
        "cookie",
        "set_cookie",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "client_secret",
        "password",
        "passwd",
        "private_key",
        "secret",
        "credential",
        "connection_string",
        "signed_url",
        "provider_request_id",
        "request_id",
        "tenant_id",
        "account_id",
    }
)
_SENSITIVE_SUFFIXES = (
    "_token",
    "_secret",
    "_password",
    "_credential",
    "_private_key",
)
_DNS_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_PERCENT = re.compile(r"%([0-9A-Fa-f]{2})")
_BAD_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")

_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?im)^(?:Authorization|Proxy-Authorization)\s*:\s*(?:Basic|Bearer)\s+[^\s]+"
        ),
        "[REDACTED_AUTH]",
    ),
    (
        re.compile(
            r"-----BEGIN [^-\r\n]*PRIVATE KEY-----[\s\S]*?-----END [^-\r\n]*PRIVATE KEY-----"
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\bgh[opusr]_[A-Za-z0-9_]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_API_KEY]"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
        "[REDACTED_JWT]",
    ),
    (
        re.compile(r"\b([A-Za-z][A-Za-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@"),
        r"\1[REDACTED_USERINFO]@",
    ),
    (
        re.compile(
            r"(?<![A-Za-z0-9_])(?:[A-Za-z]:\\[^\s\"'<>|]*|\\\\[^\s\"'<>|]+|/(?:[^\s\"'<>|/]+/)*[^\s\"'<>|/]*)"
        ),
        "[REDACTED_PATH]",
    ),
)
_QUERY_SECRET = re.compile(r"(?i)([?&])([A-Za-z0-9_-]+)=([^&#\s]*)")


def _normalized_key(key: str) -> str:
    return key.casefold().replace("-", "_")


def is_sensitive_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def redact_structured(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED_SECRET]"
                if is_sensitive_key(str(key))
                else redact_structured(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_structured(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(text: str) -> str:
    result = text
    for pattern, replacement in _TEXT_PATTERNS:
        result = pattern.sub(replacement, result)

    def replace_query(match: re.Match[str]) -> str:
        marker, key, raw_value = match.groups()
        value = "[REDACTED_SECRET]" if is_sensitive_key(key) else raw_value
        return f"{marker}{key}={value}"

    return _QUERY_SECRET.sub(replace_query, result)


def safe_reportable_url(value: str) -> str | None:
    """Validate without dereferencing and return a normalized public URL."""

    if not 1 <= len(value) <= 2048 or value != value.strip():
        return None
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return None
    if any(ord(character) <= 32 or ord(character) == 127 for character in value):
        return None
    if "\\" in value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return None
    if "@" in parsed.netloc or "%" in parsed.netloc or ":" in parsed.netloc:
        return None
    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if hostname is None or port is not None or parsed.username is not None:
        return None
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        return None
    if hostname.endswith(".") or len(hostname) > 253:
        return None
    labels = hostname.split(".")
    if len(labels) < 2 or any(_DNS_LABEL.fullmatch(label) is None for label in labels):
        return None
    lowered = hostname.casefold()
    if lowered == "localhost" or any(
        lowered.endswith(suffix)
        for suffix in (".localhost", ".local", ".internal", ".home", ".lan")
    ):
        return None
    if parsed.query or "?" in value or parsed.fragment or "#" in value:
        return None
    if parsed.path and not parsed.path.startswith("/"):
        return None
    if _BAD_PERCENT.search(parsed.path):
        return None
    try:
        decoded = unquote_to_bytes(parsed.path)
    except Exception:  # pragma: no cover - defensive standard-library boundary
        return None
    if any(byte <= 32 or byte == 127 or byte == 92 for byte in decoded):
        return None
    decoded_text = decoded.decode("utf-8", errors="ignore")
    if any(segment in {".", ".."} for segment in decoded_text.split("/")):
        return None
    authority = lowered
    return urlunsplit((parsed.scheme.casefold(), authority, parsed.path, "", ""))


def omission_facts(value: Any) -> dict[str, Any]:
    """Describe omitted source evidence without disclosing the value."""

    if value is None:
        return {"present": False, "omitted": False, "sha256": None}
    encoded = canonical_json_bytes(value)
    return {
        "present": True,
        "omitted": True,
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }
