"""Input parsing and deterministic hashing utilities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .errors import InputValidationError
from .models import CaseRecord, Verdict


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON deterministically for hashes and provenance."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_cases(path: Path) -> list[CaseRecord]:
    """Load JSONL cases and enforce stable, unique string identifiers."""

    if not path.is_file():
        raise InputValidationError(f"Case file does not exist: {path}")

    cases: list[CaseRecord] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise InputValidationError(
                    f"Invalid JSON on line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(value, dict):
                raise InputValidationError(
                    f"Line {line_number} must contain a JSON object."
                )
            raw_id = value.get("id")
            if not isinstance(raw_id, (str, int)) or str(raw_id).strip() == "":
                raise InputValidationError(
                    f"Line {line_number} requires a non-empty string or integer 'id'."
                )
            case_id = str(raw_id)
            if case_id in seen:
                raise InputValidationError(f"Duplicate case id: {case_id}")
            seen.add(case_id)
            cases.append(CaseRecord(case_id=case_id, payload=value))

    if not cases:
        raise InputValidationError("Case file contains no evaluation cases.")
    return cases


def verdicts_to_jsonl(verdicts: Iterable[Verdict]) -> str:
    return "\n".join(
        json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True)
        for item in verdicts
    ) + "\n"
