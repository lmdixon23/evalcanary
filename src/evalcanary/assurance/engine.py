"""Canonical evidence analysis and the closed evaluator contract."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any

from .constants import LIMITATIONS, PROVENANCE_FIELDS, STATUSES
from .numeric import (
    canonical_sha256,
    decimal_to_fraction,
    fraction_facts,
)
from .schema import AssuranceArtifact, AssuranceContract
from .security import omission_facts, redact_text, safe_reportable_url

_SAFE_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,255}\Z")


@dataclass(frozen=True, slots=True)
class MetricOutcome:
    state: str
    value: bool | Fraction | None
    evidence: dict[str, Any]


def _roles(artifact: AssuranceArtifact) -> dict[str, str]:
    return artifact.evaluation_roles


def _trials_by_case_role(
    artifact: AssuranceArtifact,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    roles = _roles(artifact)
    for trial in artifact.trials:
        result[(trial["case_id"], roles[trial["evaluation_id"]])].append(trial)
    for items in result.values():
        items.sort(key=lambda item: item["source_order"])
    return result


def _valid_pairs(
    case_id: str, trial_map: dict[tuple[str, str], list[dict[str, Any]]]
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], bool]:
    before = trial_map.get((case_id, "baseline"), [])
    after = trial_map.get((case_id, "candidate"), [])
    before_keys = {
        item["pairing_key"]: item for item in before if item["pairing_key"] is not None
    }
    after_keys = {
        item["pairing_key"]: item for item in after if item["pairing_key"] is not None
    }
    shared = sorted(set(before_keys) & set(after_keys))
    pairs = [(before_keys[key], after_keys[key]) for key in shared]
    complete = (
        len(pairs) == len(before)
        and len(pairs) == len(after)
        and all(item["pairing_key"] is not None for item in before + after)
    )
    return pairs, complete


def _safe_identity(value: str | None, *, typed_url: bool = False) -> dict[str, Any]:
    if value is None:
        return {"identity": None, "identity_sha256": None, "identity_omitted": False}
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    if typed_url:
        safe_url = safe_reportable_url(value)
        return {
            "identity": safe_url,
            "identity_sha256": digest,
            "identity_omitted": safe_url is None,
        }
    redacted = redact_text(value)
    safe = redacted == value and _SAFE_IDENTITY.fullmatch(value) is not None
    return {
        "identity": value if safe else None,
        "identity_sha256": digest,
        "identity_omitted": not safe,
    }


def _component_fact(
    value: dict[str, Any], *, field_name: str | None = None
) -> dict[str, Any]:
    return {
        "presence": value["presence"],
        **_safe_identity(
            value["identity"], typed_url=field_name in {"source_url", "license_url"}
        ),
        "declared_sha256": value["sha256"],
    }


def _provenance_fact(value: dict[str, Any]) -> dict[str, Any]:
    return {
        name: _component_fact(item, field_name=name)
        for name, item in sorted(value.items())
    }


def _presence(value: dict[str, Any] | None) -> str:
    return "missing" if value is None else str(value["presence"])


def _provenance_delta(
    before: dict[str, Any],
    after: dict[str, Any],
    fields: frozenset[str] = PROVENANCE_FIELDS,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name in sorted(fields):
        first = before.get(name)
        second = after.get(name)
        first_presence = _presence(first)
        second_presence = _presence(second)
        if "intentionally_omitted" in {first_presence, second_presence}:
            delta = "omitted"
        elif first_presence == "missing" and second_presence == "missing":
            delta = "missing_both"
        elif first_presence == "missing":
            delta = "missing_before"
        elif second_presence == "missing":
            delta = "missing_after"
        elif first == second:
            delta = "same"
        else:
            delta = "changed"
        result[name] = {
            "delta": delta,
            "baseline_presence": first_presence,
            "candidate_presence": second_presence,
        }
    return result


def _isolation(artifact: AssuranceArtifact) -> tuple[str, str, list[dict[str, Any]]]:
    evaluations = artifact.evaluations_by_role
    baseline = evaluations["baseline"]["context_components"]
    candidate = evaluations["candidate"]["context_components"]
    exceptions = {
        item["component"]: item
        for item in artifact.header["allowed_context_differences"]
    }
    findings: list[dict[str, Any]] = []
    not_isolated = False
    unknown = False
    for component in sorted(baseline):
        first = baseline[component]
        second = candidate[component]
        if first == second:
            if first["presence"] in {"missing", "intentionally_omitted"}:
                unknown = True
                findings.append(
                    {"component": component, "finding": "unknown_context_component"}
                )
            continue
        exception = exceptions.get(component)
        exact = (
            exception is not None
            and exception["expected_baseline_component_value"] == first
            and exception["expected_candidate_component_value"] == second
        )
        if not exact:
            findings.append(
                {"component": component, "finding": "unapproved_context_difference"}
            )
            return "NOT_COMPARABLE", "UNKNOWN", findings
        if first["presence"] in {"missing", "intentionally_omitted"} or second[
            "presence"
        ] in {"missing", "intentionally_omitted"}:
            unknown = True
            finding = "expected_but_unknown_context_difference"
        else:
            not_isolated = True
            finding = "accepted_exact_context_difference"
        findings.append({"component": component, "finding": finding})
    if unknown:
        return "VALID", "UNKNOWN", findings
    if not_isolated:
        return "VALID", "NOT_ISOLATED", findings
    return "VALID", "ISOLATED", findings


def _repeat_fact(
    cases: set[str],
    role: str,
    trial_map: dict[tuple[str, str], list[dict[str, Any]]],
    tolerance: Decimal | None,
) -> dict[str, Any]:
    trials = [
        item for case_id in sorted(cases) for item in trial_map.get((case_id, role), [])
    ]
    statuses = Counter(item["status"] for item in trials)
    labels = Counter(
        item["label"]
        for item in trials
        if item["status"] == "determinate" and item["label"] is not None
    )
    per_case: list[dict[str, Any]] = []
    for case_id in sorted(cases):
        items = trial_map.get((case_id, role), [])
        status_values = {item["status"] for item in items}
        label_values = {
            item["label"]
            for item in items
            if item["status"] == "determinate" and item["label"] is not None
        }
        scores = [item["score"] for item in items if item["score"] is not None]
        score_instability: bool | str = "not_configured"
        if tolerance is not None:
            score_instability = bool(scores and max(scores) - min(scores) > tolerance)
        per_case.append(
            {
                "case_id": case_id,
                "trial_count": len(items),
                "status_instability": len(status_values) > 1,
                "label_instability": len(label_values) > 1,
                "score_instability": score_instability,
            }
        )
    determinate = statuses["determinate"]
    return {
        "role": role,
        "trial_count": len(trials),
        "status_distribution": {name: statuses[name] for name in sorted(STATUSES)},
        "determinate_trials": determinate,
        "determinate_coverage": fraction_facts(Fraction(determinate, len(trials)))
        if trials
        else None,
        "label_distribution": {name: labels[name] for name in sorted(labels)},
        "conditional_label_rates": {
            name: fraction_facts(Fraction(count, determinate))
            for name, count in sorted(labels.items())
        }
        if determinate
        else {},
        "cases": per_case,
    }


def _pairing_fact(
    cases: set[str], trial_map: dict[tuple[str, str], list[dict[str, Any]]]
) -> dict[str, Any]:
    pairs = 0
    baseline = 0
    candidate = 0
    incomplete_cases: list[str] = []
    for case_id in sorted(cases):
        before = trial_map.get((case_id, "baseline"), [])
        after = trial_map.get((case_id, "candidate"), [])
        current, complete = _valid_pairs(case_id, trial_map)
        pairs += len(current)
        baseline += len(before)
        candidate += len(after)
        if not complete:
            incomplete_cases.append(case_id)
    denominator = max(baseline, candidate)
    return {
        "valid_pair_count": pairs,
        "baseline_trial_count": baseline,
        "candidate_trial_count": candidate,
        "pairing_coverage": fraction_facts(Fraction(pairs, denominator))
        if denominator
        else None,
        "unequal_counts": baseline != candidate,
        "incomplete_case_ids": incomplete_cases,
    }


def _paired_transitions(
    cases: set[str], trial_map: dict[tuple[str, str], list[dict[str, Any]]]
) -> dict[str, Any]:
    status_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    for case_id in sorted(cases):
        pairs, _ = _valid_pairs(case_id, trial_map)
        for before, after in pairs:
            status_counts[f"{before['status']}->{after['status']}"] += 1
            if before["status"] == after["status"] == "determinate":
                label_counts[f"{before['label']}->{after['label']}"] += 1
    return {
        "status_transitions": dict(sorted(status_counts.items())),
        "label_transitions": dict(sorted(label_counts.items())),
    }


def _relation_result(group: dict[str, Any], trials: list[dict[str, Any]]) -> str:
    if any(item["status"] != "determinate" for item in trials):
        return "not_evaluable"
    relation = group["expected_relation"]
    if relation == "same_label":
        labels = [item["label"] for item in trials]
        return "satisfied" if len(set(labels)) == 1 else "violated"
    if relation == "swapped_preference":
        first, second = (item["label"] for item in trials)
        parameters = group["relation_parameters"]
        expected = {
            (parameters["first_label"], parameters["second_label"]),
            (parameters["second_label"], parameters["first_label"]),
        }
        tie = parameters.get("tie_label")
        if tie is not None:
            expected.add((tie, tie))
        return "satisfied" if (first, second) in expected else "violated"
    scores = [item["score"] for item in trials]
    if any(score is None for score in scores):
        return "not_evaluable"
    tolerance = group["relation_parameters"]["absolute_tolerance"]
    return "satisfied" if max(scores) - min(scores) <= tolerance else "violated"


def _invariance_facts(
    artifact: AssuranceArtifact, trial_map: dict[tuple[str, str], list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for group in artifact.invariance_groups:
        role_results: dict[str, list[dict[str, Any]]] = {}
        for role in ("baseline", "candidate"):
            members = [
                trial_map.get((case_id, role), [])
                for case_id in group["member_case_ids"]
            ]
            instances: list[dict[str, Any]] = []
            if all(len(items) == 1 for items in members):
                trials = [items[0] for items in members]
                instances.append(
                    {"pairing_key": None, "result": _relation_result(group, trials)}
                )
            else:
                keyed = [
                    {
                        item["pairing_key"]: item
                        for item in items
                        if item["pairing_key"] is not None
                    }
                    for items in members
                ]
                common = (
                    set.intersection(*(set(items) for items in keyed))
                    if keyed
                    else set()
                )
                complete = (
                    bool(common)
                    and all(len(items) == len(common) for items in keyed)
                    and all(
                        all(item["pairing_key"] is not None for item in raw)
                        for item, raw in zip(keyed, members, strict=True)
                    )
                )
                if complete:
                    for key in sorted(common):
                        instances.append(
                            {
                                "pairing_key": key,
                                "result": _relation_result(
                                    group, [items[key] for items in keyed]
                                ),
                            }
                        )
                else:
                    instances.append({"pairing_key": None, "result": "not_evaluable"})
            role_results[role] = instances
        results.append(
            {
                "group_id": group["group_id"],
                "expected_relation": group["expected_relation"],
                "severity": group["severity"],
                "member_case_ids": group["member_case_ids"],
                "roles": role_results,
            }
        )
    return results


def _anchor_facts(
    artifact: AssuranceArtifact, trial_map: dict[tuple[str, str], list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    case_count = len(artifact.cases)
    results: list[dict[str, Any]] = []
    judgment_labels = artifact.header["judgment_spec"]["label_space"]
    for anchor_set in artifact.anchor_sets:
        raw = [
            item
            for item in artifact.anchors
            if item["anchor_set_id"] == anchor_set["anchor_set_id"]
            and item["kind"] == "raw_annotation"
        ]
        aggregate = [
            item
            for item in artifact.anchors
            if item["anchor_set_id"] == anchor_set["anchor_set_id"]
            and item["kind"] == "aggregate"
        ]
        covered = {item["case_id"] for item in raw}
        compatible = anchor_set["label_space"] == judgment_labels
        roles: dict[str, Any] = {}
        for role in ("baseline", "candidate"):
            confusion: Counter[str] = Counter()
            comparable = 0
            disagreement = 0
            selected_role_error = 0
            selected_role_non_determinate = 0
            anchor_non_determinate = 0
            non_unique_selected_role = 0
            incompatible_label_space = 0
            for anchor in raw:
                trials = trial_map.get((anchor["case_id"], role), [])
                if len(trials) != 1:
                    non_unique_selected_role += 1
                    continue
                if trials[0]["status"] != "determinate":
                    selected_role_non_determinate += 1
                    selected_role_error += int(trials[0]["status"] == "error")
                    continue
                if anchor["status"] != "determinate":
                    anchor_non_determinate += 1
                    continue
                if not compatible:
                    incompatible_label_space += 1
                    continue
                comparable += 1
                key = f"{anchor['label']}->{trials[0]['label']}"
                confusion[key] += 1
                disagreement += int(anchor["label"] != trials[0]["label"])
            roles[role] = {
                "comparable_raw_annotations": comparable,
                "non_comparable_raw_annotations": len(raw) - comparable,
                "selected_role_error_annotations": selected_role_error,
                "selected_role_non_determinate_annotations": (
                    selected_role_non_determinate
                ),
                "anchor_non_determinate_annotations": anchor_non_determinate,
                "non_unique_selected_role_annotations": non_unique_selected_role,
                "incompatible_label_space_annotations": incompatible_label_space,
                "exact_label_agreements": comparable - disagreement,
                "exact_label_disagreements": disagreement,
                "confusion": dict(sorted(confusion.items())),
            }
        results.append(
            {
                "anchor_set_id": anchor_set["anchor_set_id"],
                "aggregation_method": anchor_set["aggregation_method"],
                "clustering_unit": _safe_identity(anchor_set["clustering_unit"]),
                "label_spaces_exactly_match": compatible,
                "raw_annotation_count": len(raw),
                "aggregate_anchor_count": len(aggregate),
                "covered_case_count": len(covered),
                "coverage": fraction_facts(Fraction(len(covered), case_count)),
                "missing_case_count": case_count - len(covered),
                "cluster_count": len({item["cluster_id"] for item in raw}),
                "roles": roles,
            }
        )
    return results


def _trial_fact(trial: dict[str, Any]) -> dict[str, Any]:
    error_class = trial["error"]["error_class"] if trial["error"] is not None else None
    error_message = (
        trial["error"].get("message") if trial["error"] is not None else None
    )
    return {
        "trial_id": trial["trial_id"],
        "source_order": trial["source_order"],
        "pairing_key": trial["pairing_key"],
        "status": trial["status"],
        "label": trial["label"],
        "score": trial["score"],
        "error_class": error_class,
        "reason": omission_facts(trial["reason"]),
        "details": omission_facts(trial["details"]),
        "error_message": omission_facts(error_message),
        "extensions": {"present": bool(trial["extensions"]), "omitted": True},
        "provenance": _provenance_fact(trial["provenance"]),
    }


def _selected_cases(
    artifact: AssuranceArtifact, scope: str, scope_id: str | None
) -> set[str]:
    if scope == "all_cases":
        return {item["case_id"] for item in artifact.cases}
    if scope == "critical_group":
        return {
            item["case_id"]
            for item in artifact.cases
            if scope_id in item["critical_group_ids"]
        }
    return set()


def _provenance_owner(
    artifact: AssuranceArtifact, owner_type: str, owner_id: str
) -> dict[str, Any] | None:
    if owner_type == "artifact":
        return (
            artifact.header["provenance"]
            if artifact.header["artifact_id"] == owner_id
            else None
        )
    collections = {
        "evaluation": (artifact.header["evaluations"], "evaluation_id"),
        "trial": (artifact.trials, "trial_id"),
        "anchor_set": (artifact.anchor_sets, "anchor_set_id"),
        "anchor": (artifact.anchors, "anchor_id"),
    }
    collection, key = collections[owner_type]
    for item in collection:
        if item[key] == owner_id:
            provenance = item["provenance"]
            return provenance if isinstance(provenance, dict) else None
    return None


def _metric_outcome(
    artifact: AssuranceArtifact,
    evidence_status: str,
    isolation_status: str,
    invariance: list[dict[str, Any]],
    rule: dict[str, Any],
    trial_map: dict[tuple[str, str], list[dict[str, Any]]],
) -> MetricOutcome:
    metric = rule["metric"]
    scope = rule["scope"]
    scope_id = rule["scope_id"]
    params = rule["parameters"]
    if evidence_status != "VALID":
        return MetricOutcome("missing", None, {"reason": "evidence_not_valid"})
    cases = _selected_cases(artifact, scope, scope_id)
    if metric == "corpus_equal":
        return MetricOutcome("satisfied", True, {"case_count": len(artifact.cases)})
    if metric == "context_isolated":
        if isolation_status == "UNKNOWN":
            return MetricOutcome(
                "missing", None, {"isolation_status": isolation_status}
            )
        return MetricOutcome(
            "satisfied",
            isolation_status == "ISOLATED",
            {"isolation_status": isolation_status},
        )
    if metric in {
        "determinate_coverage",
        "status_count",
        "determinate_label_count",
        "unstable_case_count",
    }:
        role = params["role"]
        trials = [
            item for case_id in cases for item in trial_map.get((case_id, role), [])
        ]
        if metric == "determinate_coverage":
            if not trials:
                return MetricOutcome(
                    "missing", None, {"reason": "missing_denominator"}
                )
            value = Fraction(
                sum(item["status"] == "determinate" for item in trials), len(trials)
            )
        elif metric == "status_count":
            value = Fraction(
                sum(item["status"] == params["status"] for item in trials), 1
            )
        elif metric == "determinate_label_count":
            if artifact.header["judgment_spec"]["kind"] == "numeric":
                return MetricOutcome(
                    "not_applicable", None, {"reason": "numeric_judgment"}
                )
            value = Fraction(
                sum(
                    item["status"] == "determinate" and item["label"] == params["label"]
                    for item in trials
                ),
                1,
            )
        else:
            dimension = params["dimension"]
            judgment = artifact.header["judgment_spec"]
            if dimension == "label" and judgment["kind"] == "numeric":
                return MetricOutcome(
                    "not_applicable", None, {"reason": "numeric_judgment"}
                )
            if dimension == "score" and (
                judgment["score_spec"] is None
                or judgment["repeat_score_tolerance"] is None
            ):
                return MetricOutcome(
                    "not_applicable",
                    None,
                    {"reason": "score_instability_not_configured"},
                )
            unstable = 0
            for case_id in cases:
                items = trial_map.get((case_id, role), [])
                if dimension == "status":
                    unstable += int(len({item["status"] for item in items}) > 1)
                elif dimension == "label":
                    unstable += int(
                        len(
                            {
                                item["label"]
                                for item in items
                                if item["status"] == "determinate"
                            }
                        )
                        > 1
                    )
                else:
                    scores = [
                        item["score"] for item in items if item["score"] is not None
                    ]
                    unstable += int(
                        bool(scores)
                        and max(scores) - min(scores)
                        > judgment["repeat_score_tolerance"]
                    )
            value = Fraction(unstable, 1)
        return MetricOutcome("satisfied", value, {"selected_case_count": len(cases)})
    if metric == "determinate_coverage_delta":
        before = [
            item
            for case_id in cases
            for item in trial_map.get((case_id, "baseline"), [])
        ]
        after = [
            item
            for case_id in cases
            for item in trial_map.get((case_id, "candidate"), [])
        ]
        if not before or not after:
            return MetricOutcome("missing", None, {"reason": "missing_denominator"})
        value = Fraction(
            sum(item["status"] == "determinate" for item in after), len(after)
        ) - Fraction(
            sum(item["status"] == "determinate" for item in before), len(before)
        )
        return MetricOutcome(
            "satisfied",
            value,
            {"baseline_trials": len(before), "candidate_trials": len(after)},
        )
    if metric in {
        "new_status_count",
        "determinate_label_transition_count",
        "critical_regression_count",
        "score_delta",
    }:
        if (
            metric
            in {"determinate_label_transition_count", "critical_regression_count"}
            and artifact.header["judgment_spec"]["kind"] == "numeric"
        ):
            return MetricOutcome("not_applicable", None, {"reason": "numeric_judgment"})
        if metric == "score_delta":
            score_spec = artifact.header["judgment_spec"]["score_spec"]
            if score_spec is None or score_spec["comparison"] == "none":
                return MetricOutcome(
                    "not_applicable", None, {"reason": "score_delta_not_configured"}
                )
        count = 0
        matching_cases: set[str] = set()
        score_sum = Fraction(0)
        pair_count = 0
        for case_id in sorted(cases):
            pairs, complete = _valid_pairs(case_id, trial_map)
            if not complete:
                return MetricOutcome(
                    "missing",
                    None,
                    {"reason": "incomplete_pairing", "case_id": case_id},
                )
            for pair_before, pair_after in pairs:
                if metric == "new_status_count":
                    count += int(
                        pair_after["status"] == params["status"]
                        and pair_before["status"] != params["status"]
                    )
                elif metric in {
                    "determinate_label_transition_count",
                    "critical_regression_count",
                }:
                    if (
                        pair_before["status"] != "determinate"
                        or pair_after["status"] != "determinate"
                    ):
                        return MetricOutcome(
                            "missing",
                            None,
                            {"reason": "non_determinate_pair", "case_id": case_id},
                        )
                    if (
                        pair_before["label"] == params["from_label"]
                        and pair_after["label"] == params["to_label"]
                    ):
                        count += 1
                        matching_cases.add(case_id)
                else:
                    if pair_before["score"] is None or pair_after["score"] is None:
                        return MetricOutcome(
                            "missing",
                            None,
                            {"reason": "missing_paired_score", "case_id": case_id},
                        )
                    score_sum += decimal_to_fraction(
                        pair_after["score"] - pair_before["score"]
                    )
                    pair_count += 1
        if metric == "critical_regression_count":
            count = len(matching_cases)
        if metric == "score_delta":
            if pair_count == 0:
                return MetricOutcome("missing", None, {"reason": "no_score_pairs"})
            return MetricOutcome(
                "satisfied",
                score_sum / pair_count,
                {"sum": fraction_facts(score_sum), "pair_count": pair_count},
            )
        return MetricOutcome(
            "satisfied",
            Fraction(count, 1),
            {"matching_case_ids": sorted(matching_cases)},
        )
    if metric in {"invariance_violation_count", "invariance_not_evaluable_count"}:
        selected = (
            invariance
            if scope == "all_cases"
            else [item for item in invariance if item["group_id"] == scope_id]
        )
        if not selected:
            return MetricOutcome(
                "not_applicable", None, {"reason": "no_declared_invariance_groups"}
            )
        role = params["role"]
        instances = [instance for item in selected for instance in item["roles"][role]]
        if metric == "invariance_violation_count" and any(
            instance["result"] == "not_evaluable" for instance in instances
        ):
            partial = sum(instance["result"] == "violated" for instance in instances)
            return MetricOutcome("missing", None, {"partial_violation_count": partial})
        target = (
            "violated" if metric == "invariance_violation_count" else "not_evaluable"
        )
        return MetricOutcome(
            "satisfied",
            Fraction(sum(instance["result"] == target for instance in instances), 1),
            {"instance_count": len(instances)},
        )
    if metric == "anchor_coverage":
        covered = {
            item["case_id"]
            for item in artifact.anchors
            if item["anchor_set_id"] == scope_id and item["kind"] == "raw_annotation"
        }
        return MetricOutcome(
            "satisfied",
            Fraction(len(covered), len(artifact.cases)),
            {"covered_case_ids": sorted(covered)},
        )
    if metric == "anchor_disagreement_count":
        if artifact.header["judgment_spec"]["kind"] == "numeric":
            return MetricOutcome("not_applicable", None, {"reason": "numeric_judgment"})
        anchor_set = next(
            item for item in artifact.anchor_sets if item["anchor_set_id"] == scope_id
        )
        if anchor_set["label_space"] != artifact.header["judgment_spec"]["label_space"]:
            return MetricOutcome(
                "missing", None, {"reason": "incompatible_label_spaces"}
            )
        raw = [
            item
            for item in artifact.anchors
            if item["anchor_set_id"] == scope_id and item["kind"] == "raw_annotation"
        ]
        covered = {item["case_id"] for item in raw}
        if len(covered) != len(artifact.cases):
            return MetricOutcome("missing", None, {"reason": "partial_anchor_coverage"})
        count = 0
        role = params["role"]
        for anchor in raw:
            trials = trial_map.get((anchor["case_id"], role), [])
            if (
                len(trials) != 1
                or trials[0]["status"] != "determinate"
                or anchor["status"] != "determinate"
            ):
                return MetricOutcome(
                    "missing",
                    None,
                    {"reason": "non_unique_or_non_determinate_anchor_comparison"},
                )
            count += int(anchor["label"] != trials[0]["label"])
        return MetricOutcome(
            "satisfied", Fraction(count, 1), {"raw_annotation_count": len(raw)}
        )
    if metric == "provenance_present":
        owner = _provenance_owner(artifact, params["owner_type"], scope_id)
        item = None if owner is None else owner.get(params["field"])
        if item is None:
            return MetricOutcome("missing", None, {"presence": "missing"})
        if item["presence"] == "not_applicable":
            return MetricOutcome("not_applicable", None, {"presence": "not_applicable"})
        present = item["presence"] == "present" and (
            item["identity"] is not None or item["sha256"] is not None
        )
        return MetricOutcome("satisfied", present, {"presence": item["presence"]})
    raise AssertionError(f"Unhandled metric: {metric}")


def _compare(operator: str, value: bool | Fraction, threshold: Decimal | None) -> bool:
    if isinstance(value, bool):
        return value if operator == "eq" else not value
    assert threshold is not None
    expected = decimal_to_fraction(threshold)
    return {
        "eq": value == expected,
        "ne": value != expected,
        "lt": value < expected,
        "lte": value <= expected,
        "gt": value > expected,
        "gte": value >= expected,
    }[operator]


def _contract_facts(
    artifact: AssuranceArtifact,
    contract: AssuranceContract | None,
    evidence_status: str,
    isolation_status: str,
    invariance: list[dict[str, Any]],
    trial_map: dict[tuple[str, str], list[dict[str, Any]]],
) -> tuple[str, list[dict[str, Any]]]:
    if contract is None:
        return "NOT_CONFIGURED", []
    if evidence_status != "VALID":
        return "NOT_EVALUATED", []
    hard = False
    review = False
    results: list[dict[str, Any]] = []
    for rule in contract.document["rules"]:
        outcome = _metric_outcome(
            artifact, evidence_status, isolation_status, invariance, rule, trial_map
        )
        state = outcome.state
        if state == "satisfied" and outcome.value is not None:
            state = (
                "satisfied"
                if _compare(rule["operator"], outcome.value, rule["threshold"])
                else "violated"
            )
        if state == "violated":
            hard |= rule["severity"] == "hard"
            review |= rule["severity"] == "review"
        elif state in {"missing", "not_applicable"}:
            hard |= rule["missing_evidence"] == "hard_fail"
            review |= rule["missing_evidence"] == "review"
        value_fact: Any = outcome.value
        if isinstance(outcome.value, Fraction):
            value_fact = fraction_facts(outcome.value)
        results.append(
            {
                "rule_id": rule["rule_id"],
                "severity": rule["severity"],
                "scope": rule["scope"],
                "scope_id": rule["scope_id"],
                "metric": rule["metric"],
                "result": state,
                "value": value_fact,
                "operator": rule["operator"],
                "threshold": rule["threshold"],
                "missing_evidence": rule["missing_evidence"],
                "rationale": rule["rationale"],
                "evidence": outcome.evidence,
            }
        )
    if hard:
        return "HARD_FAILURE", results
    if review:
        return "REVIEW_REQUIRED", results
    return "PASS", results


def _report_status(evidence: str, isolation: str, contract: str) -> str:
    if evidence in {"INVALID", "NOT_COMPARABLE"}:
        return evidence
    if contract == "HARD_FAILURE":
        return "HARD_FAILURE"
    if isolation in {"NOT_ISOLATED", "UNKNOWN"} or contract == "REVIEW_REQUIRED":
        return "REVIEW_REQUIRED"
    if contract == "NOT_CONFIGURED":
        return "CONTRACT_NOT_CONFIGURED"
    return "PASS"


def build_report(
    artifact: AssuranceArtifact, contract: AssuranceContract | None = None
) -> dict[str, Any]:
    """Build the one canonical report model used by every renderer."""

    trial_map = _trials_by_case_role(artifact)
    evidence_status, isolation_status, isolation_findings = _isolation(artifact)
    missing_sides = [
        item["case_id"]
        for item in artifact.cases
        if not trial_map.get((item["case_id"], "baseline"))
        or not trial_map.get((item["case_id"], "candidate"))
    ]
    if missing_sides:
        evidence_status = "NOT_COMPARABLE"
    case_ids = {item["case_id"] for item in artifact.cases}
    tolerance = artifact.header["judgment_spec"]["repeat_score_tolerance"]
    repeat = {
        role: _repeat_fact(case_ids, role, trial_map, tolerance)
        for role in ("baseline", "candidate")
    }
    pairing = _pairing_fact(case_ids, trial_map)
    transitions = _paired_transitions(case_ids, trial_map)
    invariance = _invariance_facts(artifact, trial_map)
    anchors = _anchor_facts(artifact, trial_map)
    critical: list[dict[str, Any]] = []
    for group in artifact.critical_groups:
        members = {
            item["case_id"]
            for item in artifact.cases
            if group["group_id"] in item["critical_group_ids"]
        }
        critical.append(
            {
                "group_id": group["group_id"],
                "member_case_ids": sorted(members),
                "repeat": {
                    role: _repeat_fact(members, role, trial_map, tolerance)
                    for role in ("baseline", "candidate")
                },
                "pairing": _pairing_fact(members, trial_map),
                "transitions": _paired_transitions(members, trial_map),
            }
        )
    contract_status, rules = _contract_facts(
        artifact, contract, evidence_status, isolation_status, invariance, trial_map
    )
    report_status = _report_status(evidence_status, isolation_status, contract_status)
    evaluations = artifact.evaluations_by_role
    provenance_delta = _provenance_delta(
        evaluations["baseline"]["provenance"], evaluations["candidate"]["provenance"]
    )
    component_delta: dict[str, Any] = {}
    for side_name in ("evaluator_components", "context_components"):
        for name in sorted(evaluations["baseline"][side_name]):
            first = evaluations["baseline"][side_name][name]
            second = evaluations["candidate"][side_name][name]
            component_delta[f"{side_name}.{name}"] = _provenance_delta(
                {name: first}, {name: second}, frozenset({name})
            )[name]
    cases: list[dict[str, Any]] = []
    for case in artifact.cases:
        cases.append(
            {
                "case_id": case["case_id"],
                "manifest_position": case["manifest_position"],
                "content_sha256": case["content_sha256"],
                "critical_group_ids": case["critical_group_ids"],
                "invariance_group_ids": case["invariance_group_ids"],
                "display_label": _safe_identity(case["display_label"])
                if case["display_label"] is not None
                else None,
                "trials": {
                    role: [
                        _trial_fact(item)
                        for item in trial_map.get((case["case_id"], role), [])
                    ]
                    for role in ("baseline", "candidate")
                },
            }
        )
    evaluation_facts = {
        role: {
            "evaluation_id": item["evaluation_id"],
            "evaluator_id": item["evaluator_id"],
            "evaluator_version": _safe_identity(item["evaluator_version"]),
            "evaluator_fingerprint_sha256": item["evaluator_fingerprint_sha256"],
            "context_id": item["context_id"],
            "context_fingerprint_sha256": item["context_fingerprint_sha256"],
            "evaluator_components": {
                name: _component_fact(value)
                for name, value in sorted(item["evaluator_components"].items())
            },
            "context_components": {
                name: _component_fact(value)
                for name, value in sorted(item["context_components"].items())
            },
            "provenance": _provenance_fact(item["provenance"]),
        }
        for role, item in evaluations.items()
    }
    limits_fact = {
        "source_sha256": artifact.limits.source_sha256,
        "overrides": artifact.limits.overrides(),
        "nondefault": bool(artifact.limits.overrides()),
    }
    warnings = []
    if isolation_status != "ISOLATED":
        warnings.append(
            "Evaluator-only causal wording is not supported because isolation is not established."
        )
    if missing_sides:
        warnings.append(
            "At least one manifest case lacks baseline or candidate trial evidence."
        )
    if limits_fact["nondefault"]:
        warnings.append("NONDEFAULT_RESOURCE_LIMITS")
    report: dict[str, Any] = {
        "schema_version": "evaluator-assurance-report-v1",
        "assurance_engine_version": "0.2.0.dev0",
        "report_id": None,
        "input": {
            "schema_version": artifact.header["schema_version"],
            "artifact_id": artifact.header["artifact_id"],
            "source_sha256": artifact.source_sha256,
        },
        "contract": None
        if contract is None
        else {
            "schema_version": contract.document["schema_version"],
            "contract_id": contract.document["contract_id"],
            "contract_version": contract.document["contract_version"],
            "source_sha256": contract.source_sha256,
        },
        "evidence_status": evidence_status,
        "isolation_status": isolation_status,
        "contract_status": contract_status,
        "report_status": report_status,
        "corpus": {
            **artifact.header["corpus"],
            "computed_manifest_sha256": artifact.header["corpus"]["manifest_sha256"],
        },
        "judgment_spec": artifact.header["judgment_spec"],
        "component_ownership": artifact.header["component_ownership"],
        "evaluations": evaluation_facts,
        "cases": cases,
        "missing_evaluator_side_case_ids": missing_sides,
        "isolation_findings": isolation_findings,
        "repeat_diagnostics": repeat,
        "pairing": pairing,
        "transitions": transitions,
        "critical_groups": critical,
        "invariance_groups": invariance,
        "anchor_sets": anchors,
        "provenance": {
            "artifact": _provenance_fact(artifact.header["provenance"]),
            "evaluation_delta": provenance_delta,
            "component_delta": component_delta,
        },
        "rule_results": rules,
        "privacy": {
            "mode": "metadata_only",
            "raw_prompts_responses_traces_media_provider_payloads": "omitted",
            "reason_details_error_messages": "presence_hash_only",
            "raw_extensions": "omitted",
            "identifying_annotator_data": "omitted",
            "sanitized_excerpt_tier": "deferred",
        },
        "resource_limits": limits_fact,
        "resource_usage": {
            "input_bytes": artifact.input_bytes,
            "record_count": artifact.record_count,
            "case_count": len(artifact.cases),
            "trial_count": len(artifact.trials),
            "anchor_count": len(artifact.anchors),
        },
        "warnings": warnings,
        "limitations": list(LIMITATIONS),
    }
    report["report_id"] = canonical_sha256(report)[:24]
    return report


def exit_code_for_report(report: dict[str, Any]) -> int:
    return {
        "PASS": 0,
        "CONTRACT_NOT_CONFIGURED": 0,
        "HARD_FAILURE": 2,
        "INVALID": 3,
        "NOT_COMPARABLE": 3,
        "REVIEW_REQUIRED": 4,
    }[report["report_status"]]
