"""Reproducibility and source-diff metadata."""

from __future__ import annotations

import difflib
import hashlib
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

from . import __version__
from .io import canonical_json_bytes, sha256_file

_PATH_FLAGS = {
    "--after",
    "--before",
    "--data",
    "--out",
    "--policy",
    "--python",
    "--verifier",
}


def reproducible_now() -> datetime:
    source_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_epoch is not None:
        try:
            return datetime.fromtimestamp(int(source_epoch), tz=timezone.utc)
        except (ValueError, OSError):
            pass
    return datetime.now(tz=timezone.utc)


def _safe_path_label(value: str | Path) -> str:
    """Return a basename without leaking an absolute or parent path."""

    raw = str(value)
    if "\\" in raw or (len(raw) >= 2 and raw[1] == ":"):
        label = PureWindowsPath(raw).name
    else:
        label = Path(raw).name
    return label or "<path>"


def sanitize_command(command: list[str]) -> list[str]:
    """Redact path-bearing CLI values while retaining command structure."""

    sanitized: list[str] = []
    redact_next = False
    for token in command:
        if redact_next:
            sanitized.append(_safe_path_label(token))
            redact_next = False
            continue
        sanitized.append(token)
        redact_next = token in _PATH_FLAGS
    return sanitized


def make_run_id(data_path: Path, before_path: Path, after_path: Path) -> str:
    """Return a stable ID derived from all three content identities."""

    identity = {
        "after_verifier_sha256": sha256_file(after_path),
        "before_verifier_sha256": sha256_file(before_path),
        "data_sha256": sha256_file(data_path),
    }
    return hashlib.sha256(canonical_json_bytes(identity)).hexdigest()[:16]


def build_provenance(
    data_path: Path,
    before_path: Path,
    after_path: Path,
    *,
    command: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "tool": "EvalCanary",
        "tool_version": __version__,
        "report_schema": "evalcanary-comparison-v1",
        "path_policy": "basename-only",
        "data": {
            "path": _safe_path_label(data_path),
            "sha256": sha256_file(data_path),
        },
        "before_verifier": {
            "path": _safe_path_label(before_path),
            "sha256": sha256_file(before_path),
        },
        "after_verifier": {
            "path": _safe_path_label(after_path),
            "sha256": sha256_file(after_path),
        },
        "runtime": {
            "python": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "command": sanitize_command(command or []),
    }


def unified_verifier_diff(
    before_path: Path, after_path: Path, *, max_lines: int = 400
) -> str:
    before_lines = before_path.read_text(
        encoding="utf-8-sig", errors="replace"
    ).splitlines()
    after_lines = after_path.read_text(
        encoding="utf-8-sig", errors="replace"
    ).splitlines()
    diff = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=before_path.name,
            tofile=after_path.name,
            lineterm="",
        )
    )
    if len(diff) > max_lines:
        omitted = len(diff) - max_lines
        diff = diff[:max_lines] + [
            f"... {omitted} additional diff lines omitted ..."
        ]
    return "\n".join(diff)
