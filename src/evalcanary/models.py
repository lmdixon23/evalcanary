"""Core immutable data structures."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]


@dataclass(frozen=True, slots=True)
class CaseRecord:
    """One fixed evaluation case passed to both verifier versions."""

    case_id: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Verdict:
    """Normalized result returned by one verifier for one case."""

    case_id: str
    passed: bool | None
    score: float | None = None
    reason: str | None = None
    details: JSONValue = None
    error: str | None = None
    duration_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Runtime timing is diagnostic, not part of the reproducible report.
        data.pop("duration_ms", None)
        return data


@dataclass(frozen=True, slots=True)
class ChangedCase:
    """A case whose normalized pass/fail verdict changed."""

    case_id: str
    transition: str
    before: Verdict
    after: Verdict
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "transition": self.transition,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class SliceSummary:
    """Comparison statistics for one subgroup value."""

    slice_name: str
    slice_value: str
    total_cases: int
    comparable_cases: int
    stable_pass: int
    pass_to_fail: int
    fail_to_pass: int
    stable_fail: int
    before_rate: float | None
    after_rate: float | None
    delta: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ComparisonSummary:
    """Complete machine-readable evaluator migration result."""

    schema_version: str
    tool_version: str
    run_id: str
    created_at: str
    total_cases: int
    comparable_cases: int
    error_cases: int
    stable_pass: int
    pass_to_fail: int
    fail_to_pass: int
    stable_fail: int
    before_rate: float | None
    after_rate: float | None
    delta: float | None
    bootstrap_ci_low: float | None
    bootstrap_ci_high: float | None
    bootstrap_replicates: int
    bootstrap_seed: int
    mcnemar_p_value: float | None
    mcnemar_method: str | None
    changed_cases: tuple[ChangedCase, ...] = field(default_factory=tuple)
    slices: tuple[SliceSummary, ...] = field(default_factory=tuple)
    policy: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    verifier_diff: str = ""
    limitations: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "total_cases": self.total_cases,
            "comparable_cases": self.comparable_cases,
            "error_cases": self.error_cases,
            "transition_counts": {
                "stable_pass": self.stable_pass,
                "pass_to_fail": self.pass_to_fail,
                "fail_to_pass": self.fail_to_pass,
                "stable_fail": self.stable_fail,
            },
            "rates": {
                "before": self.before_rate,
                "after": self.after_rate,
                "delta": self.delta,
            },
            "paired_bootstrap_ci": {
                "low": self.bootstrap_ci_low,
                "high": self.bootstrap_ci_high,
                "replicates": self.bootstrap_replicates,
                "seed": self.bootstrap_seed,
            },
            "mcnemar": {
                "p_value": self.mcnemar_p_value,
                "method": self.mcnemar_method,
            },
            "changed_cases": [item.to_dict() for item in self.changed_cases],
            "slices": [item.to_dict() for item in self.slices],
            "policy": self.policy,
            "provenance": self.provenance,
            "verifier_diff": self.verifier_diff,
            "limitations": list(self.limitations),
        }
