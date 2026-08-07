"""Trusted-verifier subprocess worker.

The worker deliberately has a tiny protocol: load one Python file, require a
``verify(case)`` function, read JSON objects from stdin, and emit one normalized
JSON verdict per line. It is process isolation, not a security sandbox. Only run
verifier code you trust.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import inspect
import io
import json
import math
import sys
import time
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("evalcanary_user_verifier", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load verifier module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_verify(path: Path) -> Callable[[dict[str, Any]], Any]:
    module = _load_module(path)
    verify = getattr(module, "verify", None)
    if not callable(verify):
        raise RuntimeError("Verifier must define callable verify(case).")
    if inspect.iscoroutinefunction(verify):
        raise RuntimeError("Async verifier functions are not supported in v0.1.")
    return verify


def _normalize(case_id: str, value: Any, duration_ms: float) -> dict[str, Any]:
    if isinstance(value, bool):
        return {
            "case_id": case_id,
            "passed": value,
            "score": 1.0 if value else 0.0,
            "reason": None,
            "details": None,
            "error": None,
            "duration_ms": duration_ms,
        }
    if not isinstance(value, dict):
        raise TypeError("verify(case) must return bool or a JSON-serializable dict.")
    passed = value.get("passed")
    if not isinstance(passed, bool):
        raise TypeError("Verifier dict result requires boolean 'passed'.")
    score = value.get("score")
    if score is not None:
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise TypeError("Verifier 'score' must be numeric when provided.")
        score = float(score)
        if not math.isfinite(score):
            raise TypeError("Verifier 'score' must be finite when provided.")
    reason = value.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise TypeError("Verifier 'reason' must be a string when provided.")
    details = value.get("details")
    details = json.loads(json.dumps(details, ensure_ascii=False, allow_nan=False))
    return {
        "case_id": case_id,
        "passed": passed,
        "score": score,
        "reason": reason,
        "details": details,
        "error": None,
        "duration_ms": duration_ms,
    }


def _captured_call(function: Callable[[], Any]) -> Any:
    """Protect the JSONL protocol from verifier stdout and stderr writes."""

    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
        return function()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--verifier", required=True)
    args = parser.parse_args(argv)
    verifier_path = Path(args.verifier).resolve()

    try:
        verify = _captured_call(lambda: _load_verify(verifier_path))
    except Exception as exc:  # pragma: no cover
        print(f"WORKER_STARTUP_ERROR: {exc}", file=sys.stderr)
        return 10

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        case_id = "<unknown>"
        started = time.perf_counter()
        try:
            case = json.loads(line)
            if not isinstance(case, dict):
                raise TypeError("Worker input must be a JSON object.")
            case_id = str(case["id"])
            raw_result = _captured_call(lambda: verify(case))
            duration_ms = (time.perf_counter() - started) * 1000.0
            result = _normalize(case_id, raw_result, duration_ms)
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000.0
            result = {
                "case_id": case_id,
                "passed": None,
                "score": None,
                "reason": None,
                "details": None,
                "error": f"{type(exc).__name__}: {exc}",
                "duration_ms": duration_ms,
                "traceback": traceback.format_exc(limit=8),
            }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
