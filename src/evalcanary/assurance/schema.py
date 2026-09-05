"""Strict bounded schemas for evaluator-assurance evidence and contracts."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..errors import InputValidationError, PolicyConfigurationError
from .constants import (
    CONTRACT_SCHEMA,
    FIXED_CONTEXT_COMPONENTS,
    FIXED_EVALUATOR_COMPONENTS,
    INPUT_SCHEMA,
    LIMIT_CEILINGS,
    LIMIT_DEFAULTS,
    MANIFEST_ALGORITHM,
    METRICS,
    MOVABLE_COMPONENTS,
    NON_OVERRIDABLE_LIMITS,
    OPERATORS,
    PRESENCES,
    PROVENANCE_FIELDS,
    RECORD_TYPES,
    RELATIONS,
    ROLES,
    SCOPES,
    SEVERITIES,
    STATUSES,
)
from .numeric import (
    canonical_json_bytes,
    canonical_sha256,
    parse_decimal_token,
    reject_constant,
)

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_EXTENSION = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)+\Z")
_ERROR_CLASS = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


@dataclass(frozen=True, slots=True)
class Limits:
    """One immutable effective resource-limit policy."""

    values: dict[str, int] = field(default_factory=lambda: dict(LIMIT_DEFAULTS))
    source_sha256: str | None = None

    def get(self, name: str) -> int:
        return self.values[name]

    def enforce(self, name: str, observed: int, *, field_path: str) -> None:
        allowed = self.get(name)
        if observed > allowed:
            raise InputValidationError(
                f"Limit exceeded at {field_path}: {name} observed={observed} allowed={allowed}."
            )

    @classmethod
    def from_path(cls, path: Path | None) -> Limits:
        if path is None:
            return cls()
        bootstrap = cls()
        data = _bounded_read(
            path,
            bootstrap,
            field_path="$limits",
            description="Limits document",
        )
        source_sha256 = hashlib.sha256(data).hexdigest()
        value = _loads_strict(data, source="limits document")
        _check_shape(value, bootstrap, "$limits")
        _exact_fields(value, {"limits"}, "limits")
        overrides = _object(value["limits"], "limits.limits")
        unknown = sorted(set(overrides) - set(LIMIT_DEFAULTS))
        if unknown:
            raise InputValidationError("Unknown resource limit: " + ", ".join(unknown))
        effective = dict(LIMIT_DEFAULTS)
        for name, raw in overrides.items():
            integer = _integer(raw, f"limits.limits.{name}", minimum=1)
            if integer > LIMIT_CEILINGS[name]:
                raise InputValidationError(
                    f"Resource limit {name} exceeds the absolute v0.2 ceiling."
                )
            if name in NON_OVERRIDABLE_LIMITS and integer > LIMIT_DEFAULTS[name]:
                raise InputValidationError(f"Resource limit {name} cannot be raised.")
            effective[name] = integer
        return cls(values=effective, source_sha256=source_sha256)

    def overrides(self) -> dict[str, int]:
        return {
            name: value
            for name, value in self.values.items()
            if value != LIMIT_DEFAULTS[name]
        }


@dataclass(frozen=True, slots=True)
class AssuranceArtifact:
    path: Path
    source_sha256: str
    input_bytes: int
    record_count: int
    header: dict[str, Any]
    cases: tuple[dict[str, Any], ...]
    trials: tuple[dict[str, Any], ...]
    critical_groups: tuple[dict[str, Any], ...]
    invariance_groups: tuple[dict[str, Any], ...]
    anchor_sets: tuple[dict[str, Any], ...]
    anchors: tuple[dict[str, Any], ...]
    limits: Limits

    @property
    def evaluations_by_role(self) -> dict[str, dict[str, Any]]:
        return {item["role"]: item for item in self.header["evaluations"]}

    @property
    def evaluation_roles(self) -> dict[str, str]:
        return {
            item["evaluation_id"]: item["role"] for item in self.header["evaluations"]
        }


@dataclass(frozen=True, slots=True)
class AssuranceContract:
    path: Path
    source_sha256: str
    document: dict[str, Any]


def _bounded_read(
    path: Path,
    limits: Limits,
    *,
    field_path: str,
    description: str,
) -> bytes:
    try:
        if not path.is_file():
            raise InputValidationError(f"{description} does not exist.")
        limits.enforce("total_input_bytes", path.stat().st_size, field_path=field_path)
        data = path.read_bytes()
    except InputValidationError:
        raise
    except OSError as exc:
        raise InputValidationError(f"{description} could not be read safely.") from exc
    limits.enforce("total_input_bytes", len(data), field_path=field_path)
    return data


def _duplicate_checked(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputValidationError("Duplicate JSON object key is not permitted.")
        result[key] = value
    return result


def _loads_strict(data: bytes, *, source: str) -> Any:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise InputValidationError(f"{source} is not valid UTF-8.") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_duplicate_checked,
            parse_int=parse_decimal_token,
            parse_float=parse_decimal_token,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise InputValidationError(
            f"Invalid JSON in {source} at line {exc.lineno}, column {exc.colno}."
        ) from exc


def _object(value: Any, field_path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputValidationError(f"{field_path} must be an object.")
    return value


def _array(value: Any, field_path: str) -> list[Any]:
    if not isinstance(value, list):
        raise InputValidationError(f"{field_path} must be an array.")
    return value


def _exact_fields(value: Any, fields: set[str], field_path: str) -> dict[str, Any]:
    obj = _object(value, field_path)
    missing = sorted(fields - set(obj))
    unknown = sorted(set(obj) - fields)
    if missing:
        raise InputValidationError(
            f"Missing required field at {field_path}: {missing[0]}"
        )
    if unknown:
        raise InputValidationError(f"Unknown core field at {field_path}: {unknown[0]}")
    return obj


def _fields_with_optional(
    value: Any, required: set[str], optional: set[str], field_path: str
) -> dict[str, Any]:
    obj = _object(value, field_path)
    missing = sorted(required - set(obj))
    unknown = sorted(set(obj) - required - optional)
    if missing:
        raise InputValidationError(
            f"Missing required field at {field_path}: {missing[0]}"
        )
    if unknown:
        raise InputValidationError(f"Unknown core field at {field_path}: {unknown[0]}")
    return obj


def _string(
    value: Any, field_path: str, limits: Limits, *, allow_empty: bool = False
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise InputValidationError(f"{field_path} must be a non-empty string.")
    try:
        encoded_size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise InputValidationError(
            f"{field_path} must contain valid Unicode scalar values."
        ) from exc
    limits.enforce("general_string_scalars", len(value), field_path=field_path)
    limits.enforce("general_string_bytes", encoded_size, field_path=field_path)
    return value


def _fixed_source_text(value: Any, field_path: str, limits: Limits) -> str:
    """Apply the immutable 4,096-scalar and 16-KiB source-text ceiling."""

    text = _string(value, field_path, limits)
    if len(text) > 4_096 or len(text.encode("utf-8")) > 16_384:
        raise InputValidationError(f"{field_path} exceeds the fixed v1 source bound.")
    return text


def _identity_string(value: Any, field_path: str, limits: Limits) -> str:
    text = _string(value, field_path, limits)
    if unicodedata.normalize("NFC", text) != text:
        raise InputValidationError(f"{field_path} must already be NFC-normalized.")
    return text


def _id(value: Any, field_path: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise InputValidationError(
            f"{field_path} is not a valid bounded ASCII identifier."
        )
    return value


def _sha(value: Any, field_path: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise InputValidationError(f"{field_path} must be a lowercase SHA-256 value.")
    return value


def _integer(
    value: Any, field_path: str, *, minimum: int = 0, maximum: int | None = None
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, Decimal)
        or value != value.to_integral_value()
    ):
        raise InputValidationError(f"{field_path} must be an exact integer.")
    integer = int(value)
    if integer < minimum or (maximum is not None and integer > maximum):
        raise InputValidationError(
            f"{field_path} is outside its allowed integer domain."
        )
    return integer


def _enum(value: Any, choices: frozenset[str], field_path: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise InputValidationError(f"{field_path} contains an unknown enum value.")
    return value


def _decimal(value: Any, field_path: str) -> Decimal:
    if (
        isinstance(value, bool)
        or not isinstance(value, Decimal)
        or not value.is_finite()
    ):
        raise InputValidationError(f"{field_path} must be an exact finite JSON number.")
    return value


def _label(value: Any, field_path: str) -> str:
    if not isinstance(value, str) or not value:
        raise InputValidationError(f"{field_path} must be a non-empty label.")
    if len(value) > 64 or len(value.encode("utf-8")) > 256:
        raise InputValidationError(f"{field_path} exceeds the label bound.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise InputValidationError(f"{field_path} contains a control character.")
    if unicodedata.normalize("NFC", value) != value:
        raise InputValidationError(f"{field_path} must already be NFC-normalized.")
    return value


def _extensions(value: Any, field_path: str, limits: Limits) -> dict[str, Any]:
    obj = _object(value, field_path)
    for key in obj:
        if _EXTENSION.fullmatch(key) is None:
            raise InputValidationError(
                f"Invalid namespaced extension key at {field_path}."
            )
    limits.enforce(
        "extension_bytes", len(canonical_json_bytes(obj)), field_path=field_path
    )
    return obj


def _component_value(value: Any, field_path: str, limits: Limits) -> dict[str, Any]:
    obj = _exact_fields(value, {"presence", "identity", "sha256"}, field_path)
    presence = _enum(obj["presence"], PRESENCES, f"{field_path}.presence")
    identity = obj["identity"]
    if identity is not None:
        _identity_string(identity, f"{field_path}.identity", limits)
    _sha(obj["sha256"], f"{field_path}.sha256", nullable=True)
    if presence == "present":
        if identity is None and obj["sha256"] is None:
            raise InputValidationError(
                f"{field_path} present value requires identity or sha256."
            )
    elif identity is not None or obj["sha256"] is not None:
        raise InputValidationError(
            f"{field_path} non-present value cannot carry identity or sha256."
        )
    return obj


def _provenance(value: Any, field_path: str, limits: Limits) -> dict[str, Any]:
    obj = _object(value, field_path)
    unknown = sorted(set(obj) - PROVENANCE_FIELDS)
    if unknown:
        raise InputValidationError(
            f"Unknown provenance field at {field_path}: {unknown[0]}"
        )
    for name, item in obj.items():
        _component_value(item, f"{field_path}.{name}", limits)
    return obj


def _check_shape(
    value: Any, limits: Limits, field_path: str = "$", depth: int = 1
) -> None:
    limits.enforce("nesting_depth", depth, field_path=field_path)
    if isinstance(value, dict):
        limits.enforce("map_keys", len(value), field_path=field_path)
        for key, item in value.items():
            _string(key, f"{field_path}.<key>", limits)
            _check_shape(item, limits, f"{field_path}.{key}", depth + 1)
    elif isinstance(value, list):
        limits.enforce("array_items", len(value), field_path=field_path)
        for index, item in enumerate(value):
            _check_shape(item, limits, f"{field_path}[{index}]", depth + 1)
    elif isinstance(value, str):
        _string(value, field_path, limits, allow_empty=True)
    elif value is not None and not isinstance(value, (bool, Decimal)):
        raise InputValidationError(f"Unsupported JSON scalar at {field_path}.")


def _read_jsonl(
    path: Path, limits: Limits
) -> tuple[list[dict[str, Any]], str, int]:
    try:
        if not path.is_file():
            raise InputValidationError("Assurance input file does not exist.")
        size = path.stat().st_size
    except InputValidationError:
        raise
    except OSError as exc:
        raise InputValidationError("Assurance input could not be read safely.") from exc
    limits.enforce("total_input_bytes", size, field_path="$input")
    if size == 0:
        raise InputValidationError("Assurance input is empty.")
    records: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    total_bytes = 0
    try:
        with path.open("rb") as handle:
            line_number = 0
            while raw_line := handle.readline(limits.get("line_bytes") + 1):
                line_number += 1
                total_bytes += len(raw_line)
                limits.enforce(
                    "total_input_bytes", total_bytes, field_path="$input"
                )
                digest.update(raw_line)
                limits.enforce(
                    "line_bytes", len(raw_line), field_path=f"record[{line_number}]"
                )
                if b"\xef\xbb\xbf" in raw_line:
                    raise InputValidationError(
                        f"BOM is not permitted at record {line_number}."
                    )
                content = raw_line[:-1] if raw_line.endswith(b"\n") else raw_line
                if content.endswith(b"\r"):
                    content = content[:-1]
                if not content:
                    raise InputValidationError(
                        f"Blank lines are not permitted at record {line_number}."
                    )
                value = _loads_strict(content, source=f"record {line_number}")
                obj = _object(value, f"record[{line_number}]")
                _check_shape(obj, limits, f"record[{line_number}]")
                records.append(obj)
                limits.enforce("total_records", len(records), field_path="$input")
    except InputValidationError:
        raise
    except OSError as exc:
        raise InputValidationError("Assurance input could not be read safely.") from exc
    return records, digest.hexdigest(), total_bytes


def _validate_component_inventory(header: dict[str, Any], limits: Limits) -> None:
    ownership = _exact_fields(
        header["component_ownership"],
        set(MOVABLE_COMPONENTS),
        "header.component_ownership",
    )
    for name in MOVABLE_COMPONENTS:
        _enum(
            ownership[name],
            frozenset({"evaluator", "context"}),
            f"component_ownership.{name}",
        )
    expected_evaluator = set(FIXED_EVALUATOR_COMPONENTS)
    expected_context = set(FIXED_CONTEXT_COMPONENTS)
    for name, owner in ownership.items():
        (expected_evaluator if owner == "evaluator" else expected_context).add(name)
    for index, evaluation in enumerate(header["evaluations"]):
        evaluator_components = _object(
            evaluation["evaluator_components"],
            f"header.evaluations[{index}].evaluator_components",
        )
        context_components = _object(
            evaluation["context_components"],
            f"header.evaluations[{index}].context_components",
        )
        if set(evaluator_components) != expected_evaluator:
            raise InputValidationError(
                "Evaluator component inventory does not match declared ownership."
            )
        if set(context_components) != expected_context:
            raise InputValidationError(
                "Context component inventory does not match declared ownership."
            )
        for name, item in evaluator_components.items():
            _component_value(
                item, f"evaluation[{index}].evaluator_components.{name}", limits
            )
        for name, item in context_components.items():
            _component_value(
                item, f"evaluation[{index}].context_components.{name}", limits
            )


def _validate_judgment_spec(value: Any, limits: Limits) -> dict[str, Any]:
    obj = _exact_fields(
        value,
        {
            "judgment_spec_id",
            "kind",
            "label_space",
            "score_spec",
            "repeat_score_tolerance",
        },
        "header.judgment_spec",
    )
    _id(obj["judgment_spec_id"], "judgment_spec.judgment_spec_id")
    kind = _enum(
        obj["kind"],
        frozenset({"categorical", "numeric", "categorical_and_numeric"}),
        "judgment_spec.kind",
    )
    label_space = obj["label_space"]
    if kind in {"categorical", "categorical_and_numeric"}:
        labels = _array(label_space, "judgment_spec.label_space")
        if not 2 <= len(labels) <= 64:
            raise InputValidationError(
                "Categorical label_space requires 2 through 64 labels."
            )
        checked = [_label(item, "judgment_spec.label_space[]") for item in labels]
        if len(set(checked)) != len(checked):
            raise InputValidationError("label_space values must be unique.")
    elif label_space is not None:
        raise InputValidationError("Numeric judgment label_space must be null.")

    score_spec = obj["score_spec"]
    if kind in {"numeric", "categorical_and_numeric"}:
        score = _exact_fields(
            score_spec,
            {
                "scale_id",
                "domain_min",
                "domain_max",
                "direction",
                "comparison",
                "valid_statuses",
                "threshold_relationship",
            },
            "judgment_spec.score_spec",
        )
        _id(score["scale_id"], "score_spec.scale_id")
        domain_min = _decimal(score["domain_min"], "score_spec.domain_min")
        domain_max = _decimal(score["domain_max"], "score_spec.domain_max")
        if domain_min >= domain_max:
            raise InputValidationError(
                "score_spec domain_min must be below domain_max."
            )
        _enum(
            score["direction"],
            frozenset({"higher_is_better", "lower_is_better", "none"}),
            "score_spec.direction",
        )
        _enum(
            score["comparison"], frozenset({"delta", "none"}), "score_spec.comparison"
        )
        statuses = _array(score["valid_statuses"], "score_spec.valid_statuses")
        allowed_score_statuses = frozenset({"determinate", "abstain", "indeterminate"})
        if not statuses or any(item not in allowed_score_statuses for item in statuses):
            raise InputValidationError("score_spec.valid_statuses is invalid.")
        if len(set(statuses)) != len(statuses):
            raise InputValidationError("score_spec.valid_statuses must be unique.")
        relationship = score["threshold_relationship"]
        if relationship is not None:
            relation = _exact_fields(
                relationship,
                {"operator", "threshold", "below_label", "above_label"},
                "score_spec.threshold_relationship",
            )
            _enum(
                relation["operator"],
                frozenset({"lt", "lte", "gt", "gte"}),
                "threshold_relationship.operator",
            )
            threshold = _decimal(
                relation["threshold"], "threshold_relationship.threshold"
            )
            if not domain_min <= threshold <= domain_max:
                raise InputValidationError(
                    "threshold_relationship threshold is outside the score domain."
                )
            if kind != "categorical_and_numeric":
                raise InputValidationError(
                    "threshold_relationship requires categorical_and_numeric kind."
                )
            for name in ("below_label", "above_label"):
                if relation[name] not in label_space:
                    raise InputValidationError(
                        "threshold_relationship label is outside label_space."
                    )
            if relation["below_label"] == relation["above_label"]:
                raise InputValidationError("threshold_relationship labels must differ.")
    elif score_spec is not None:
        raise InputValidationError("Categorical judgment score_spec must be null.")
    tolerance = obj["repeat_score_tolerance"]
    if (
        tolerance is not None
        and _decimal(tolerance, "judgment_spec.repeat_score_tolerance") < 0
    ):
        raise InputValidationError("repeat_score_tolerance must be non-negative.")
    return obj


def _validate_header(value: Any, limits: Limits) -> dict[str, Any]:
    fields = {
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
    header = _exact_fields(value, fields, "header")
    if header["record_type"] != "header" or header["schema_version"] != INPUT_SCHEMA:
        raise InputValidationError(
            "The first record must be the exact assurance v1 header."
        )
    _id(header["artifact_id"], "header.artifact_id")
    corpus = _exact_fields(
        header["corpus"],
        {
            "corpus_id",
            "manifest_sha256",
            "case_count",
            "identity_level",
            "manifest_algorithm",
        },
        "header.corpus",
    )
    _id(corpus["corpus_id"], "corpus.corpus_id")
    _sha(corpus["manifest_sha256"], "corpus.manifest_sha256")
    corpus["case_count"] = _integer(
        corpus["case_count"], "corpus.case_count", minimum=1
    )
    _enum(
        corpus["identity_level"],
        frozenset({"case_ids", "content_hashes", "full_artifact"}),
        "corpus.identity_level",
    )
    if corpus["manifest_algorithm"] != MANIFEST_ALGORITHM:
        raise InputValidationError("Unknown corpus manifest algorithm.")
    _validate_judgment_spec(header["judgment_spec"], limits)
    evaluations = _array(header["evaluations"], "header.evaluations")
    if len(evaluations) != 2:
        raise InputValidationError("Exactly two evaluations are required.")
    evaluation_fields = {
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
    roles: list[str] = []
    evaluation_ids: list[str] = []
    for index, raw in enumerate(evaluations):
        evaluation = _exact_fields(
            raw, evaluation_fields, f"header.evaluations[{index}]"
        )
        for name in ("evaluation_id", "evaluator_id", "context_id"):
            _id(evaluation[name], f"evaluations[{index}].{name}")
        _identity_string(
            evaluation["evaluator_version"],
            f"evaluations[{index}].evaluator_version",
            limits,
        )
        _sha(
            evaluation["evaluator_fingerprint_sha256"],
            f"evaluations[{index}].evaluator_fingerprint_sha256",
        )
        _sha(
            evaluation["context_fingerprint_sha256"],
            f"evaluations[{index}].context_fingerprint_sha256",
        )
        roles.append(_enum(evaluation["role"], ROLES, f"evaluations[{index}].role"))
        evaluation_ids.append(evaluation["evaluation_id"])
        _provenance(
            evaluation["provenance"], f"evaluations[{index}].provenance", limits
        )
    if set(roles) != ROLES or len(set(evaluation_ids)) != 2:
        raise InputValidationError(
            "Evaluations require distinct IDs and one baseline/candidate role each."
        )
    _validate_component_inventory(header, limits)
    exceptions = _array(
        header["allowed_context_differences"], "header.allowed_context_differences"
    )
    seen_components: set[str] = set()
    ownership = header["component_ownership"]
    context_inventory = set(FIXED_CONTEXT_COMPONENTS) | {
        name for name, owner in ownership.items() if owner == "context"
    }
    exception_fields = {
        "component",
        "expected_baseline_component_value",
        "expected_candidate_component_value",
        "rationale",
        "reviewer_id",
        "disposition",
    }
    for index, raw in enumerate(exceptions):
        item = _exact_fields(
            raw, exception_fields, f"allowed_context_differences[{index}]"
        )
        component = item["component"]
        if component not in context_inventory or component in seen_components:
            raise InputValidationError(
                "Allowed context difference has invalid or duplicate component."
            )
        seen_components.add(component)
        before = _component_value(
            item["expected_baseline_component_value"],
            f"context_exception[{index}].baseline",
            limits,
        )
        after = _component_value(
            item["expected_candidate_component_value"],
            f"context_exception[{index}].candidate",
            limits,
        )
        if before == after:
            raise InputValidationError(
                "Allowed context difference expected values must differ."
            )
        _string(item["rationale"], f"context_exception[{index}].rationale", limits)
        _id(item["reviewer_id"], f"context_exception[{index}].reviewer_id")
        if item["disposition"] != "not_isolated_review_required":
            raise InputValidationError(
                "Unknown allowed-context-difference disposition."
            )
    _provenance(header["provenance"], "header.provenance", limits)
    _extensions(header["extensions"], "header.extensions", limits)
    if corpus["identity_level"] == "full_artifact":
        item = header["provenance"].get("original_artifact_hash")
        if (
            not isinstance(item, dict)
            or item.get("presence") != "present"
            or item.get("sha256") is None
        ):
            raise InputValidationError(
                "full_artifact identity requires present original_artifact_hash provenance."
            )
    return header


def _validate_case(
    value: Any, header: dict[str, Any], limits: Limits, index: int
) -> dict[str, Any]:
    obj = _exact_fields(
        value,
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
        },
        f"case[{index}]",
    )
    _id(obj["case_id"], f"case[{index}].case_id")
    obj["manifest_position"] = _integer(
        obj["manifest_position"], f"case[{index}].manifest_position"
    )
    identity_level = header["corpus"]["identity_level"]
    _sha(
        obj["content_sha256"],
        f"case[{index}].content_sha256",
        nullable=identity_level == "case_ids",
    )
    if identity_level != "case_ids" and obj["content_sha256"] is None:
        raise InputValidationError(
            "content_sha256 is required for the declared corpus identity level."
        )
    for field_name, limit_name in (
        ("critical_group_ids", "critical_memberships_per_case"),
        ("invariance_group_ids", "invariance_memberships_per_case"),
    ):
        values = _array(obj[field_name], f"case[{index}].{field_name}")
        limits.enforce(
            limit_name, len(values), field_path=f"case[{index}].{field_name}"
        )
        checked = [_id(item, f"case[{index}].{field_name}[]") for item in values]
        if checked != sorted(set(checked)):
            raise InputValidationError(f"{field_name} must be sorted and unique.")
    tags = _array(obj["tags"], f"case[{index}].tags")
    checked_tags = [
        _identity_string(item, f"case[{index}].tags[]", limits) for item in tags
    ]
    if checked_tags != sorted(set(checked_tags)):
        raise InputValidationError("Case tags must be sorted and unique.")
    if obj["display_label"] is not None:
        _string(obj["display_label"], f"case[{index}].display_label", limits)
    _extensions(obj["extensions"], f"case[{index}].extensions", limits)
    return obj


def _validate_trial(
    value: Any, header: dict[str, Any], limits: Limits, index: int
) -> dict[str, Any]:
    obj = _exact_fields(
        value,
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
        },
        f"trial[{index}]",
    )
    for name in ("case_id", "evaluation_id", "trial_id"):
        _id(obj[name], f"trial[{index}].{name}")
    obj["source_order"] = _integer(obj["source_order"], f"trial[{index}].source_order")
    if obj["pairing_key"] is not None:
        _id(obj["pairing_key"], f"trial[{index}].pairing_key")
    status = _enum(obj["status"], STATUSES, f"trial[{index}].status")
    judgment = header["judgment_spec"]
    kind = judgment["kind"]
    if obj["label"] is not None:
        _label(obj["label"], f"trial[{index}].label")
    if status == "determinate" and kind in {"categorical", "categorical_and_numeric"}:
        if obj["label"] not in judgment["label_space"]:
            raise InputValidationError(
                "Determinate categorical trial requires a declared label."
            )
    elif obj["label"] is not None:
        raise InputValidationError(
            "Non-determinate or numeric-only trial label must be null."
        )
    score = obj["score"]
    score_spec = judgment["score_spec"]
    if score is not None:
        numeric = _decimal(score, f"trial[{index}].score")
        if score_spec is None:
            raise InputValidationError("Categorical trial cannot carry a score.")
        if status == "error" or status not in score_spec["valid_statuses"]:
            raise InputValidationError("Trial score is not valid for its status.")
        if not score_spec["domain_min"] <= numeric <= score_spec["domain_max"]:
            raise InputValidationError("Trial score is outside the declared domain.")
    if obj["reason"] is not None:
        _fixed_source_text(obj["reason"], f"trial[{index}].reason", limits)
    if obj["details"] is not None:
        limits.enforce(
            "details_bytes",
            len(canonical_json_bytes(obj["details"])),
            field_path=f"trial[{index}].details",
        )
    error = obj["error"]
    if status == "error":
        error_obj = _fields_with_optional(
            error, {"error_class"}, {"message"}, f"trial[{index}].error"
        )
        if (
            not isinstance(error_obj["error_class"], str)
            or _ERROR_CLASS.fullmatch(error_obj["error_class"]) is None
        ):
            raise InputValidationError(
                "error_class must be bounded enum-like ASCII text."
            )
        message = error_obj.get("message")
        if message is not None:
            _fixed_source_text(
                message, f"trial[{index}].error.message", limits
            )
    elif error is not None:
        raise InputValidationError("Non-error trial must have error=null.")
    _provenance(obj["provenance"], f"trial[{index}].provenance", limits)
    _extensions(obj["extensions"], f"trial[{index}].extensions", limits)
    return obj


def _validate_critical(value: Any, limits: Limits, index: int) -> dict[str, Any]:
    obj = _exact_fields(
        value,
        {
            "record_type",
            "group_id",
            "title",
            "declaration_source",
            "rationale",
            "extensions",
        },
        f"critical_group[{index}]",
    )
    _id(obj["group_id"], f"critical_group[{index}].group_id")
    for name in ("title", "declaration_source"):
        _identity_string(obj[name], f"critical_group[{index}].{name}", limits)
    _string(obj["rationale"], f"critical_group[{index}].rationale", limits)
    _extensions(obj["extensions"], f"critical_group[{index}].extensions", limits)
    return obj


def _validate_invariance(
    value: Any, header: dict[str, Any], limits: Limits, index: int
) -> dict[str, Any]:
    obj = _exact_fields(
        value,
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
        },
        f"invariance_group[{index}]",
    )
    for name in ("group_id", "transformation_id", "transformation_version"):
        _id(obj[name], f"invariance_group[{index}].{name}")
    members = _array(
        obj["member_case_ids"], f"invariance_group[{index}].member_case_ids"
    )
    limits.enforce(
        "invariance_members",
        len(members),
        field_path=f"invariance_group[{index}].member_case_ids",
    )
    if len(members) < 2 or len(set(members)) != len(members):
        raise InputValidationError(
            "Invariance group requires at least two unique ordered members."
        )
    for member in members:
        _id(member, f"invariance_group[{index}].member_case_ids[]")
    relation = _enum(
        obj["expected_relation"],
        RELATIONS,
        f"invariance_group[{index}].expected_relation",
    )
    parameters = _object(
        obj["relation_parameters"], f"invariance_group[{index}].relation_parameters"
    )
    labels = header["judgment_spec"]["label_space"]
    if relation == "same_label":
        _exact_fields(
            parameters, set(), f"invariance_group[{index}].relation_parameters"
        )
    elif relation == "swapped_preference":
        if len(members) != 2 or labels is None:
            raise InputValidationError(
                "swapped_preference requires two members and categorical labels."
            )
        relation_obj = _fields_with_optional(
            parameters,
            {"first_label", "second_label"},
            {"tie_label"},
            f"invariance_group[{index}].relation_parameters",
        )
        declared = [relation_obj["first_label"], relation_obj["second_label"]]
        if "tie_label" in relation_obj:
            declared.append(relation_obj["tie_label"])
        if len(set(declared)) != len(declared) or any(
            item not in labels for item in declared
        ):
            raise InputValidationError(
                "swapped_preference labels must be distinct declared labels."
            )
    else:
        relation_obj = _exact_fields(
            parameters,
            {"absolute_tolerance"},
            f"invariance_group[{index}].relation_parameters",
        )
        tolerance = _decimal(
            relation_obj["absolute_tolerance"], "relation_parameters.absolute_tolerance"
        )
        if tolerance < 0 or header["judgment_spec"]["score_spec"] is None:
            raise InputValidationError(
                "same_score_within_tolerance requires a non-negative tolerance and score spec."
            )
    _enum(obj["severity"], SEVERITIES, f"invariance_group[{index}].severity")
    _identity_string(
        obj["declaration_source"],
        f"invariance_group[{index}].declaration_source",
        limits,
    )
    _string(obj["rationale"], f"invariance_group[{index}].rationale", limits)
    _extensions(obj["extensions"], f"invariance_group[{index}].extensions", limits)
    return obj


def _validate_anchor_set(value: Any, limits: Limits, index: int) -> dict[str, Any]:
    obj = _exact_fields(
        value,
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
        },
        f"anchor_set[{index}]",
    )
    for name in ("anchor_set_id", "protocol_id", "protocol_version"):
        _id(obj[name], f"anchor_set[{index}].{name}")
    labels = _array(obj["label_space"], f"anchor_set[{index}].label_space")
    if not 2 <= len(labels) <= 64:
        raise InputValidationError("Anchor label_space requires 2 through 64 labels.")
    checked = [_label(item, f"anchor_set[{index}].label_space[]") for item in labels]
    if len(set(checked)) != len(checked):
        raise InputValidationError("Anchor label_space must be unique.")
    _enum(
        obj["aggregation_method"],
        frozenset({"none", "majority", "adjudicated", "caller_supplied"}),
        f"anchor_set[{index}].aggregation_method",
    )
    for name in ("clustering_unit", "source_revision", "license"):
        _identity_string(obj[name], f"anchor_set[{index}].{name}", limits)
    _sha(obj["source_sha256"], f"anchor_set[{index}].source_sha256")
    _provenance(obj["provenance"], f"anchor_set[{index}].provenance", limits)
    _extensions(obj["extensions"], f"anchor_set[{index}].extensions", limits)
    return obj


def _validate_anchor(value: Any, limits: Limits, index: int) -> dict[str, Any]:
    obj = _exact_fields(
        value,
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
        },
        f"anchor[{index}]",
    )
    for name in (
        "anchor_id",
        "anchor_set_id",
        "case_id",
        "cluster_id",
        "annotation_id",
    ):
        _id(obj[name], f"anchor[{index}].{name}")
    if obj["annotator_id"] is not None:
        _id(obj["annotator_id"], f"anchor[{index}].annotator_id")
    kind = _enum(
        obj["kind"], frozenset({"raw_annotation", "aggregate"}), f"anchor[{index}].kind"
    )
    status = _enum(obj["status"], STATUSES, f"anchor[{index}].status")
    if status == "error":
        raise InputValidationError(
            "Anchor error status cannot be represented without the locked error object; fail closed."
        )
    if status == "determinate":
        _label(obj["label"], f"anchor[{index}].label")
    elif obj["label"] is not None:
        raise InputValidationError("Non-determinate anchor label must be null.")
    if obj["reason"] is not None:
        _string(obj["reason"], f"anchor[{index}].reason", limits)
    inputs = _array(obj["aggregation_inputs"], f"anchor[{index}].aggregation_inputs")
    limits.enforce(
        "aggregation_inputs",
        len(inputs),
        field_path=f"anchor[{index}].aggregation_inputs",
    )
    for item in inputs:
        _id(item, f"anchor[{index}].aggregation_inputs[]")
    if len(inputs) != len(set(inputs)):
        raise InputValidationError("Anchor aggregation_inputs must be unique.")
    if kind == "raw_annotation" and inputs:
        raise InputValidationError("Raw anchor aggregation_inputs must be empty.")
    if obj["adjudication_rationale"] is not None:
        _string(
            obj["adjudication_rationale"],
            f"anchor[{index}].adjudication_rationale",
            limits,
        )
    _provenance(obj["provenance"], f"anchor[{index}].provenance", limits)
    _extensions(obj["extensions"], f"anchor[{index}].extensions", limits)
    return obj


def _manifest_document(
    header: dict[str, Any],
    cases: list[dict[str, Any]],
    critical_groups: list[dict[str, Any]],
    invariance_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "manifest_algorithm": MANIFEST_ALGORITHM,
        "corpus_id": header["corpus"]["corpus_id"],
        "cases": [
            {
                "case_id": item["case_id"],
                "manifest_position": item["manifest_position"],
                "content_sha256": item["content_sha256"],
                "critical_group_ids": item["critical_group_ids"],
                "invariance_group_ids": item["invariance_group_ids"],
            }
            for item in sorted(cases, key=lambda case: case["manifest_position"])
        ],
        "critical_groups": [
            {
                "group_id": item["group_id"],
                "title": item["title"],
                "declaration_source": item["declaration_source"],
            }
            for item in sorted(critical_groups, key=lambda group: group["group_id"])
        ],
        "invariance_groups": [
            {
                "group_id": item["group_id"],
                "member_case_ids": item["member_case_ids"],
                "transformation_id": item["transformation_id"],
                "transformation_version": item["transformation_version"],
                "expected_relation": item["expected_relation"],
                "relation_parameters": item["relation_parameters"],
                "severity": item["severity"],
                "declaration_source": item["declaration_source"],
            }
            for item in sorted(invariance_groups, key=lambda group: group["group_id"])
        ],
    }


def compute_manifest_sha256(
    header: dict[str, Any],
    cases: list[dict[str, Any]],
    critical_groups: list[dict[str, Any]],
    invariance_groups: list[dict[str, Any]],
) -> str:
    return canonical_sha256(
        _manifest_document(header, cases, critical_groups, invariance_groups)
    )


def load_artifact(path: Path, *, limits: Limits | None = None) -> AssuranceArtifact:
    """Parse and validate one normative UTF-8 JSONL assurance artifact."""

    effective_limits = limits or Limits()
    records, source_sha256, input_bytes = _read_jsonl(path, effective_limits)
    if not records or records[0].get("record_type") != "header":
        raise InputValidationError("The first record must be the sole header.")
    header = _validate_header(records[0], effective_limits)
    typed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record_number, record in enumerate(records[1:], start=2):
        record_type = record.get("record_type")
        if record_type not in RECORD_TYPES or record_type == "header":
            raise InputValidationError(
                f"Unknown or duplicate record type at record {record_number}."
            )
        typed[record_type].append(record)
    cases = [
        _validate_case(item, header, effective_limits, index)
        for index, item in enumerate(typed["case"])
    ]
    trials = [
        _validate_trial(item, header, effective_limits, index)
        for index, item in enumerate(typed["trial"])
    ]
    critical = [
        _validate_critical(item, effective_limits, index)
        for index, item in enumerate(typed["critical_group"])
    ]
    invariance = [
        _validate_invariance(item, header, effective_limits, index)
        for index, item in enumerate(typed["invariance_group"])
    ]
    anchor_sets = [
        _validate_anchor_set(item, effective_limits, index)
        for index, item in enumerate(typed["anchor_set"])
    ]
    anchors = [
        _validate_anchor(item, effective_limits, index)
        for index, item in enumerate(typed["anchor"])
    ]
    for name, collection, limit_name in (
        ("cases", cases, "cases"),
        ("critical groups", critical, "critical_groups"),
        ("invariance groups", invariance, "invariance_groups"),
        ("anchor sets", anchor_sets, "anchor_sets"),
    ):
        effective_limits.enforce(limit_name, len(collection), field_path=name)
    if len(cases) != header["corpus"]["case_count"]:
        raise InputValidationError("Corpus case_count does not match case records.")
    identities: tuple[tuple[str, list[dict[str, Any]], str], ...] = (
        ("case", cases, "case_id"),
        ("trial", trials, "trial_id"),
        ("critical group", critical, "group_id"),
        ("invariance group", invariance, "group_id"),
        ("anchor set", anchor_sets, "anchor_set_id"),
        ("anchor", anchors, "anchor_id"),
    )
    for kind, collection, key in identities:
        values = [item[key] for item in collection]
        if len(values) != len(set(values)):
            raise InputValidationError(f"Duplicate {kind} identity is not permitted.")
    positions = sorted(item["manifest_position"] for item in cases)
    if positions != list(range(len(cases))):
        raise InputValidationError(
            "Case manifest positions must be unique and gap-free."
        )
    case_ids = {item["case_id"] for item in cases}
    critical_ids = {item["group_id"] for item in critical}
    invariance_ids = {item["group_id"] for item in invariance}
    anchor_set_ids = {item["anchor_set_id"] for item in anchor_sets}
    evaluation_ids = {item["evaluation_id"] for item in header["evaluations"]}
    for case in cases:
        if (
            not set(case["critical_group_ids"]) <= critical_ids
            or not set(case["invariance_group_ids"]) <= invariance_ids
        ):
            raise InputValidationError("Case references an undeclared group.")
    for group in critical:
        if not any(group["group_id"] in case["critical_group_ids"] for case in cases):
            raise InputValidationError("Declared critical group must not be empty.")
    for group in invariance:
        if not set(group["member_case_ids"]) <= case_ids:
            raise InputValidationError("Invariance group references an unknown case.")
        declared = {
            case["case_id"]
            for case in cases
            if group["group_id"] in case["invariance_group_ids"]
        }
        if declared != set(group["member_case_ids"]):
            raise InputValidationError(
                "Invariance declaration and case memberships disagree."
            )
    trial_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trial in trials:
        if (
            trial["case_id"] not in case_ids
            or trial["evaluation_id"] not in evaluation_ids
        ):
            raise InputValidationError(
                "Trial references an unknown case or evaluation."
            )
        trial_groups[(trial["case_id"], trial["evaluation_id"])].append(trial)
    for group_key, items in trial_groups.items():
        effective_limits.enforce(
            "trials_per_case_evaluation",
            len(items),
            field_path=f"trials[{group_key[0]}]",
        )
        orders = sorted(item["source_order"] for item in items)
        if orders != list(range(len(items))):
            raise InputValidationError(
                "Trial source_order must be unique and gap-free per case/evaluation."
            )
        pairing = [
            item["pairing_key"] for item in items if item["pairing_key"] is not None
        ]
        effective_limits.enforce(
            "pairing_keys_per_case",
            len(pairing),
            field_path=f"pairing_keys[{group_key[0]}]",
        )
        if len(pairing) != len(set(pairing)):
            raise InputValidationError(
                "Trial pairing_key must be unique per case/evaluation."
            )
    anchor_sets_by_id = {item["anchor_set_id"]: item for item in anchor_sets}
    anchor_by_id = {item["anchor_id"]: item for item in anchors}
    anchor_counts: Counter[tuple[str, str]] = Counter()
    for anchor in anchors:
        if (
            anchor["case_id"] not in case_ids
            or anchor["anchor_set_id"] not in anchor_set_ids
        ):
            raise InputValidationError(
                "Anchor references an unknown case or anchor set."
            )
        if (
            anchor["status"] == "determinate"
            and anchor["label"]
            not in anchor_sets_by_id[anchor["anchor_set_id"]]["label_space"]
        ):
            raise InputValidationError(
                "Anchor label is outside its anchor-set label space."
            )
        anchor_counts[(anchor["case_id"], anchor["anchor_set_id"])] += 1
        if anchor["kind"] == "aggregate":
            owner = anchor_sets_by_id[anchor["anchor_set_id"]]
            if (
                owner["aggregation_method"] == "none"
                or not anchor["aggregation_inputs"]
            ):
                raise InputValidationError(
                    "Aggregate anchor requires a declared aggregation method and inputs."
                )
            for input_id in anchor["aggregation_inputs"]:
                source = anchor_by_id.get(input_id)
                if (
                    source is None
                    or source["kind"] != "raw_annotation"
                    or source["case_id"] != anchor["case_id"]
                    or source["anchor_set_id"] != anchor["anchor_set_id"]
                ):
                    raise InputValidationError(
                        "Aggregate anchor input must reference a retained raw anchor in the same case/set."
                    )
    for anchor_key, count in anchor_counts.items():
        effective_limits.enforce(
            "anchors_per_case_set", count, field_path=f"anchors[{anchor_key[0]}]"
        )
    computed_manifest = compute_manifest_sha256(header, cases, critical, invariance)
    if computed_manifest != header["corpus"]["manifest_sha256"]:
        raise InputValidationError("Corpus manifest SHA-256 mismatch.")
    return AssuranceArtifact(
        path=path.resolve(),
        source_sha256=source_sha256,
        input_bytes=input_bytes,
        record_count=len(records),
        header=header,
        cases=tuple(sorted(cases, key=lambda item: item["manifest_position"])),
        trials=tuple(
            sorted(
                trials,
                key=lambda item: (
                    item["case_id"],
                    item["evaluation_id"],
                    item["source_order"],
                ),
            )
        ),
        critical_groups=tuple(sorted(critical, key=lambda item: item["group_id"])),
        invariance_groups=tuple(sorted(invariance, key=lambda item: item["group_id"])),
        anchor_sets=tuple(sorted(anchor_sets, key=lambda item: item["anchor_set_id"])),
        anchors=tuple(sorted(anchors, key=lambda item: item["anchor_id"])),
        limits=effective_limits,
    )


_METRIC_SIGNATURES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
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


def load_contract(
    path: Path | None, artifact: AssuranceArtifact
) -> AssuranceContract | None:
    if path is None:
        return None
    data = _bounded_read(
        path,
        artifact.limits,
        field_path="$contract",
        description="Contract document",
    )
    document = _loads_strict(data, source="contract")
    _check_shape(document, artifact.limits, "$contract")
    obj = _exact_fields(
        document,
        {
            "schema_version",
            "contract_id",
            "contract_version",
            "applies_to_input_schema",
            "rules",
            "extensions",
        },
        "contract",
    )
    if (
        obj["schema_version"] != CONTRACT_SCHEMA
        or obj["applies_to_input_schema"] != INPUT_SCHEMA
    ):
        raise PolicyConfigurationError(
            "Contract schema identifier or input binding is invalid."
        )
    _id(obj["contract_id"], "contract.contract_id")
    _id(obj["contract_version"], "contract.contract_version")
    rules = _array(obj["rules"], "contract.rules")
    if not rules:
        raise PolicyConfigurationError("Contract rules must be non-empty.")
    rule_ids: set[str] = set()
    labels = artifact.header["judgment_spec"]["label_space"]
    critical_ids = {item["group_id"] for item in artifact.critical_groups}
    invariance_ids = {item["group_id"] for item in artifact.invariance_groups}
    anchor_set_ids = {item["anchor_set_id"] for item in artifact.anchor_sets}
    owner_ids = {
        "artifact": {artifact.header["artifact_id"]},
        "evaluation": {
            item["evaluation_id"] for item in artifact.header["evaluations"]
        },
        "trial": {item["trial_id"] for item in artifact.trials},
        "anchor_set": anchor_set_ids,
        "anchor": {item["anchor_id"] for item in artifact.anchors},
    }
    rule_fields = {
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
    for index, raw in enumerate(rules):
        rule = _exact_fields(raw, rule_fields, f"contract.rules[{index}]")
        rule_id = _id(rule["rule_id"], f"contract.rules[{index}].rule_id")
        if rule_id in rule_ids:
            raise PolicyConfigurationError("Contract rule IDs must be unique.")
        rule_ids.add(rule_id)
        severity = _enum(
            rule["severity"], SEVERITIES, f"contract.rules[{index}].severity"
        )
        scope = _enum(rule["scope"], SCOPES, f"contract.rules[{index}].scope")
        metric = _enum(rule["metric"], METRICS, f"contract.rules[{index}].metric")
        operator = _enum(
            rule["operator"], OPERATORS, f"contract.rules[{index}].operator"
        )
        allowed_scopes, parameters = _METRIC_SIGNATURES[metric]
        if scope not in allowed_scopes:
            raise PolicyConfigurationError("Contract metric uses an unsupported scope.")
        scope_id = rule["scope_id"]
        if scope == "all_cases":
            if scope_id is not None:
                raise PolicyConfigurationError("all_cases scope_id must be null.")
        else:
            _id(scope_id, f"contract.rules[{index}].scope_id")
            valid_scope_ids = {
                "critical_group": critical_ids,
                "invariance_group": invariance_ids,
                "anchor_set": anchor_set_ids,
            }
            if scope in valid_scope_ids and scope_id not in valid_scope_ids[scope]:
                raise PolicyConfigurationError(
                    "Contract rule scope_id is not declared."
                )
        params = _exact_fields(
            rule["parameters"], set(parameters), f"contract.rules[{index}].parameters"
        )
        for name in ("role",):
            if name in params:
                _enum(params[name], ROLES, f"contract.rules[{index}].parameters.{name}")
        if "status" in params:
            _enum(
                params["status"], STATUSES, f"contract.rules[{index}].parameters.status"
            )
        for name in ("label", "from_label", "to_label"):
            if name in params:
                label = _label(
                    params[name], f"contract.rules[{index}].parameters.{name}"
                )
                if labels is not None and label not in labels:
                    raise PolicyConfigurationError(
                        "Contract rule label is outside the declared label space."
                    )
        if (
            metric == "critical_regression_count"
            and params["from_label"] == params["to_label"]
        ):
            raise PolicyConfigurationError(
                "critical_regression_count labels must differ."
            )
        if "dimension" in params:
            _enum(
                params["dimension"],
                frozenset({"status", "label", "score"}),
                f"contract.rules[{index}].parameters.dimension",
            )
        if metric == "provenance_present":
            owner_type = _enum(
                params["owner_type"], frozenset(owner_ids), "parameters.owner_type"
            )
            if (
                scope_id not in owner_ids[owner_type]
                or params["field"] not in PROVENANCE_FIELDS
            ):
                raise PolicyConfigurationError(
                    "provenance_present selects an unknown owner or field."
                )
        boolean_metric = metric in {
            "corpus_equal",
            "context_isolated",
            "provenance_present",
        }
        if boolean_metric:
            if operator not in {"eq", "ne"} or rule["threshold"] is not None:
                raise PolicyConfigurationError(
                    "Boolean metrics require eq/ne and threshold=null."
                )
        else:
            threshold = _decimal(
                rule["threshold"], f"contract.rules[{index}].threshold"
            )
            count_metrics = {
                "status_count",
                "new_status_count",
                "determinate_label_count",
                "determinate_label_transition_count",
                "critical_regression_count",
                "unstable_case_count",
                "invariance_violation_count",
                "invariance_not_evaluable_count",
                "anchor_disagreement_count",
            }
            if metric in count_metrics and (
                threshold < 0 or threshold != threshold.to_integral_value()
            ):
                raise PolicyConfigurationError(
                    "Count metric threshold must be a non-negative integer."
                )
            if metric in {"determinate_coverage", "anchor_coverage"} and not Decimal(
                0
            ) <= threshold <= Decimal(1):
                raise PolicyConfigurationError("Coverage threshold must lie in [0,1].")
            if metric == "determinate_coverage_delta" and not Decimal(
                -1
            ) <= threshold <= Decimal(1):
                raise PolicyConfigurationError(
                    "Coverage delta threshold must lie in [-1,1]."
                )
        missing = _enum(
            rule["missing_evidence"],
            frozenset({"hard_fail", "review", "info"}),
            f"contract.rules[{index}].missing_evidence",
        )
        if severity == "info" and missing != "info":
            raise PolicyConfigurationError("Info rule missing_evidence must be info.")
        if severity == "review" and missing == "hard_fail":
            raise PolicyConfigurationError(
                "Review rule missing_evidence cannot hard-fail."
            )
        _string(
            rule["rationale"], f"contract.rules[{index}].rationale", artifact.limits
        )
        _extensions(
            rule["extensions"], f"contract.rules[{index}].extensions", artifact.limits
        )
    _extensions(obj["extensions"], "contract.extensions", artifact.limits)
    return AssuranceContract(
        path=path.resolve(),
        source_sha256=hashlib.sha256(data).hexdigest(),
        document=obj,
    )
