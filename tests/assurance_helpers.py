from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from evalcanary.assurance.constants import (
    FIXED_CONTEXT_COMPONENTS,
    FIXED_EVALUATOR_COMPONENTS,
)
from evalcanary.assurance.numeric import canonical_json_text
from evalcanary.assurance.schema import compute_manifest_sha256

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def component(identity: str | None = "same") -> dict[str, Any]:
    if identity is None:
        return {"presence": "not_applicable", "identity": None, "sha256": None}
    return {"presence": "present", "identity": identity, "sha256": None}


def provenance(**values: str) -> dict[str, Any]:
    return {name: component(value) for name, value in values.items()}


def _evaluation(role: str) -> dict[str, Any]:
    evaluator = {name: component(None) for name in FIXED_EVALUATOR_COMPONENTS}
    evaluator["implementation"] = component(f"{role}-implementation")
    evaluator["aggregation_policy"] = component(f"{role}-policy")
    context = {name: component(None) for name in FIXED_CONTEXT_COMPONENTS}
    context["runtime"] = component("python-3.13")
    context["parser"] = component("strict-jsonl-v1")
    return {
        "evaluation_id": f"eval-{role}",
        "role": role,
        "evaluator_id": f"evaluator-{role}",
        "evaluator_version": "1",
        "evaluator_fingerprint_sha256": HASH_A if role == "baseline" else HASH_B,
        "evaluator_components": evaluator,
        "context_id": "context-shared",
        "context_fingerprint_sha256": HASH_C,
        "context_components": context,
        "provenance": provenance(
            evaluator_source=f"{role}-source",
            source_url="https://example.com/source",
        ),
    }


def trial(
    case_id: str,
    role: str,
    *,
    label: str | None = "pass",
    status: str = "determinate",
    score: Any = None,
    source_order: int = 0,
    pairing_key: str | None = "pair",
) -> dict[str, Any]:
    error = (
        {"error_class": "ParserError", "message": "private message"}
        if status == "error"
        else None
    )
    return {
        "record_type": "trial",
        "case_id": case_id,
        "evaluation_id": f"eval-{role}",
        "trial_id": f"{case_id}-{role}-{source_order}",
        "source_order": source_order,
        "pairing_key": pairing_key,
        "status": status,
        "label": label if status == "determinate" else None,
        "score": score,
        "reason": "secret reason",
        "details": {"request_id": "provider-secret", "note": "private"},
        "error": error,
        "provenance": provenance(source_row=f"row-{source_order}"),
        "extensions": {},
    }


def records(
    *,
    relation: str | None = "same_label",
    with_anchors: bool = False,
    numeric: bool = False,
) -> list[dict[str, Any]]:
    judgment = {
        "judgment_spec_id": "judgment-v1",
        "kind": "categorical_and_numeric" if numeric else "categorical",
        "label_space": ["pass", "fail"],
        "score_spec": (
            {
                "scale_id": "score-v1",
                "domain_min": 0,
                "domain_max": 10,
                "direction": "higher_is_better",
                "comparison": "delta",
                "valid_statuses": ["determinate"],
                "threshold_relationship": None,
            }
            if numeric
            else None
        ),
        "repeat_score_tolerance": 1 if numeric else None,
    }
    header = {
        "record_type": "header",
        "schema_version": "evaluator-assurance-input-v1",
        "artifact_id": "artifact-1",
        "corpus": {
            "corpus_id": "corpus-1",
            "manifest_sha256": "0" * 64,
            "case_count": 2,
            "identity_level": "content_hashes",
            "manifest_algorithm": "evaluator-assurance-manifest-v1",
        },
        "judgment_spec": judgment,
        "evaluations": [_evaluation("baseline"), _evaluation("candidate")],
        "component_ownership": {"parser": "context", "aggregation_policy": "evaluator"},
        "allowed_context_differences": [],
        "provenance": provenance(
            corpus_source="fixture",
            corpus_revision="revision-1",
            original_artifact_hash="artifact-hash",
            license_url="https://example.com/license",
        ),
        "extensions": {},
    }
    case_records = [
        {
            "record_type": "case",
            "case_id": "case-1",
            "manifest_position": 0,
            "content_sha256": HASH_A,
            "critical_group_ids": ["critical-1"],
            "invariance_group_ids": ["invariance-1"] if relation else [],
            "tags": [],
            "display_label": None,
            "extensions": {},
        },
        {
            "record_type": "case",
            "case_id": "case-2",
            "manifest_position": 1,
            "content_sha256": HASH_B,
            "critical_group_ids": [],
            "invariance_group_ids": ["invariance-1"] if relation else [],
            "tags": [],
            "display_label": None,
            "extensions": {},
        },
    ]
    critical = {
        "record_type": "critical_group",
        "group_id": "critical-1",
        "title": "Critical fixture",
        "declaration_source": "test",
        "rationale": "non-cancelable control",
        "extensions": {},
    }
    invariance_records: list[dict[str, Any]] = []
    if relation:
        parameters: dict[str, Any] = {}
        if relation == "swapped_preference":
            parameters = {"first_label": "pass", "second_label": "fail"}
        elif relation == "same_score_within_tolerance":
            parameters = {"absolute_tolerance": 1}
        invariance_records.append(
            {
                "record_type": "invariance_group",
                "group_id": "invariance-1",
                "member_case_ids": ["case-1", "case-2"],
                "transformation_id": "transformation-1",
                "transformation_version": "1",
                "expected_relation": relation,
                "relation_parameters": parameters,
                "severity": "hard",
                "declaration_source": "test",
                "rationale": "declared relation only",
                "extensions": {},
            }
        )
    trial_records = [
        trial("case-1", "baseline", score=1 if numeric else None),
        trial("case-1", "candidate", score=2 if numeric else None),
        trial("case-2", "baseline", score=1 if numeric else None),
        trial("case-2", "candidate", score=2 if numeric else None),
    ]
    anchor_set_records: list[dict[str, Any]] = []
    anchor_records: list[dict[str, Any]] = []
    if with_anchors:
        anchor_set_records.append(
            {
                "record_type": "anchor_set",
                "anchor_set_id": "anchors-1",
                "label_space": ["pass", "fail"],
                "protocol_id": "protocol-1",
                "protocol_version": "1",
                "aggregation_method": "none",
                "clustering_unit": "case",
                "source_revision": "revision-1",
                "source_sha256": HASH_C,
                "license": "CC-BY-4.0",
                "provenance": provenance(corpus_source="human-fixture"),
                "extensions": {},
            }
        )
        for index, case_id in enumerate(("case-1", "case-2")):
            anchor_records.append(
                {
                    "record_type": "anchor",
                    "anchor_id": f"anchor-{index}",
                    "anchor_set_id": "anchors-1",
                    "case_id": case_id,
                    "cluster_id": f"cluster-{index}",
                    "annotation_id": f"annotation-{index}",
                    "annotator_id": f"person-{index}",
                    "kind": "raw_annotation",
                    "status": "determinate",
                    "label": "pass",
                    "reason": None,
                    "aggregation_inputs": [],
                    "adjudication_rationale": None,
                    "provenance": provenance(source_row=f"human-row-{index}"),
                    "extensions": {},
                }
            )
    header["corpus"]["manifest_sha256"] = compute_manifest_sha256(
        header, case_records, [critical], invariance_records
    )
    return [
        header,
        critical,
        *invariance_records,
        *anchor_set_records,
        *case_records,
        *trial_records,
        *anchor_records,
    ]


def refresh_manifest(items: list[dict[str, Any]]) -> None:
    header = items[0]
    cases = [item for item in items if item["record_type"] == "case"]
    critical = [item for item in items if item["record_type"] == "critical_group"]
    invariance = [item for item in items if item["record_type"] == "invariance_group"]
    header["corpus"]["manifest_sha256"] = compute_manifest_sha256(
        header, cases, critical, invariance
    )


def write_records(path: Path, items: list[dict[str, Any]]) -> Path:
    path.write_text(
        "\n".join(canonical_json_text(item) for item in items) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def contract(*rules: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "evaluator-assurance-contract-v1",
        "contract_id": "contract-1",
        "contract_version": "1",
        "applies_to_input_schema": "evaluator-assurance-input-v1",
        "rules": list(rules),
        "extensions": {},
    }


def rule(
    metric: str,
    *,
    scope: str = "all_cases",
    scope_id: str | None = None,
    parameters: dict[str, Any] | None = None,
    operator: str = "eq",
    threshold: Any = 0,
    severity: str = "hard",
    missing_evidence: str = "hard_fail",
) -> dict[str, Any]:
    if metric in {"corpus_equal", "context_isolated", "provenance_present"}:
        threshold = None
    return {
        "rule_id": f"rule-{metric}",
        "severity": severity,
        "scope": scope,
        "scope_id": scope_id,
        "metric": metric,
        "operator": operator,
        "threshold": threshold,
        "parameters": parameters or {},
        "missing_evidence": missing_evidence,
        "rationale": f"Exercise {metric}.",
        "extensions": {},
    }


def write_json(path: Path, value: dict[str, Any]) -> Path:
    path.write_text(canonical_json_text(value) + "\n", encoding="utf-8", newline="\n")
    return path


def clone_records(**kwargs: Any) -> list[dict[str, Any]]:
    return deepcopy(records(**kwargs))


def pure_numeric_records() -> list[dict[str, Any]]:
    """Return a valid numeric-only artifact with no categorical label space."""

    items = clone_records(relation=None, numeric=True)
    items[0]["judgment_spec"]["kind"] = "numeric"
    items[0]["judgment_spec"]["label_space"] = None
    for item in items:
        if item.get("record_type") == "trial":
            item["label"] = None
    refresh_manifest(items)
    return items
