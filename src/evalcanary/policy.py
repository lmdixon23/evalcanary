"""TOML policy parsing and migration-gate evaluation."""

from __future__ import annotations

import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

from .errors import PolicyConfigurationError
from .models import ComparisonSummary

_ALLOWED = {
    "min_cases",
    "max_error_cases",
    "max_abs_score_delta",
    "max_pass_to_fail",
    "max_fail_to_pass",
    "max_changed_cases",
    "require_statistical_review_below_p",
}


def load_policy(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    if not path.is_file():
        raise PolicyConfigurationError(f"Policy file does not exist: {path}")
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as exc:
        raise PolicyConfigurationError(f"Invalid TOML policy: {exc}") from exc
    policy = document.get("policy", {})
    if not isinstance(policy, dict):
        raise PolicyConfigurationError("Policy file requires a [policy] table.")
    unknown = sorted(set(policy) - _ALLOWED)
    if unknown:
        raise PolicyConfigurationError(
            "Unknown policy keys: " + ", ".join(unknown)
        )
    integer_keys = (
        "min_cases",
        "max_error_cases",
        "max_pass_to_fail",
        "max_fail_to_pass",
        "max_changed_cases",
    )
    for key in integer_keys:
        if key in policy and (
            isinstance(policy[key], bool)
            or not isinstance(policy[key], int)
            or policy[key] < 0
        ):
            raise PolicyConfigurationError(
                f"{key} must be a non-negative integer."
            )
    numeric_keys = (
        "max_abs_score_delta",
        "require_statistical_review_below_p",
    )
    for key in numeric_keys:
        if key in policy:
            value = policy[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value < 0
            ):
                raise PolicyConfigurationError(
                    f"{key} must be a non-negative number."
                )
    return policy


def evaluate_policy(
    summary: ComparisonSummary, policy: dict[str, Any]
) -> ComparisonSummary:
    checks: list[dict[str, Any]] = []

    def add(
        name: str,
        passed: bool,
        actual: Any,
        limit: Any,
        message: str,
    ) -> None:
        checks.append(
            {
                "name": name,
                "passed": passed,
                "actual": actual,
                "limit": limit,
                "message": message,
            }
        )

    if "min_cases" in policy:
        limit = policy["min_cases"]
        add(
            "min_cases",
            summary.total_cases >= limit,
            summary.total_cases,
            limit,
            "Total fixed cases",
        )
    if "max_error_cases" in policy:
        limit = policy["max_error_cases"]
        add(
            "max_error_cases",
            summary.error_cases <= limit,
            summary.error_cases,
            limit,
            "Verifier error cases",
        )
    if "max_abs_score_delta" in policy:
        limit = float(policy["max_abs_score_delta"])
        actual = abs(summary.delta) if summary.delta is not None else None
        add(
            "max_abs_score_delta",
            actual is not None and actual <= limit,
            actual,
            limit,
            "Absolute pass-rate change",
        )
    if "max_pass_to_fail" in policy:
        limit = policy["max_pass_to_fail"]
        add(
            "max_pass_to_fail",
            summary.pass_to_fail <= limit,
            summary.pass_to_fail,
            limit,
            "Pass-to-fail transitions",
        )
    if "max_fail_to_pass" in policy:
        limit = policy["max_fail_to_pass"]
        add(
            "max_fail_to_pass",
            summary.fail_to_pass <= limit,
            summary.fail_to_pass,
            limit,
            "Fail-to-pass transitions",
        )
    if "max_changed_cases" in policy:
        limit = policy["max_changed_cases"]
        actual = summary.pass_to_fail + summary.fail_to_pass
        add(
            "max_changed_cases",
            actual <= limit,
            actual,
            limit,
            "All changed verdicts",
        )
    if "require_statistical_review_below_p" in policy:
        limit = float(policy["require_statistical_review_below_p"])
        actual = summary.mcnemar_p_value
        passed = actual is None or actual >= limit
        add(
            "require_statistical_review_below_p",
            passed,
            actual,
            limit,
            "Exact paired significance review threshold",
        )

    result = {
        "configured": bool(policy),
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
        "source": policy,
    }
    return replace(summary, policy=result)
