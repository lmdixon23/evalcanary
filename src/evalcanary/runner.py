"""Subprocess execution for trusted Python verifiers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .errors import VerifierExecutionError
from .models import CaseRecord, Verdict


def run_verifier(
    verifier_path: Path,
    cases: list[CaseRecord],
    *,
    timeout_seconds: float,
    python_executable: str | None = None,
) -> list[Verdict]:
    """Execute one verifier against a fixed case list in a child process."""

    verifier_path = verifier_path.resolve()
    if not verifier_path.is_file():
        raise VerifierExecutionError(f"Verifier file does not exist: {verifier_path}")
    if timeout_seconds <= 0:
        raise VerifierExecutionError("Timeout must be greater than zero.")

    executable = python_executable or sys.executable
    worker_path = Path(__file__).with_name("worker.py").resolve()
    stdin_data = "".join(
        json.dumps(case.payload, ensure_ascii=False, sort_keys=True) + "\n"
        for case in cases
    )
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    env["TZ"] = "UTC"
    command = [
        executable,
        str(worker_path),
        "--verifier",
        str(verifier_path),
    ]
    try:
        completed = subprocess.run(
            command,
            input=stdin_data,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise VerifierExecutionError(
            f"Verifier exceeded the {timeout_seconds:g}-second run timeout: {verifier_path}"
        ) from exc
    except OSError as exc:
        raise VerifierExecutionError(
            f"Unable to start verifier subprocess with {executable}: {exc}"
        ) from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip() or "No stderr was produced."
        raise VerifierExecutionError(
            f"Verifier worker failed with exit code {completed.returncode}: {detail}"
        )

    raw_results: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(completed.stdout.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise VerifierExecutionError(
                f"Worker produced invalid JSON on output line {line_number}."
            ) from exc
        if not isinstance(value, dict):
            raise VerifierExecutionError("Worker output must contain JSON objects.")
        raw_results.append(value)

    if len(raw_results) != len(cases):
        raise VerifierExecutionError(
            "Verifier returned a different number of verdicts than input cases: "
            f"expected {len(cases)}, received {len(raw_results)}."
        )

    verdicts: list[Verdict] = []
    for case, value in zip(cases, raw_results, strict=True):
        case_id = str(value.get("case_id", ""))
        if case_id != case.case_id:
            raise VerifierExecutionError(
                f"Verifier result order or identity mismatch: expected {case.case_id}, received {case_id}."
            )
        passed = value.get("passed")
        if passed is not None and not isinstance(passed, bool):
            raise VerifierExecutionError(f"Invalid normalized verdict for case {case_id}.")
        score = value.get("score")
        verdicts.append(
            Verdict(
                case_id=case_id,
                passed=passed,
                score=float(score) if score is not None else None,
                reason=value.get("reason"),
                details=value.get("details"),
                error=value.get("error"),
                duration_ms=float(value["duration_ms"])
                if value.get("duration_ms") is not None
                else None,
            )
        )
    return verdicts
