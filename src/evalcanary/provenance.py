"""Reproducibility and source-diff metadata."""

from __future__ import annotations

import difflib
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .io import sha256_file


def reproducible_now() -> datetime:
    source_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_epoch is not None:
        try:
            return datetime.fromtimestamp(int(source_epoch), tz=timezone.utc)
        except (ValueError, OSError):
            pass
    return datetime.now(tz=timezone.utc)


def make_run_id(data_path: Path, before_path: Path, after_path: Path) -> str:
    combined = (
        sha256_file(data_path)
        + sha256_file(before_path)
        + sha256_file(after_path)
    )
    return combined[:16]


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
        "data": {"path": str(data_path), "sha256": sha256_file(data_path)},
        "before_verifier": {
            "path": str(before_path),
            "sha256": sha256_file(before_path),
        },
        "after_verifier": {
            "path": str(after_path),
            "sha256": sha256_file(after_path),
        },
        "runtime": {
            "python": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "command": command or [],
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
