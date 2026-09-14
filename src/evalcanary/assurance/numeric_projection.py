"""Bounded exact arithmetic over canonical report facts, without new decisions."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from fractions import Fraction
from typing import Any

from .numeric import canonical_json_text, fraction_facts
from .review_queue import _paired_trials

NUMERIC_NOTE = (
    "Numeric arithmetic is descriptive only. Delta signs do not establish improvement, "
    "regression, correctness, acceptance, or quality. Missing scores remain unavailable. "
    "The complete-pair summary uses only score-complete valid pairs; it does not replace "
    "contract metrics or their missing-evidence policy. Canonical invariance and "
    "instability results remain authoritative."
)

PAIR_HEADERS = (
    "Case",
    "Pairing key",
    "Baseline score",
    "Candidate score",
    "Candidate minus baseline",
    "Baseline status",
    "Candidate status",
    "Score completeness",
)
SUMMARY_HEADERS = (
    "Valid pairs",
    "Score-complete pairs",
    "Score-incomplete pairs",
    "Complete-pair delta sum",
    "Complete-pair mean",
    "Mean denominator",
)
INVARIANCE_HEADERS = (
    "Group",
    "Role",
    "Instance / pairing key",
    "Numeric members",
    "Exact score spread",
    "Canonical absolute tolerance",
    "Canonical result",
    "Numeric evidence",
)
REPEAT_HEADERS = (
    "Case",
    "Role",
    "Total repeat trials",
    "Numeric scores",
    "Minimum",
    "Maximum",
    "Range",
    "Repeat-score tolerance",
    "Canonical score instability",
)


def _exact(value: Fraction, *, signed: bool = False) -> str:
    facts = fraction_facts(value)
    decimal = facts["decimal"]
    text = (
        str(decimal)
        if decimal is not None
        else f"{value.numerator}/{value.denominator}"
    )
    return ("+" if signed and value > 0 else "") + text


def _score(value: Decimal | int | None) -> str:
    return "unavailable" if value is None else _exact(Fraction(value))


def numeric_projection(
    report: dict[str, Any], *, case_cap: int, invariance_caps: dict[str, int]
) -> dict[str, Any]:
    """Share the same facts and bounds between Markdown and static HTML."""
    if report["judgment_spec"]["score_spec"] is None:
        return {"tables": [], "projection": []}
    cases = sorted(report["cases"], key=lambda case: str(case["case_id"]))
    pair_rows: list[tuple[str, ...]] = []
    complete = 0
    valid = 0
    delta_sum = Fraction(0)
    for case in cases:
        # Reuse the existing canonical-report pairing selection used by the queue.
        for _, _, before, after in _paired_trials(case):
            valid += 1
            first, second = before["score"], after["score"]
            delta = None
            if first is not None and second is not None:
                complete += 1
                delta = Fraction(second) - Fraction(first)
                delta_sum += delta
            if len(pair_rows) < case_cap:
                pair_rows.append(
                    (
                        str(case["case_id"]),
                        str(before["pairing_key"]),
                        _score(first),
                        _score(second),
                        "unavailable" if delta is None else _exact(delta, signed=True),
                        str(before["status"]),
                        str(after["status"]),
                        "complete" if delta is not None else "incomplete",
                    )
                )
    summary: list[tuple[str, ...]] = [
        (
            str(valid),
            str(complete),
            str(valid - complete),
            _exact(delta_sum),
            _exact(delta_sum / complete) if complete else "unavailable",
            str(complete),
        )
    ]
    projection = [
        (
            "paired numeric trials",
            str(valid),
            str(len(pair_rows)),
            str(valid - len(pair_rows)),
        )
    ]
    tables: list[tuple[str, tuple[str, ...], list[tuple[str, ...]]]] = [
        ("Paired score evidence", PAIR_HEADERS, pair_rows),
        ("Complete-pair numeric summary", SUMMARY_HEADERS, summary),
    ]

    case_by_id = {case["case_id"]: case for case in cases}
    invariant_rows: dict[tuple[str, str], list[tuple[str, ...]]] = {}
    counts: Counter[tuple[str, str]] = Counter()
    for group in sorted(
        report["invariance_groups"], key=lambda group: str(group["group_id"])
    ):
        if group["expected_relation"] != "same_score_within_tolerance":
            continue
        # An older report-v1 may lack this additive fact. Never infer its value.
        tolerance = group.get("relation_configuration", {}).get("absolute_tolerance")
        for role in ("baseline", "candidate"):
            members = [
                case_by_id[case_id]["trials"][role]
                for case_id in group["member_case_ids"]
            ]
            for instance in sorted(
                group["roles"][role], key=lambda item: item["pairing_key"] or ""
            ):
                bucket = (role, str(instance["result"]))
                counts[bucket] += 1
                rows = invariant_rows.setdefault(bucket, [])
                if len(rows) >= invariance_caps[bucket[1]]:
                    continue
                key = instance["pairing_key"]
                selected = []
                # Resolve the existing canonical instance; never create membership
                # or pair repeated, unkeyed trials by order or by their outputs.
                for trials in members:
                    matches = (
                        trials
                        if key is None
                        else [trial for trial in trials if trial["pairing_key"] == key]
                    )
                    selected.append(matches[0] if len(matches) == 1 else None)
                scores = [
                    Fraction(trial["score"])
                    for trial in selected
                    if trial is not None and trial["score"] is not None
                ]
                evidence = "complete" if len(scores) == len(members) else "incomplete"
                spread = (
                    _exact(max(scores) - min(scores))
                    if len(scores) >= 2
                    else "unavailable"
                )
                if len(scores) < 2:
                    evidence = "insufficient numeric members"
                rows.append(
                    (
                        str(group["group_id"]),
                        role,
                        "single / unkeyed" if key is None else str(key),
                        str(len(scores)),
                        spread,
                        _score(tolerance),
                        str(instance["result"]),
                        evidence,
                    )
                )
    if counts:
        details = []
        for role in ("baseline", "candidate"):
            for result in ("violated", "not_evaluable", "satisfied"):
                rows = invariant_rows.get((role, result), [])
                total = counts[(role, result)]
                details.extend(rows)
                projection.append(
                    (
                        f"numeric invariance {role} {result}",
                        str(total),
                        str(len(rows)),
                        str(total - len(rows)),
                    )
                )
        tables.append(("Numeric invariance evidence", INVARIANCE_HEADERS, details))

    repeat_rows: list[tuple[str, ...]] = []
    repeats = 0
    tolerance = report["judgment_spec"]["repeat_score_tolerance"]
    states = {
        role: {
            item["case_id"]: item["score_instability"]
            for item in report["repeat_diagnostics"][role]["cases"]
        }
        for role in ("baseline", "candidate")
    }
    for case in cases:
        for role in ("baseline", "candidate"):
            trials = case["trials"][role]
            if len(trials) <= 1:
                continue
            repeats += 1
            if len(repeat_rows) >= case_cap:
                continue
            scores = [
                Fraction(trial["score"])
                for trial in trials
                if trial["score"] is not None
            ]
            state = states[role][case["case_id"]]
            repeat_rows.append(
                (
                    str(case["case_id"]),
                    role,
                    str(len(trials)),
                    str(len(scores)),
                    _exact(min(scores)) if scores else "unavailable",
                    _exact(max(scores)) if scores else "unavailable",
                    _exact(max(scores) - min(scores)) if scores else "unavailable",
                    "not configured" if tolerance is None else _score(tolerance),
                    state if isinstance(state, str) else canonical_json_text(state),
                )
            )
    if repeats:
        tables.append(("Repeated score ranges", REPEAT_HEADERS, repeat_rows))
        projection.append(
            (
                "repeated numeric case roles",
                str(repeats),
                str(len(repeat_rows)),
                str(repeats - len(repeat_rows)),
            )
        )
    return {"tables": tables, "projection": projection}
