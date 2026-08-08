"""Paired evaluator comparison engine."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from . import __version__
from .models import (
    CaseRecord,
    ChangedCase,
    ComparisonSummary,
    SliceSummary,
    Verdict,
)
from .provenance import (
    build_provenance,
    make_run_id,
    reproducible_now,
    unified_verifier_diff,
)
from .statistics import exact_mcnemar_two_sided, paired_bootstrap_delta_ci


def _nested_value(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return "<missing>"
        current = current[part]
    if isinstance(current, (dict, list)):
        return repr(current)
    return current


def _rate(values: Iterable[bool]) -> float | None:
    items = list(values)
    return sum(items) / len(items) if items else None


def _transition(before: bool, after: bool) -> str:
    if before and after:
        return "stable_pass"
    if before and not after:
        return "pass_to_fail"
    if not before and after:
        return "fail_to_pass"
    return "stable_fail"


def _slice_summary(
    slice_name: str,
    slice_value: str,
    records: list[tuple[CaseRecord, Verdict, Verdict]],
) -> SliceSummary:
    counts = {
        name: 0
        for name in (
            "stable_pass",
            "pass_to_fail",
            "fail_to_pass",
            "stable_fail",
        )
    }
    comparable: list[tuple[bool, bool]] = []
    for _, before, after in records:
        if before.passed is None or after.passed is None:
            continue
        comparable.append((before.passed, after.passed))
        counts[_transition(before.passed, after.passed)] += 1
    before_rate = _rate(item[0] for item in comparable)
    after_rate = _rate(item[1] for item in comparable)
    delta = (
        None
        if before_rate is None or after_rate is None
        else after_rate - before_rate
    )
    return SliceSummary(
        slice_name=slice_name,
        slice_value=slice_value,
        total_cases=len(records),
        comparable_cases=len(comparable),
        stable_pass=counts["stable_pass"],
        pass_to_fail=counts["pass_to_fail"],
        fail_to_pass=counts["fail_to_pass"],
        stable_fail=counts["stable_fail"],
        before_rate=before_rate,
        after_rate=after_rate,
        delta=delta,
    )


def compare_verdicts(
    cases: list[CaseRecord],
    before_verdicts: list[Verdict],
    after_verdicts: list[Verdict],
    *,
    data_path: Path,
    before_path: Path,
    after_path: Path,
    slices: list[str] | None = None,
    include_content: bool = False,
    include_source_diff: bool = False,
    bootstrap_replicates: int = 2000,
    bootstrap_seed: int = 20260805,
    command: list[str] | None = None,
) -> ComparisonSummary:
    if not (len(cases) == len(before_verdicts) == len(after_verdicts)):
        raise ValueError("Case and verdict collections must have equal lengths.")

    counts = {
        name: 0
        for name in (
            "stable_pass",
            "pass_to_fail",
            "fail_to_pass",
            "stable_fail",
        )
    }
    paired_before: list[bool] = []
    paired_after: list[bool] = []
    changed: list[ChangedCase] = []
    joined: list[tuple[CaseRecord, Verdict, Verdict]] = []
    error_cases = 0

    for case, before, after in zip(
        cases, before_verdicts, after_verdicts, strict=True
    ):
        if case.case_id != before.case_id or case.case_id != after.case_id:
            raise ValueError("Case and verdict identity mismatch.")
        joined.append((case, before, after))
        if before.passed is None or after.passed is None:
            error_cases += 1
            continue
        paired_before.append(before.passed)
        paired_after.append(after.passed)
        transition = _transition(before.passed, after.passed)
        counts[transition] += 1
        if before.passed != after.passed:
            changed.append(
                ChangedCase(
                    case_id=case.case_id,
                    transition=transition,
                    before=before,
                    after=after,
                    payload=case.payload if include_content else None,
                )
            )

    before_rate = _rate(paired_before)
    after_rate = _rate(paired_after)
    delta = (
        None
        if before_rate is None or after_rate is None
        else after_rate - before_rate
    )
    ci_low, ci_high = paired_bootstrap_delta_ci(
        paired_before,
        paired_after,
        replicates=bootstrap_replicates,
        seed=bootstrap_seed,
    )
    mcnemar_p, mcnemar_method = exact_mcnemar_two_sided(
        counts["pass_to_fail"], counts["fail_to_pass"]
    )

    slice_results: list[SliceSummary] = []
    for slice_name in slices or []:
        grouped: dict[
            str, list[tuple[CaseRecord, Verdict, Verdict]]
        ] = defaultdict(list)
        for record in joined:
            raw = _nested_value(record[0].payload, slice_name)
            grouped[str(raw)].append(record)
        for value in sorted(grouped):
            slice_results.append(
                _slice_summary(slice_name, value, grouped[value])
            )

    created = reproducible_now()
    limitations = (
        "EvalCanary isolates evaluator effects only when the input-output corpus is fixed.",
        "A changed verdict is evidence of evaluator sensitivity, not automatic proof that either evaluator is correct.",
        "Python subprocess isolation is not a security sandbox; run only trusted verifier code.",
        "The bootstrap interval is a deterministic percentile estimate and should not replace domain review.",
    )
    return ComparisonSummary(
        schema_version="evalcanary-comparison-v1",
        tool_version=__version__,
        run_id=make_run_id(data_path, before_path, after_path),
        created_at=created.isoformat().replace("+00:00", "Z"),
        total_cases=len(cases),
        comparable_cases=len(paired_before),
        error_cases=error_cases,
        stable_pass=counts["stable_pass"],
        pass_to_fail=counts["pass_to_fail"],
        fail_to_pass=counts["fail_to_pass"],
        stable_fail=counts["stable_fail"],
        before_rate=before_rate,
        after_rate=after_rate,
        delta=delta,
        bootstrap_ci_low=ci_low,
        bootstrap_ci_high=ci_high,
        bootstrap_replicates=bootstrap_replicates,
        bootstrap_seed=bootstrap_seed,
        mcnemar_p_value=mcnemar_p,
        mcnemar_method=mcnemar_method,
        changed_cases=tuple(changed),
        slices=tuple(slice_results),
        policy={},
        provenance=build_provenance(
            data_path, before_path, after_path, command=command
        ),
        verifier_diff=(
            unified_verifier_diff(before_path, after_path)
            if include_source_diff
            else (
                "Source diff omitted by default. Rerun with "
                "--include-source-diff to include trusted source text."
            )
        ),
        limitations=limitations,
    )
