"""Shared structural registry and deterministic Draft 2020-12 schemas."""

from __future__ import annotations

from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path
from typing import Any

from ..errors import InputValidationError
from .constants import (
    CONTRACT_SCHEMA,
    FIXED_CONTEXT_COMPONENTS,
    FIXED_EVALUATOR_COMPONENTS,
    INPUT_SCHEMA,
    MANIFEST_ALGORITHM,
    METRICS,
    MOVABLE_COMPONENTS,
    OPERATORS,
    PRESENCES,
    PROVENANCE_FIELDS,
    RECORD_TYPES,
    RELATIONS,
    REPORT_SCHEMA,
    ROLES,
    RULE_RESULTS,
    SCOPES,
    SEVERITIES,
    STATUSES,
)
from .numeric import canonical_json_bytes
from .review_queue import (
    DISPOSITION_SOURCES,
    REASON_RANKS,
    REVIEW_QUEUE_SCHEMA,
)

STRUCTURAL_SCHEMA = "STRUCTURAL_SCHEMA"
RUNTIME_SEMANTICS = "RUNTIME_SEMANTICS"

SCHEMA_FILENAMES = {
    "input-record": "evaluator-assurance-input-record-v1.schema.json",
    "contract": "evaluator-assurance-contract-v1.schema.json",
    "report": "evaluator-assurance-report-v1.schema.json",
    "review-queue": "evaluator-assurance-review-queue-v1.schema.json",
}

RUNTIME_ONLY_FACTS = (
    "JSONL byte encoding, line bounds, header order, and duplicate JSON keys",
    "corpus-manifest recomputation and cross-record identity/reference integrity",
    "pairing completeness, trial ordering, and component ownership",
    "exact context comparability and allowed-difference matching",
    "contract metric evaluation, missingness, and report-status precedence",
    "Decimal identity canonicalization and whole-artifact resource limits",
)

FIELD_REGISTRY: dict[str, frozenset[str]] = {
    "component_value": frozenset({"presence", "identity", "sha256"}),
    "header": frozenset(
        {
            "record_type",
            "schema_version",
            "artifact_id",
            "corpus",
            "judgment_spec",
            "evaluations",
            "component_ownership",
            "allowed_context_differences",
            "provenance",
            "extensions",
        }
    ),
    "corpus": frozenset(
        {
            "corpus_id",
            "manifest_sha256",
            "case_count",
            "identity_level",
            "manifest_algorithm",
        }
    ),
    "judgment_spec": frozenset(
        {
            "judgment_spec_id",
            "kind",
            "label_space",
            "score_spec",
            "repeat_score_tolerance",
        }
    ),
    "score_spec": frozenset(
        {
            "scale_id",
            "domain_min",
            "domain_max",
            "direction",
            "comparison",
            "valid_statuses",
            "threshold_relationship",
        }
    ),
    "threshold_relationship": frozenset(
        {"operator", "threshold", "below_label", "above_label"}
    ),
    "evaluation": frozenset(
        {
            "evaluation_id",
            "role",
            "evaluator_id",
            "evaluator_version",
            "evaluator_fingerprint_sha256",
            "evaluator_components",
            "context_id",
            "context_fingerprint_sha256",
            "context_components",
            "provenance",
        }
    ),
    "component_ownership": frozenset(MOVABLE_COMPONENTS),
    "context_difference": frozenset(
        {
            "component",
            "expected_baseline_component_value",
            "expected_candidate_component_value",
            "rationale",
            "reviewer_id",
            "disposition",
        }
    ),
    "case": frozenset(
        {
            "record_type",
            "case_id",
            "manifest_position",
            "content_sha256",
            "critical_group_ids",
            "invariance_group_ids",
            "tags",
            "display_label",
            "extensions",
        }
    ),
    "trial": frozenset(
        {
            "record_type",
            "case_id",
            "evaluation_id",
            "trial_id",
            "source_order",
            "pairing_key",
            "status",
            "label",
            "score",
            "reason",
            "details",
            "error",
            "provenance",
            "extensions",
        }
    ),
    "critical_group": frozenset(
        {"record_type", "group_id", "title", "declaration_source", "rationale", "extensions"}
    ),
    "invariance_group": frozenset(
        {
            "record_type",
            "group_id",
            "member_case_ids",
            "transformation_id",
            "transformation_version",
            "expected_relation",
            "relation_parameters",
            "severity",
            "declaration_source",
            "rationale",
            "extensions",
        }
    ),
    "anchor_set": frozenset(
        {
            "record_type",
            "anchor_set_id",
            "label_space",
            "protocol_id",
            "protocol_version",
            "aggregation_method",
            "clustering_unit",
            "source_revision",
            "source_sha256",
            "license",
            "provenance",
            "extensions",
        }
    ),
    "anchor": frozenset(
        {
            "record_type",
            "anchor_id",
            "anchor_set_id",
            "case_id",
            "cluster_id",
            "annotation_id",
            "annotator_id",
            "kind",
            "status",
            "label",
            "reason",
            "aggregation_inputs",
            "adjudication_rationale",
            "provenance",
            "extensions",
        }
    ),
    "contract": frozenset(
        {"schema_version", "contract_id", "contract_version", "applies_to_input_schema", "rules", "extensions"}
    ),
    "rule": frozenset(
        {
            "rule_id",
            "severity",
            "scope",
            "scope_id",
            "metric",
            "operator",
            "threshold",
            "parameters",
            "missing_evidence",
            "rationale",
            "extensions",
        }
    ),
}

METRIC_SIGNATURES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "corpus_equal": (frozenset({"all_cases"}), frozenset()),
    "context_isolated": (frozenset({"all_cases"}), frozenset()),
    "determinate_coverage": (
        frozenset({"all_cases", "critical_group"}),
        frozenset({"role"}),
    ),
    "determinate_coverage_delta": (
        frozenset({"all_cases", "critical_group"}),
        frozenset(),
    ),
    "status_count": (
        frozenset({"all_cases", "critical_group"}),
        frozenset({"role", "status"}),
    ),
    "new_status_count": (
        frozenset({"all_cases", "critical_group"}),
        frozenset({"status"}),
    ),
    "determinate_label_count": (
        frozenset({"all_cases", "critical_group"}),
        frozenset({"role", "label"}),
    ),
    "determinate_label_transition_count": (
        frozenset({"all_cases", "critical_group"}),
        frozenset({"from_label", "to_label"}),
    ),
    "critical_regression_count": (
        frozenset({"critical_group"}),
        frozenset({"from_label", "to_label"}),
    ),
    "unstable_case_count": (
        frozenset({"all_cases", "critical_group"}),
        frozenset({"role", "dimension"}),
    ),
    "invariance_violation_count": (
        frozenset({"all_cases", "invariance_group"}),
        frozenset({"role"}),
    ),
    "invariance_not_evaluable_count": (
        frozenset({"all_cases", "invariance_group"}),
        frozenset({"role"}),
    ),
    "anchor_coverage": (frozenset({"anchor_set"}), frozenset()),
    "anchor_disagreement_count": (frozenset({"anchor_set"}), frozenset({"role"})),
    "provenance_present": (
        frozenset({"provenance"}),
        frozenset({"owner_type", "field"}),
    ),
    "score_delta": (frozenset({"all_cases", "critical_group"}), frozenset()),
}


def _sorted(values: Iterable[str]) -> list[str]:
    return sorted(values)


def _object(
    properties: dict[str, Any],
    *,
    required: Iterable[str] | None = None,
    additional: bool | dict[str, Any] = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional,
    }
    if required is not None:
        result["required"] = _sorted(required)
    return result


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/$defs/{name}"}


def _base(schema_id: str, title: str) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:evalcanary:schema:{schema_id}",
        "title": title,
        "x-evalcanary-validation-layers": {
            STRUCTURAL_SCHEMA: "This document validates one JSON value's structure.",
            RUNTIME_SEMANTICS: list(RUNTIME_ONLY_FACTS),
        },
    }


def _common_defs() -> dict[str, Any]:
    component_names = (
        set(FIXED_EVALUATOR_COMPONENTS)
        | set(FIXED_CONTEXT_COMPONENTS)
        | set(MOVABLE_COMPONENTS)
    )
    return {
        "id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "label": {"type": "string", "minLength": 1, "maxLength": 64},
        "extensions": {
            "type": "object",
            "propertyNames": {"pattern": "^[a-z0-9]+(?:[.-][a-z0-9]+)+$"},
        },
        "component_value": _object(
            {
                "presence": {"enum": _sorted(PRESENCES)},
                "identity": _nullable({"type": "string"}),
                "sha256": _nullable(_ref("sha256")),
            },
            required=FIELD_REGISTRY["component_value"],
        ),
        "provenance": {
            "type": "object",
            "propertyNames": {"enum": _sorted(PROVENANCE_FIELDS)},
            "additionalProperties": _ref("component_value"),
        },
        "component_map": {
            "type": "object",
            "propertyNames": {"enum": _sorted(component_names)},
            "additionalProperties": _ref("component_value"),
        },
    }


def _input_schema() -> dict[str, Any]:
    schema = _base(
        "evaluator-assurance-input-record-v1",
        "EvalCanary evaluator-assurance JSONL record",
    )
    defs = _common_defs()
    text = {"type": "string"}
    nullable_text = _nullable(text)
    label_array = {
        "type": "array",
        "items": _ref("label"),
        "minItems": 2,
        "maxItems": 64,
        "uniqueItems": True,
    }
    threshold_relationship = _object(
        {
            "operator": {"enum": ["gt", "gte", "lt", "lte"]},
            "threshold": {"type": "number"},
            "below_label": _ref("label"),
            "above_label": _ref("label"),
        },
        required=FIELD_REGISTRY["threshold_relationship"],
    )
    score_spec = _object(
        {
            "scale_id": _ref("id"),
            "domain_min": {"type": "number"},
            "domain_max": {"type": "number"},
            "direction": {
                "enum": ["higher_is_better", "lower_is_better", "none"]
            },
            "comparison": {"enum": ["delta", "none"]},
            "valid_statuses": {
                "type": "array",
                "items": {
                    "enum": ["abstain", "determinate", "indeterminate"]
                },
                "minItems": 1,
                "uniqueItems": True,
            },
            "threshold_relationship": _nullable(threshold_relationship),
        },
        required=FIELD_REGISTRY["score_spec"],
    )
    judgment_spec = _object(
        {
            "judgment_spec_id": _ref("id"),
            "kind": {
                "enum": ["categorical", "categorical_and_numeric", "numeric"]
            },
            "label_space": _nullable(label_array),
            "score_spec": _nullable(score_spec),
            "repeat_score_tolerance": _nullable(
                {"type": "number", "minimum": 0}
            ),
        },
        required=FIELD_REGISTRY["judgment_spec"],
    )
    judgment_spec["allOf"] = [
        {
            "if": {"properties": {"kind": {"const": "categorical"}}},
            "then": {
                "properties": {
                    "label_space": label_array,
                    "score_spec": {"type": "null"},
                }
            },
        },
        {
            "if": {"properties": {"kind": {"const": "numeric"}}},
            "then": {
                "properties": {
                    "label_space": {"type": "null"},
                    "score_spec": score_spec,
                }
            },
        },
        {
            "if": {
                "properties": {"kind": {"const": "categorical_and_numeric"}}
            },
            "then": {
                "properties": {"label_space": label_array, "score_spec": score_spec}
            },
        },
    ]
    corpus = _object(
        {
            "corpus_id": _ref("id"),
            "manifest_sha256": _ref("sha256"),
            "case_count": {"type": "integer", "minimum": 1},
            "identity_level": {
                "enum": ["case_ids", "content_hashes", "full_artifact"]
            },
            "manifest_algorithm": {"const": MANIFEST_ALGORITHM},
        },
        required=FIELD_REGISTRY["corpus"],
    )
    evaluation = _object(
        {
            "evaluation_id": _ref("id"),
            "role": {"enum": _sorted(ROLES)},
            "evaluator_id": _ref("id"),
            "evaluator_version": text,
            "evaluator_fingerprint_sha256": _ref("sha256"),
            "evaluator_components": _ref("component_map"),
            "context_id": _ref("id"),
            "context_fingerprint_sha256": _ref("sha256"),
            "context_components": _ref("component_map"),
            "provenance": _ref("provenance"),
        },
        required=FIELD_REGISTRY["evaluation"],
    )
    context_difference = _object(
        {
            "component": {
                "enum": _sorted(set(FIXED_CONTEXT_COMPONENTS) | set(MOVABLE_COMPONENTS))
            },
            "expected_baseline_component_value": _ref("component_value"),
            "expected_candidate_component_value": _ref("component_value"),
            "rationale": text,
            "reviewer_id": _ref("id"),
            "disposition": {"const": "not_isolated_review_required"},
        },
        required=FIELD_REGISTRY["context_difference"],
    )
    header = _object(
        {
            "record_type": {"const": "header"},
            "schema_version": {"const": INPUT_SCHEMA},
            "artifact_id": _ref("id"),
            "corpus": corpus,
            "judgment_spec": judgment_spec,
            "evaluations": {
                "type": "array",
                "items": evaluation,
                "minItems": 2,
                "maxItems": 2,
                "allOf": [
                    {"contains": {"properties": {"role": {"const": role}}}}
                    for role in _sorted(ROLES)
                ],
            },
            "component_ownership": _object(
                {
                    name: {"enum": ["context", "evaluator"]}
                    for name in _sorted(MOVABLE_COMPONENTS)
                },
                required=FIELD_REGISTRY["component_ownership"],
            ),
            "allowed_context_differences": {
                "type": "array",
                "items": context_difference,
            },
            "provenance": _ref("provenance"),
            "extensions": _ref("extensions"),
        },
        required=FIELD_REGISTRY["header"],
    )
    case = _object(
        {
            "record_type": {"const": "case"},
            "case_id": _ref("id"),
            "manifest_position": {"type": "integer", "minimum": 0},
            "content_sha256": _nullable(_ref("sha256")),
            "critical_group_ids": {
                "type": "array",
                "items": _ref("id"),
                "uniqueItems": True,
            },
            "invariance_group_ids": {
                "type": "array",
                "items": _ref("id"),
                "uniqueItems": True,
            },
            "tags": {"type": "array", "items": text, "uniqueItems": True},
            "display_label": nullable_text,
            "extensions": _ref("extensions"),
        },
        required=FIELD_REGISTRY["case"],
    )
    error = _nullable(
        _object(
            {
                "error_class": {
                    "type": "string",
                    "pattern": "^[A-Za-z][A-Za-z0-9_.:-]{0,127}$",
                },
                "message": text,
            },
            required={"error_class"},
        )
    )
    trial = _object(
        {
            "record_type": {"const": "trial"},
            "case_id": _ref("id"),
            "evaluation_id": _ref("id"),
            "trial_id": _ref("id"),
            "source_order": {"type": "integer", "minimum": 0},
            "pairing_key": _nullable(_ref("id")),
            "status": {"enum": _sorted(STATUSES)},
            "label": _nullable(_ref("label")),
            "score": _nullable({"type": "number"}),
            "reason": nullable_text,
            "details": {},
            "error": error,
            "provenance": _ref("provenance"),
            "extensions": _ref("extensions"),
        },
        required=FIELD_REGISTRY["trial"],
    )
    critical_group = _object(
        {
            "record_type": {"const": "critical_group"},
            "group_id": _ref("id"),
            "title": text,
            "declaration_source": text,
            "rationale": text,
            "extensions": _ref("extensions"),
        },
        required=FIELD_REGISTRY["critical_group"],
    )
    relation_parameters = {
        "oneOf": [
            _object({}, required=set()),
            _object(
                {
                    "first_label": _ref("label"),
                    "second_label": _ref("label"),
                    "tie_label": _ref("label"),
                },
                required={"first_label", "second_label"},
            ),
            _object(
                {"absolute_tolerance": {"type": "number", "minimum": 0}},
                required={"absolute_tolerance"},
            ),
        ]
    }
    invariance_group = _object(
        {
            "record_type": {"const": "invariance_group"},
            "group_id": _ref("id"),
            "member_case_ids": {
                "type": "array",
                "items": _ref("id"),
                "minItems": 2,
                "uniqueItems": True,
            },
            "transformation_id": _ref("id"),
            "transformation_version": _ref("id"),
            "expected_relation": {"enum": _sorted(RELATIONS)},
            "relation_parameters": relation_parameters,
            "severity": {"enum": _sorted(SEVERITIES)},
            "declaration_source": text,
            "rationale": text,
            "extensions": _ref("extensions"),
        },
        required=FIELD_REGISTRY["invariance_group"],
    )
    anchor_set = _object(
        {
            "record_type": {"const": "anchor_set"},
            "anchor_set_id": _ref("id"),
            "label_space": label_array,
            "protocol_id": _ref("id"),
            "protocol_version": _ref("id"),
            "aggregation_method": {
                "enum": ["adjudicated", "caller_supplied", "majority", "none"]
            },
            "clustering_unit": text,
            "source_revision": text,
            "source_sha256": _ref("sha256"),
            "license": text,
            "provenance": _ref("provenance"),
            "extensions": _ref("extensions"),
        },
        required=FIELD_REGISTRY["anchor_set"],
    )
    anchor = _object(
        {
            "record_type": {"const": "anchor"},
            "anchor_id": _ref("id"),
            "anchor_set_id": _ref("id"),
            "case_id": _ref("id"),
            "cluster_id": _ref("id"),
            "annotation_id": _ref("id"),
            "annotator_id": _nullable(_ref("id")),
            "kind": {"enum": ["aggregate", "raw_annotation"]},
            "status": {"enum": _sorted(STATUSES - {"error"})},
            "label": _nullable(_ref("label")),
            "reason": nullable_text,
            "aggregation_inputs": {
                "type": "array",
                "items": _ref("id"),
                "uniqueItems": True,
            },
            "adjudication_rationale": nullable_text,
            "provenance": _ref("provenance"),
            "extensions": _ref("extensions"),
        },
        required=FIELD_REGISTRY["anchor"],
    )
    defs.update(
        {
            "header": header,
            "case": case,
            "trial": trial,
            "critical_group": critical_group,
            "invariance_group": invariance_group,
            "anchor_set": anchor_set,
            "anchor": anchor,
        }
    )
    schema["$defs"] = defs
    schema["oneOf"] = [_ref(name) for name in _sorted(RECORD_TYPES)]
    return schema


def _parameter_schema(names: frozenset[str]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for name in names:
        if name == "role":
            properties[name] = {"enum": _sorted(ROLES)}
        elif name == "status":
            properties[name] = {"enum": _sorted(STATUSES)}
        elif name == "dimension":
            properties[name] = {"enum": ["label", "score", "status"]}
        elif name == "owner_type":
            properties[name] = {
                "enum": ["anchor", "anchor_set", "artifact", "evaluation", "trial"]
            }
        elif name == "field":
            properties[name] = {"enum": _sorted(PROVENANCE_FIELDS)}
        else:
            properties[name] = {"type": "string", "minLength": 1, "maxLength": 64}
    return _object(properties, required=names)


def _contract_schema() -> dict[str, Any]:
    schema = _base(CONTRACT_SCHEMA, "EvalCanary evaluator-assurance contract")
    schema["$defs"] = _common_defs()
    rule = _object(
        {
            "rule_id": _ref("id"),
            "severity": {"enum": _sorted(SEVERITIES)},
            "scope": {"enum": _sorted(SCOPES)},
            "scope_id": _nullable(_ref("id")),
            "metric": {"enum": _sorted(METRICS)},
            "operator": {"enum": _sorted(OPERATORS)},
            "threshold": _nullable({"type": "number"}),
            "parameters": {"type": "object"},
            "missing_evidence": {"enum": ["hard_fail", "info", "review"]},
            "rationale": {"type": "string"},
            "extensions": _ref("extensions"),
        },
        required=FIELD_REGISTRY["rule"],
    )
    rule["allOf"] = [
        {
            "if": {"properties": {"metric": {"const": metric}}},
            "then": {
                "properties": {
                    "scope": {"enum": _sorted(scopes)},
                    "parameters": _parameter_schema(parameters),
                }
            },
        }
        for metric, (scopes, parameters) in sorted(METRIC_SIGNATURES.items())
    ]
    boolean_metrics = ["corpus_equal", "context_isolated", "provenance_present"]
    rule["allOf"].append(
        {
            "if": {"properties": {"metric": {"enum": boolean_metrics}}},
            "then": {
                "properties": {
                    "operator": {"enum": ["eq", "ne"]},
                    "threshold": {"type": "null"},
                }
            },
            "else": {"properties": {"threshold": {"type": "number"}}},
        }
    )
    schema.update(
        _object(
            {
                "schema_version": {"const": CONTRACT_SCHEMA},
                "contract_id": _ref("id"),
                "contract_version": _ref("id"),
                "applies_to_input_schema": {"const": INPUT_SCHEMA},
                "rules": {"type": "array", "items": rule, "minItems": 1},
                "extensions": _ref("extensions"),
            },
            required=FIELD_REGISTRY["contract"],
        )
    )
    return schema


def _report_schema() -> dict[str, Any]:
    schema = _base(REPORT_SCHEMA, "EvalCanary evaluator-assurance report")
    defs = _common_defs()
    defs.update(
        {
            "string_array": {"type": "array", "items": {"type": "string"}},
            "object_array": {"type": "array", "items": {"type": "object"}},
            "string_map": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
        }
    )
    schema["$defs"] = defs
    report_fields = frozenset(
        {
            "schema_version",
            "assurance_engine_version",
            "report_id",
            "input",
            "contract",
            "evidence_status",
            "isolation_status",
            "contract_status",
            "report_status",
            "corpus",
            "judgment_spec",
            "component_ownership",
            "evaluations",
            "cases",
            "missing_evaluator_side_case_ids",
            "isolation_findings",
            "repeat_diagnostics",
            "pairing",
            "transitions",
            "critical_groups",
            "invariance_groups",
            "anchor_sets",
            "provenance",
            "rule_results",
            "privacy",
            "resource_limits",
            "resource_usage",
            "warnings",
            "limitations",
        }
    )
    input_fact = _object(
        {
            "schema_version": {"const": INPUT_SCHEMA},
            "artifact_id": _ref("id"),
            "source_sha256": _ref("sha256"),
        },
        required={"schema_version", "artifact_id", "source_sha256"},
    )
    contract_fact = _nullable(
        _object(
            {
                "schema_version": {"const": CONTRACT_SCHEMA},
                "contract_id": _ref("id"),
                "contract_version": _ref("id"),
                "source_sha256": _ref("sha256"),
            },
            required={
                "schema_version",
                "contract_id",
                "contract_version",
                "source_sha256",
            },
        )
    )
    corpus = _object(
        {
            "corpus_id": _ref("id"),
            "manifest_sha256": _ref("sha256"),
            "case_count": {"type": "integer", "minimum": 1},
            "identity_level": {
                "enum": ["case_ids", "content_hashes", "full_artifact"]
            },
            "manifest_algorithm": {"const": MANIFEST_ALGORITHM},
            "computed_manifest_sha256": _ref("sha256"),
        },
        required=set(FIELD_REGISTRY["corpus"]) | {"computed_manifest_sha256"},
    )
    rule_result = _object(
        {
            "rule_id": _ref("id"),
            "severity": {"enum": _sorted(SEVERITIES)},
            "scope": {"enum": _sorted(SCOPES)},
            "scope_id": _nullable(_ref("id")),
            "metric": {"enum": _sorted(METRICS)},
            "operator": {"enum": _sorted(OPERATORS)},
            "threshold": {},
            "parameters": {"type": "object"},
            "missing_evidence": {"enum": ["hard_fail", "info", "review"]},
            "result": {"enum": _sorted(RULE_RESULTS)},
            "value": {},
            "rationale": {"type": "string"},
            "evidence": {"type": "object"},
        },
        required={
            "rule_id",
            "severity",
            "scope",
            "scope_id",
            "metric",
            "operator",
            "threshold",
            "parameters",
            "missing_evidence",
            "result",
            "value",
            "rationale",
            "evidence",
        },
    )
    schema.update(
        _object(
            {
                "schema_version": {"const": REPORT_SCHEMA},
                "assurance_engine_version": {"type": "string"},
                "report_id": {"type": "string", "pattern": "^[0-9a-f]{24}$"},
                "input": input_fact,
                "contract": contract_fact,
                "evidence_status": {
                    "enum": ["INVALID", "NOT_COMPARABLE", "VALID"]
                },
                "isolation_status": {
                    "enum": ["ISOLATED", "NOT_ISOLATED", "NOT_ESTABLISHED"]
                },
                "contract_status": {
                    "enum": [
                        "HARD_FAILURE",
                        "NOT_CONFIGURED",
                        "PASS",
                        "REVIEW_REQUIRED",
                    ]
                },
                "report_status": {
                    "enum": [
                        "CONTRACT_NOT_CONFIGURED",
                        "HARD_FAILURE",
                        "INVALID",
                        "NOT_COMPARABLE",
                        "PASS",
                        "REVIEW_REQUIRED",
                    ]
                },
                "corpus": corpus,
                "judgment_spec": {"type": "object"},
                "component_ownership": {"type": "object"},
                "evaluations": {"type": "object"},
                "cases": _ref("object_array"),
                "missing_evaluator_side_case_ids": _ref("string_array"),
                "isolation_findings": _ref("object_array"),
                "repeat_diagnostics": {"type": "object"},
                "pairing": {"type": "object"},
                "transitions": {"type": "object"},
                "critical_groups": _ref("object_array"),
                "invariance_groups": _ref("object_array"),
                "anchor_sets": _ref("object_array"),
                "provenance": {"type": "object"},
                "rule_results": {"type": "array", "items": rule_result},
                "privacy": {"type": "object"},
                "resource_limits": {"type": "object"},
                "resource_usage": {"type": "object"},
                "warnings": _ref("string_array"),
                "limitations": _ref("string_array"),
            },
            required=report_fields,
        )
    )
    return schema


def _review_queue_schema() -> dict[str, Any]:
    schema = _base(REVIEW_QUEUE_SCHEMA, "EvalCanary evaluator-assurance review queue")
    defs = _common_defs()
    queue_fields = frozenset(
        {
            "schema_version",
            "source_report_id",
            "source_report_sha256",
            "generated_by",
            "item_count",
            "counts_by_review_rank",
            "counts_by_reason",
            "counts_by_disposition_source",
            "invariance_summary",
            "workload_summary",
            "items",
        }
    )
    item_fields = frozenset(
        {
            "queue_item_id",
            "review_rank",
            "reason_code",
            "subject_type",
            "subject_id",
            "related_subject_ids",
            "role",
            "pairing_key",
            "rule_id",
            "disposition_source",
            "contract_severity",
            "contract_result",
            "facts",
            "source_pointers",
        }
    )
    count_map = {
        "type": "object",
        "additionalProperties": {"type": "integer", "minimum": 0},
    }
    invariance_role_summary = _object(
        {
            "satisfied": {"type": "integer", "minimum": 0},
            "violated": {"type": "integer", "minimum": 0},
            "not_evaluable": {"type": "integer", "minimum": 0},
            "declared_policy_not_evaluable": {"type": "integer", "minimum": 0},
        },
        required={
            "satisfied",
            "violated",
            "not_evaluable",
            "declared_policy_not_evaluable",
        },
    )
    workload_summary = _object(
        {
            "items": {"type": "integer", "minimum": 0},
            "unique_cases": {"type": "integer", "minimum": 0},
            "unique_trials": {"type": "integer", "minimum": 0},
            "unique_invariance_groups": {"type": "integer", "minimum": 0},
            "unique_rules": {"type": "integer", "minimum": 0},
            "unique_anchors": {"type": "integer", "minimum": 0},
            "overall_unique_logical_subjects": {
                "type": "integer",
                "minimum": 0,
            },
            "logical_subject_identity": {"const": "subject_type+subject_id"},
        },
        required={
            "items",
            "unique_cases",
            "unique_trials",
            "unique_invariance_groups",
            "unique_rules",
            "unique_anchors",
            "overall_unique_logical_subjects",
            "logical_subject_identity",
        },
    )
    item = _object(
        {
            "queue_item_id": _ref("sha256"),
            "review_rank": {
                "type": "integer",
                "enum": sorted(set(REASON_RANKS.values())),
            },
            "reason_code": {"enum": _sorted(REASON_RANKS)},
            "subject_type": {"type": "string", "minLength": 1},
            "subject_id": {"type": "string", "minLength": 1},
            "related_subject_ids": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
            },
            "role": _nullable({"enum": _sorted(ROLES)}),
            "pairing_key": _nullable({"type": "string"}),
            "rule_id": _nullable({"type": "string"}),
            "disposition_source": {"enum": _sorted(DISPOSITION_SOURCES)},
            "contract_severity": _nullable({"enum": _sorted(SEVERITIES)}),
            "contract_result": _nullable({"enum": _sorted(RULE_RESULTS)}),
            "facts": {"type": "object"},
            "source_pointers": {
                "type": "array",
                "items": {"type": "string", "pattern": "^/"},
                "minItems": 1,
            },
        },
        required=item_fields,
    )
    schema["$defs"] = defs
    schema.update(
        _object(
            {
                "schema_version": {"const": REVIEW_QUEUE_SCHEMA},
                "source_report_id": {"type": "string", "pattern": "^[0-9a-f]{24}$"},
                "source_report_sha256": _ref("sha256"),
                "generated_by": _object(
                    {
                        "name": {"const": "evalcanary"},
                        "assurance_engine_version": {"type": "string"},
                    },
                    required={"name", "assurance_engine_version"},
                ),
                "item_count": {"type": "integer", "minimum": 0},
                "counts_by_review_rank": count_map,
                "counts_by_reason": count_map,
                "counts_by_disposition_source": count_map,
                "invariance_summary": _object(
                    {
                        "baseline": invariance_role_summary,
                        "candidate": invariance_role_summary,
                    },
                    required={"baseline", "candidate"},
                ),
                "workload_summary": workload_summary,
                "items": {"type": "array", "items": item},
            },
            required=queue_fields,
        )
    )
    return schema


def generate_schemas() -> dict[str, dict[str, Any]]:
    """Generate every bundled schema from the shared structural registry."""

    return {
        "input-record": _input_schema(),
        "contract": _contract_schema(),
        "report": _report_schema(),
        "review-queue": _review_queue_schema(),
    }


def canonical_schema_bytes(selector: str) -> bytes:
    """Return canonical checked-in schema bytes for one public selector."""

    schema = generate_schemas().get(selector)
    if schema is None:
        raise InputValidationError(
            "Unknown schema selector; expected input-record, contract, report, or review-queue."
        )
    return canonical_json_bytes(schema) + b"\n"


def schema_directory() -> Path:
    """Return the source-tree schema directory used by the generator."""

    return Path(__file__).resolve().with_name("schemas")


def bundled_schema_bytes(selector: str) -> bytes:
    """Read one packaged schema without network resolution."""

    filename = SCHEMA_FILENAMES.get(selector)
    if filename is None:
        return canonical_schema_bytes(selector)
    return files("evalcanary.assurance").joinpath("schemas", filename).read_bytes()


def verify_checked_in_schemas() -> None:
    """Fail closed when generated bytes drift from checked-in artifacts."""

    for selector, filename in SCHEMA_FILENAMES.items():
        path = schema_directory() / filename
        try:
            actual = path.read_bytes()
        except OSError as exc:
            raise InputValidationError("A checked-in assurance schema is unavailable.") from exc
        if actual != canonical_schema_bytes(selector):
            raise InputValidationError(
                "Generated assurance schema bytes differ from checked-in artifacts."
            )


def write_checked_in_schemas() -> tuple[Path, ...]:
    """Mechanically update checked-in schemas from the registry."""

    target = schema_directory()
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for selector, filename in SCHEMA_FILENAMES.items():
        path = target / filename
        path.write_bytes(canonical_schema_bytes(selector))
        written.append(path)
    return tuple(written)
