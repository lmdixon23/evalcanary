"""Bounded, privacy-safe assurance authoring preflight."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import EvalCanaryError
from . import schema as runtime
from .constants import (
    CONTRACT_SCHEMA,
    INPUT_SCHEMA,
    METRICS,
    OPERATORS,
    RECORD_TYPES,
    ROLES,
    SCOPES,
    SEVERITIES,
    STATUSES,
)
from .schema import AssuranceArtifact, Limits
from .structural import FIELD_REGISTRY, METRIC_SIGNATURES

PREFLIGHT_SCHEMA = "evaluator-assurance-preflight-v1"
MAX_PREFLIGHT_DIAGNOSTICS = 100


@dataclass(frozen=True, slots=True)
class PreflightDiagnostic:
    """One safe diagnostic that never includes the rejected value."""

    code: str
    source_kind: str
    json_path: str
    expected: str
    schema_id: str
    line: int | None = None
    record: int | None = None

    def document(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "source_kind": self.source_kind,
            "json_path": self.json_path,
            "expected": self.expected,
            "schema_id": self.schema_id,
        }
        if self.line is not None:
            result["line"] = self.line
        if self.record is not None:
            result["record"] = self.record
        return result


@dataclass(slots=True)
class _Collector:
    diagnostics: list[PreflightDiagnostic] = field(default_factory=list)
    omitted: int = 0

    def add(
        self,
        code: str,
        source_kind: str,
        json_path: str,
        expected: str,
        schema_id: str,
        *,
        line: int | None = None,
        record: int | None = None,
    ) -> None:
        item = PreflightDiagnostic(
            code=code,
            source_kind=source_kind,
            json_path=json_path,
            expected=expected,
            schema_id=schema_id,
            line=line,
            record=record,
        )
        if len(self.diagnostics) < MAX_PREFLIGHT_DIAGNOSTICS:
            self.diagnostics.append(item)
        else:
            self.omitted += 1


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """Validation-only result; it contains no migration policy outcome."""

    diagnostics: tuple[PreflightDiagnostic, ...]
    diagnostics_omitted: int

    @property
    def valid(self) -> bool:
        return not self.diagnostics and self.diagnostics_omitted == 0

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": PREFLIGHT_SCHEMA,
            "mode": "VALIDATION_ONLY",
            "valid": self.valid,
            "diagnostic_limit": MAX_PREFLIGHT_DIAGNOSTICS,
            "diagnostic_count": len(self.diagnostics),
            "diagnostics_omitted": self.diagnostics_omitted,
            "diagnostics": [item.document() for item in self.diagnostics],
        }


def _expected_fields(name: str) -> str:
    return "exact fields: " + ", ".join(sorted(FIELD_REGISTRY[name]))


def _check_exact_fields(
    value: Any,
    registry_name: str,
    collector: _Collector,
    *,
    source_kind: str,
    json_path: str,
    schema_id: str,
    line: int | None = None,
    record: int | None = None,
) -> bool:
    if not isinstance(value, dict):
        collector.add(
            "EXPECTED_OBJECT",
            source_kind,
            json_path,
            _expected_fields(registry_name),
            schema_id,
            line=line,
            record=record,
        )
        return False
    expected = FIELD_REGISTRY[registry_name]
    for name in sorted(expected - set(value)):
        collector.add(
            "MISSING_REQUIRED_FIELD",
            source_kind,
            f"{json_path}/{name}",
            f"required field {name}",
            schema_id,
            line=line,
            record=record,
        )
    for _name in sorted(set(value) - expected):
        collector.add(
            "UNKNOWN_FIELD",
            source_kind,
            json_path,
            _expected_fields(registry_name),
            schema_id,
            line=line,
            record=record,
        )
    return set(value) == expected


def _check_enum(
    value: Any,
    allowed: Collection[str],
    collector: _Collector,
    *,
    source_kind: str,
    json_path: str,
    schema_id: str,
    line: int | None = None,
    record: int | None = None,
) -> None:
    choices = sorted(allowed)
    if not isinstance(value, str) or value not in choices:
        collector.add(
            "UNKNOWN_ENUM_VALUE",
            source_kind,
            json_path,
            "one of: " + ", ".join(choices),
            schema_id,
            line=line,
            record=record,
        )


def _scan_nested_record(
    obj: dict[str, Any],
    record_type: str,
    collector: _Collector,
    *,
    line: int,
    record: int,
) -> None:
    common = {
        "header": (
            ("corpus", "corpus"),
            ("judgment_spec", "judgment_spec"),
            ("component_ownership", "component_ownership"),
        ),
    }
    for field_name, registry_name in common.get(record_type, ()):
        if field_name in obj:
            _check_exact_fields(
                obj[field_name],
                registry_name,
                collector,
                source_kind="input",
                json_path=f"/{field_name}",
                schema_id=INPUT_SCHEMA,
                line=line,
                record=record,
            )
    if record_type == "header":
        judgment = obj.get("judgment_spec")
        if isinstance(judgment, dict):
            _check_enum(
                judgment.get("kind"),
                {"categorical", "numeric", "categorical_and_numeric"},
                collector,
                source_kind="input",
                json_path="/judgment_spec/kind",
                schema_id=INPUT_SCHEMA,
                line=line,
                record=record,
            )
            score = judgment.get("score_spec")
            if score is not None:
                _check_exact_fields(
                    score,
                    "score_spec",
                    collector,
                    source_kind="input",
                    json_path="/judgment_spec/score_spec",
                    schema_id=INPUT_SCHEMA,
                    line=line,
                    record=record,
                )
        evaluations = obj.get("evaluations")
        if not isinstance(evaluations, list):
            collector.add(
                "EXPECTED_ARRAY",
                "input",
                "/evaluations",
                "exactly two evaluation objects",
                INPUT_SCHEMA,
                line=line,
                record=record,
            )
        else:
            for index, evaluation in enumerate(evaluations):
                _check_exact_fields(
                    evaluation,
                    "evaluation",
                    collector,
                    source_kind="input",
                    json_path=f"/evaluations/{index}",
                    schema_id=INPUT_SCHEMA,
                    line=line,
                    record=record,
                )
                if isinstance(evaluation, dict):
                    _check_enum(
                        evaluation.get("role"),
                        ROLES,
                        collector,
                        source_kind="input",
                        json_path=f"/evaluations/{index}/role",
                        schema_id=INPUT_SCHEMA,
                        line=line,
                        record=record,
                    )
    elif record_type == "trial":
        _check_enum(
            obj.get("status"),
            STATUSES,
            collector,
            source_kind="input",
            json_path="/status",
            schema_id=INPUT_SCHEMA,
            line=line,
            record=record,
        )


def _scan_input(
    path: Path, limits: Limits, collector: _Collector
) -> AssuranceArtifact | None:
    try:
        with path.open("rb") as handle:
            data = handle.read(limits.get("total_input_bytes") + 1)
    except OSError:
        collector.add(
            "SOURCE_UNREADABLE",
            "input",
            "$",
            "readable local UTF-8 JSONL input",
            INPUT_SCHEMA,
        )
        return None
    if len(data) > limits.get("total_input_bytes"):
        collector.add(
            "RESOURCE_LIMIT_EXCEEDED",
            "input",
            "$",
            "input within configured total_input_bytes limit",
            INPUT_SCHEMA,
        )
        return None
    if data.startswith(b"\xef\xbb\xbf"):
        collector.add(
            "UTF8_BOM_FORBIDDEN",
            "input",
            "$",
            "UTF-8 JSONL without a byte-order mark",
            INPUT_SCHEMA,
        )
    structural_before = len(collector.diagnostics) + collector.omitted
    for line_number, raw in enumerate(data.splitlines(keepends=True), start=1):
        if len(raw) > limits.get("line_bytes"):
            collector.add(
                "RESOURCE_LIMIT_EXCEEDED",
                "input",
                "$record",
                "record within configured line_bytes limit",
                INPUT_SCHEMA,
                line=line_number,
            )
            continue
        payload = raw[:-1] if raw.endswith(b"\n") else raw
        if payload.endswith(b"\r"):
            payload = payload[:-1]
        if not payload:
            collector.add(
                "BLANK_JSONL_RECORD",
                "input",
                "$record",
                "one JSON object per non-blank line",
                INPUT_SCHEMA,
                line=line_number,
            )
            continue
        try:
            obj = runtime._loads_strict(payload, source="preflight input")
        except (EvalCanaryError, UnicodeError):
            collector.add(
                "INVALID_JSON",
                "input",
                "$record",
                "strict UTF-8 JSON using bounded finite numeric tokens",
                INPUT_SCHEMA,
                line=line_number,
            )
            continue
        record = line_number - 1
        if not isinstance(obj, dict):
            collector.add(
                "EXPECTED_OBJECT",
                "input",
                "$record",
                "JSON object with a registered record_type",
                INPUT_SCHEMA,
                line=line_number,
                record=record,
            )
            continue
        record_type = obj.get("record_type")
        if not isinstance(record_type, str) or record_type not in RECORD_TYPES:
            collector.add(
                "UNKNOWN_RECORD_TYPE",
                "input",
                "/record_type",
                "one of: " + ", ".join(sorted(RECORD_TYPES)),
                INPUT_SCHEMA,
                line=line_number,
                record=record,
            )
            continue
        _check_exact_fields(
            obj,
            record_type,
            collector,
            source_kind="input",
            json_path="$record",
            schema_id=INPUT_SCHEMA,
            line=line_number,
            record=record,
        )
        _scan_nested_record(
            obj, record_type, collector, line=line_number, record=record
        )
    if len(collector.diagnostics) + collector.omitted != structural_before:
        return None
    try:
        return runtime.load_artifact(path, limits=limits)
    except EvalCanaryError:
        collector.add(
            "RUNTIME_SEMANTICS_INVALID",
            "input",
            "$",
            "valid JSONL ordering, identities, references, pairing, ownership, manifest, and resource semantics",
            INPUT_SCHEMA,
        )
        return None


def _scan_contract_structure(document: Any, collector: _Collector) -> bool:
    start = len(collector.diagnostics) + collector.omitted
    if not _check_exact_fields(
        document,
        "contract",
        collector,
        source_kind="contract",
        json_path="$",
        schema_id=CONTRACT_SCHEMA,
    ):
        return False
    assert isinstance(document, dict)
    if document.get("schema_version") != CONTRACT_SCHEMA:
        collector.add(
            "SCHEMA_ID_MISMATCH",
            "contract",
            "/schema_version",
            CONTRACT_SCHEMA,
            CONTRACT_SCHEMA,
        )
    if document.get("applies_to_input_schema") != INPUT_SCHEMA:
        collector.add(
            "INPUT_SCHEMA_BINDING_MISMATCH",
            "contract",
            "/applies_to_input_schema",
            INPUT_SCHEMA,
            CONTRACT_SCHEMA,
        )
    rules = document.get("rules")
    if not isinstance(rules, list) or not rules:
        collector.add(
            "RULES_REQUIRED",
            "contract",
            "/rules",
            "non-empty array of rule objects",
            CONTRACT_SCHEMA,
        )
        return False
    for index, rule in enumerate(rules):
        path = f"/rules/{index}"
        _check_exact_fields(
            rule,
            "rule",
            collector,
            source_kind="contract",
            json_path=path,
            schema_id=CONTRACT_SCHEMA,
            record=index,
        )
        if not isinstance(rule, dict):
            continue
        for field_name, allowed in (
            ("severity", SEVERITIES),
            ("scope", SCOPES),
            ("metric", METRICS),
            ("operator", OPERATORS),
        ):
            _check_enum(
                rule.get(field_name),
                allowed,
                collector,
                source_kind="contract",
                json_path=f"{path}/{field_name}",
                schema_id=CONTRACT_SCHEMA,
                record=index,
            )
        metric = rule.get("metric")
        scope = rule.get("scope")
        params = rule.get("parameters")
        if isinstance(metric, str) and metric in METRIC_SIGNATURES:
            scopes, parameter_names = METRIC_SIGNATURES[metric]
            if scope not in scopes:
                collector.add(
                    "UNSUPPORTED_METRIC_SCOPE",
                    "contract",
                    f"{path}/scope",
                    "one of: " + ", ".join(sorted(scopes)),
                    CONTRACT_SCHEMA,
                    record=index,
                )
            if not isinstance(params, dict):
                collector.add(
                    "EXPECTED_OBJECT",
                    "contract",
                    f"{path}/parameters",
                    "exact parameters: " + ", ".join(sorted(parameter_names)),
                    CONTRACT_SCHEMA,
                    record=index,
                )
            else:
                for name in sorted(parameter_names - set(params)):
                    collector.add(
                        "MISSING_METRIC_PARAMETER",
                        "contract",
                        f"{path}/parameters/{name}",
                        f"required metric parameter {name}",
                        CONTRACT_SCHEMA,
                        record=index,
                    )
                for _name in sorted(set(params) - parameter_names):
                    collector.add(
                        "UNSUPPORTED_METRIC_PARAMETER",
                        "contract",
                        f"{path}/parameters",
                        "allowed parameters: " + ", ".join(sorted(parameter_names)),
                        CONTRACT_SCHEMA,
                        record=index,
                    )
        severity = rule.get("severity")
        missing = rule.get("missing_evidence")
        if missing not in {"hard_fail", "review", "info"}:
            collector.add(
                "UNKNOWN_ENUM_VALUE",
                "contract",
                f"{path}/missing_evidence",
                "one of: hard_fail, info, review",
                CONTRACT_SCHEMA,
                record=index,
            )
        elif (severity == "info" and missing != "info") or (
            severity == "review" and missing == "hard_fail"
        ):
            collector.add(
                "INCOMPATIBLE_MISSING_EVIDENCE",
                "contract",
                f"{path}/missing_evidence",
                "missing-evidence disposition compatible with rule severity",
                CONTRACT_SCHEMA,
                record=index,
            )
    return len(collector.diagnostics) + collector.omitted == start


def _scan_contract(
    path: Path | None,
    artifact: AssuranceArtifact | None,
    collector: _Collector,
    limits: Limits,
) -> None:
    if path is None:
        return
    try:
        with path.open("rb") as handle:
            data = handle.read(limits.get("total_input_bytes") + 1)
    except OSError:
        collector.add(
            "SOURCE_UNREADABLE",
            "contract",
            "$",
            "readable local UTF-8 JSON contract",
            CONTRACT_SCHEMA,
        )
        return
    if len(data) > limits.get("total_input_bytes"):
        collector.add(
            "RESOURCE_LIMIT_EXCEEDED",
            "contract",
            "$",
            "contract within configured total_input_bytes limit",
            CONTRACT_SCHEMA,
        )
        return
    try:
        document = runtime._loads_strict(data, source="preflight contract")
    except (EvalCanaryError, UnicodeError):
        collector.add(
            "INVALID_JSON",
            "contract",
            "$",
            "strict UTF-8 JSON using bounded finite numeric tokens",
            CONTRACT_SCHEMA,
        )
        return
    structurally_valid = _scan_contract_structure(document, collector)
    if structurally_valid and artifact is not None:
        try:
            runtime.load_contract(path, artifact)
        except EvalCanaryError:
            collector.add(
                "RUNTIME_SEMANTICS_INVALID",
                "contract",
                "$",
                "valid rule identity, scope references, labels, thresholds, and semantic combinations",
                CONTRACT_SCHEMA,
            )


def preflight_paths(
    input_path: Path,
    *,
    contract_path: Path | None = None,
    limits_path: Path | None = None,
) -> PreflightResult:
    """Validate migrate inputs without evaluating policy or writing output."""

    collector = _Collector()
    try:
        limits = Limits.from_path(limits_path)
    except EvalCanaryError:
        collector.add(
            "LIMITS_INVALID",
            "limits",
            "$",
            "valid bounded local resource-limit override document",
            "evaluator-assurance-limits-v1",
        )
        limits = Limits()
    artifact = _scan_input(input_path, limits, collector)
    _scan_contract(contract_path, artifact, collector, limits)
    return PreflightResult(tuple(collector.diagnostics), collector.omitted)
