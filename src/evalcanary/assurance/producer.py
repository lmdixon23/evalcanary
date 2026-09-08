"""Small zero-dependency producer for normative assurance JSONL artifacts.

Identity helpers hash only exact caller-supplied bytes or canonical JSON values.
No filename, path, environment, import, object representation, package metadata,
clock, status mapping, pairing key, ownership, relation, exception, or policy is
ever inferred.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import uuid
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
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
    SCOPES,
    SEVERITIES,
)
from .numeric import canonical_json_bytes, canonical_sha256
from .schema import (
    AssuranceArtifact,
    Limits,
    compute_manifest_sha256,
    load_artifact,
    load_contract,
)
from .structural import METRIC_SIGNATURES

ComponentValue = dict[str, Any]
Record = dict[str, Any]


def sha256_bytes(value: bytes) -> str:
    """Hash exactly the caller-supplied bytes, without interpretation."""

    return hashlib.sha256(value).hexdigest()


def sha256_value(value: Any) -> str:
    """Hash one exact caller-supplied value using assurance canonical JSON."""

    return canonical_sha256(value)


def component_value(
    presence: str,
    *,
    identity: str | None = None,
    sha256: str | None = None,
) -> ComponentValue:
    """Represent one ordinary component/provenance value explicitly."""

    if presence == "present":
        if identity is None and sha256 is None:
            raise InputValidationError(
                "A present component value requires explicit identity or SHA-256."
            )
    elif presence in {"missing", "intentionally_omitted", "not_applicable"}:
        if identity is not None or sha256 is not None:
            raise InputValidationError(
                "A non-present component value cannot carry identity or SHA-256."
            )
    else:
        raise InputValidationError("Unknown component presence value.")
    return {"presence": presence, "identity": identity, "sha256": sha256}


def _copy_map(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return deepcopy(dict(value or {}))


def _name_list(values: Collection[str]) -> str:
    return "[" + ", ".join(sorted(values)) + "]"


def _requirements(
    ownership: Mapping[str, str],
) -> tuple[set[str], set[str], dict[str, str]]:
    supplied = dict(ownership)
    missing = set(MOVABLE_COMPONENTS) - set(supplied)
    unexpected = set(supplied) - set(MOVABLE_COMPONENTS)
    invalid = {
        name
        for name in MOVABLE_COMPONENTS & set(supplied)
        if supplied[name] not in {"evaluator", "context"}
    }
    if missing or unexpected or invalid:
        raise InputValidationError(
            "Component ownership is invalid; "
            f"missing={_name_list(missing)}; "
            f"unexpected={_name_list(unexpected)}; "
            f"invalid_owner={_name_list(invalid)}."
        )
    evaluator = set(FIXED_EVALUATOR_COMPONENTS)
    context = set(FIXED_CONTEXT_COMPONENTS)
    for name in sorted(MOVABLE_COMPONENTS):
        (evaluator if supplied[name] == "evaluator" else context).add(name)
    return evaluator, context, supplied


def component_requirements(
    ownership: Mapping[str, str],
) -> dict[str, tuple[str, ...]]:
    """Return the complete deterministic inventory required by explicit ownership."""

    evaluator, context, _ = _requirements(ownership)
    return {
        "evaluator_components": tuple(sorted(evaluator)),
        "context_components": tuple(sorted(context)),
    }


def _checked_component_map(
    values: Mapping[str, ComponentValue],
    inventory_name: str,
) -> dict[str, ComponentValue]:
    result: dict[str, ComponentValue] = {}
    for name, raw in values.items():
        if not isinstance(name, str) or not isinstance(raw, Mapping):
            raise InputValidationError(
                f"The {inventory_name} inventory contains an invalid declaration."
            )
        if set(raw) != {"presence", "identity", "sha256"}:
            raise InputValidationError(
                f"The {inventory_name} inventory declaration for {name} has "
                "invalid fields."
            )
        try:
            result[name] = component_value(
                raw["presence"],
                identity=raw["identity"],
                sha256=raw["sha256"],
            )
        except InputValidationError as exc:
            raise InputValidationError(
                f"The {inventory_name} inventory declaration for {name} is invalid."
            ) from exc
    return result


@dataclass(frozen=True, slots=True)
class ComponentInventories:
    """Complete component facts bound to one explicit ownership declaration."""

    component_ownership: Mapping[str, str]
    evaluator_components: Mapping[str, ComponentValue]
    context_components: Mapping[str, ComponentValue]


def complete_components(
    *,
    ownership: Mapping[str, str],
    evaluator_components: Mapping[str, ComponentValue],
    context_components: Mapping[str, ComponentValue],
    confirm_unlisted_not_applicable: bool = False,
) -> ComponentInventories:
    """Complete unlisted owned components only after an explicit affirmation.

    The confirmation means that every owned component not explicitly declared
    present, missing, intentionally_omitted, or not_applicable is affirmed to be
    not applicable. Explicit declarations always win; no presence is inferred.
    """

    if confirm_unlisted_not_applicable is not True:
        raise InputValidationError(
            "Bulk not_applicable completion requires "
            "confirm_unlisted_not_applicable=True."
        )
    expected_evaluator, expected_context, supplied_ownership = _requirements(ownership)
    evaluator = _checked_component_map(evaluator_components, "evaluator_components")
    context = _checked_component_map(context_components, "context_components")
    duplicates = set(evaluator) & set(context)
    evaluator_unexpected = set(evaluator) - expected_evaluator
    context_unexpected = set(context) - expected_context
    if duplicates or evaluator_unexpected or context_unexpected:
        raise InputValidationError(
            "Component inventories contradict declared ownership; "
            f"evaluator_components unexpected={_name_list(evaluator_unexpected)}; "
            f"context_components unexpected={_name_list(context_unexpected)}; "
            f"duplicate_across_sides={_name_list(duplicates)}."
        )
    for name in sorted(expected_evaluator - set(evaluator)):
        evaluator[name] = component_value("not_applicable")
    for name in sorted(expected_context - set(context)):
        context[name] = component_value("not_applicable")
    return ComponentInventories(
        component_ownership=dict(sorted(supplied_ownership.items())),
        evaluator_components={
            name: deepcopy(evaluator[name]) for name in sorted(evaluator)
        },
        context_components={name: deepcopy(context[name]) for name in sorted(context)},
    )


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Explicit evaluator/context identity and component evidence for one role."""

    evaluation_id: str
    role: str
    evaluator_id: str
    evaluator_version: str
    evaluator_fingerprint_sha256: str
    context_id: str
    context_fingerprint_sha256: str
    evaluator_components: Mapping[str, ComponentValue]
    context_components: Mapping[str, ComponentValue]
    evaluator_not_applicable: Collection[str] = field(default_factory=tuple)
    context_not_applicable: Collection[str] = field(default_factory=tuple)
    provenance: Mapping[str, ComponentValue] = field(default_factory=dict)

    def document(self, ownership: Mapping[str, str]) -> Record:
        evaluator_names, context_names, _ = _requirements(ownership)
        evaluator = self._inventory(
            evaluator_names,
            self.evaluator_components,
            self.evaluator_not_applicable,
            "evaluator",
            self.role,
            self.evaluation_id,
        )
        context = self._inventory(
            context_names,
            self.context_components,
            self.context_not_applicable,
            "context",
            self.role,
            self.evaluation_id,
        )
        return {
            "evaluation_id": self.evaluation_id,
            "role": self.role,
            "evaluator_id": self.evaluator_id,
            "evaluator_version": self.evaluator_version,
            "evaluator_fingerprint_sha256": self.evaluator_fingerprint_sha256,
            "evaluator_components": evaluator,
            "context_id": self.context_id,
            "context_fingerprint_sha256": self.context_fingerprint_sha256,
            "context_components": context,
            "provenance": _copy_map(self.provenance),
        }

    @staticmethod
    def _inventory(
        expected: set[str],
        supplied: Mapping[str, ComponentValue],
        confirmed_not_applicable: Collection[str],
        inventory_name: str,
        role: str,
        evaluation_id: str,
    ) -> dict[str, ComponentValue]:
        checked_supplied = _checked_component_map(
            supplied, f"{inventory_name}_components"
        )
        confirmed_items = list(confirmed_not_applicable)
        if not all(isinstance(name, str) for name in confirmed_items):
            raise InputValidationError(
                f"The {inventory_name} inventory for role={role} "
                f"evaluation={evaluation_id} contains an invalid component name."
            )
        supplied_names = set(checked_supplied)
        confirmed = set(confirmed_items)
        repeated_confirmations = {
            name for name, count in Counter(confirmed_items).items() if count > 1
        }
        duplicates = (supplied_names & confirmed) | repeated_confirmations
        declared = supplied_names | confirmed
        missing = expected - declared
        unexpected = declared - expected
        if missing or unexpected or duplicates:
            raise InputValidationError(
                f"{role} evaluation {evaluation_id} {inventory_name}_components "
                "inventory is invalid; "
                f"missing={_name_list(missing)}; "
                f"unexpected={_name_list(unexpected)}; "
                f"duplicate_supplied_or_not_applicable={_name_list(duplicates)}."
            )
        return {
            name: (
                deepcopy(checked_supplied[name])
                if name in checked_supplied
                else component_value("not_applicable")
            )
            for name in sorted(expected)
        }


def make_evaluation(
    *,
    evaluation_id: str,
    role: str,
    evaluator_id: str,
    evaluator_version: str,
    evaluator_fingerprint_sha256: str,
    context_id: str,
    context_fingerprint_sha256: str,
    component_ownership: Mapping[str, str],
    components: ComponentInventories,
    provenance: Mapping[str, ComponentValue],
) -> Evaluation:
    """Create an Evaluation from complete facts without choosing any semantics."""

    _, _, checked_ownership = _requirements(component_ownership)
    if checked_ownership != dict(components.component_ownership):
        raise InputValidationError(
            "Evaluation component ownership does not match completed inventories."
        )
    return Evaluation(
        evaluation_id=evaluation_id,
        role=role,
        evaluator_id=evaluator_id,
        evaluator_version=evaluator_version,
        evaluator_fingerprint_sha256=evaluator_fingerprint_sha256,
        context_id=context_id,
        context_fingerprint_sha256=context_fingerprint_sha256,
        evaluator_components=deepcopy(dict(components.evaluator_components)),
        context_components=deepcopy(dict(components.context_components)),
        provenance=_copy_map(provenance),
    )


def complete_evaluation(
    *,
    evaluation_id: str,
    role: str,
    evaluator_id: str,
    evaluator_version: str,
    evaluator_fingerprint_sha256: str,
    context_id: str,
    context_fingerprint_sha256: str,
    component_ownership: Mapping[str, str],
    component_values: Mapping[str, ComponentValue],
    confirm_unlisted_not_applicable: bool,
    provenance: Mapping[str, ComponentValue],
) -> Evaluation:
    """Create one evaluation from explicit ownership and flat component facts.

    Fixed ownership comes from the locked vocabulary; ownership for each movable
    component comes only from ``component_ownership``. Unlisted facts are filled
    only after the caller's explicit bulk not-applicable affirmation.
    """

    evaluator_names, context_names, _ = _requirements(component_ownership)
    checked = _checked_component_map(component_values, "component_values")
    unexpected = set(checked) - evaluator_names - context_names
    if unexpected:
        raise InputValidationError(
            "The flat component inventory contains unexpected names; "
            f"unexpected={_name_list(unexpected)}."
        )
    completed = complete_components(
        ownership=component_ownership,
        evaluator_components={
            name: value for name, value in checked.items() if name in evaluator_names
        },
        context_components={
            name: value for name, value in checked.items() if name in context_names
        },
        confirm_unlisted_not_applicable=confirm_unlisted_not_applicable,
    )
    return make_evaluation(
        evaluation_id=evaluation_id,
        role=role,
        evaluator_id=evaluator_id,
        evaluator_version=evaluator_version,
        evaluator_fingerprint_sha256=evaluator_fingerprint_sha256,
        context_id=context_id,
        context_fingerprint_sha256=context_fingerprint_sha256,
        component_ownership=component_ownership,
        components=completed,
        provenance=provenance,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class Rule:
    """One semantics-explicit contract rule from the closed metric vocabulary."""

    rule_id: str
    severity: str
    scope: str
    scope_id: str | None
    metric: str
    parameters: Mapping[str, Any]
    operator: str
    threshold: Any
    missing_evidence: str
    rationale: str
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def document(self) -> Record:
        if self.metric not in METRICS:
            raise InputValidationError("Contract rule metric is not registered.")
        if self.severity not in SEVERITIES:
            raise InputValidationError("Contract rule severity is not registered.")
        if self.scope not in SCOPES:
            raise InputValidationError("Contract rule scope is not registered.")
        if self.operator not in OPERATORS:
            raise InputValidationError("Contract rule operator is not registered.")
        if self.missing_evidence not in {"hard_fail", "review", "info"}:
            raise InputValidationError(
                "Contract rule missing-evidence policy is not registered."
            )
        allowed_scopes, required_parameters = METRIC_SIGNATURES[self.metric]
        if self.scope not in allowed_scopes:
            raise InputValidationError(
                "Contract rule metric uses an unsupported scope."
            )
        supplied_parameters = set(self.parameters)
        missing = set(required_parameters) - supplied_parameters
        unexpected = supplied_parameters - set(required_parameters)
        if missing or unexpected:
            raise InputValidationError(
                f"Contract rule {self.rule_id} parameters are invalid; "
                f"missing={_name_list(missing)}; "
                f"unexpected={_name_list(unexpected)}."
            )
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "scope": self.scope,
            "scope_id": self.scope_id,
            "metric": self.metric,
            "operator": self.operator,
            "threshold": deepcopy(self.threshold),
            "parameters": _copy_map(self.parameters),
            "missing_evidence": self.missing_evidence,
            "rationale": self.rationale,
            "extensions": _copy_map(self.extensions),
        }


@dataclass(frozen=True, slots=True)
class Contract:
    """Small deterministic contract authoring surface with no policy defaults."""

    contract_id: str
    contract_version: str
    rules: Collection[Rule]
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def document(self) -> Record:
        rules = sorted(
            (rule.document() for rule in self.rules),
            key=lambda item: item["rule_id"],
        )
        if not rules:
            raise InputValidationError("Contract rules must be non-empty.")
        rule_ids = [item["rule_id"] for item in rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise InputValidationError("Contract rule IDs must be unique.")
        return {
            "schema_version": CONTRACT_SCHEMA,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "applies_to_input_schema": INPUT_SCHEMA,
            "rules": rules,
            "extensions": _copy_map(self.extensions),
        }

    def canonical_bytes(self) -> bytes:
        """Serialize deterministically; artifact-bound semantics validate on write."""

        return canonical_json_bytes(self.document()) + b"\n"

    def write(
        self,
        path: Path,
        *,
        artifact: AssuranceArtifact | str | os.PathLike[str],
    ) -> Path:
        """Validate against a loaded artifact or finalized input path, then publish.

        Path-like inputs are loaded only through the normative ``load_artifact``
        validator. Advanced callers may pass an already-loaded
        ``AssuranceArtifact`` without reloading it.
        """

        loaded_artifact = (
            artifact
            if isinstance(artifact, AssuranceArtifact)
            else load_artifact(_artifact_path(artifact))
        )
        data = self.canonical_bytes()
        return _atomic_write_bytes(
            path,
            data,
            description="Contract output",
            validator=lambda candidate: load_contract(candidate, loaded_artifact),
        )


class AssurancePacket:
    """Collect records, deterministically finalize them, and validate before write."""

    def __init__(
        self,
        *,
        artifact_id: str,
        corpus_id: str,
        identity_level: str,
        judgment_spec: Mapping[str, Any],
        evaluations: Collection[Evaluation],
        component_ownership: Mapping[str, str],
        provenance: Mapping[str, ComponentValue],
        allowed_context_differences: Sequence[Mapping[str, Any]],
        extensions: Mapping[str, Any] | None = None,
    ) -> None:
        self._artifact_id = artifact_id
        self._corpus_id = corpus_id
        self._identity_level = identity_level
        self._judgment_spec = _copy_map(judgment_spec)
        self._evaluations = tuple(evaluations)
        self._ownership = dict(component_ownership)
        self._provenance = _copy_map(provenance)
        self._context_differences = [
            _copy_map(item) for item in allowed_context_differences
        ]
        self._extensions = _copy_map(extensions)
        self._cases: list[Record] = []
        self._trials: list[Record] = []
        self._critical_groups: list[Record] = []
        self._invariance_groups: list[Record] = []
        self._anchor_sets: list[Record] = []
        self._anchors: list[Record] = []

    @property
    def evaluation_ids_by_role(self) -> Mapping[str, str]:
        """Return the exact declared baseline/candidate IDs as a read-only mapping."""

        by_role: dict[str, list[str]] = {"baseline": [], "candidate": []}
        for evaluation in self._evaluations:
            if evaluation.role in by_role:
                by_role[evaluation.role].append(evaluation.evaluation_id)
        if len(self._evaluations) != 2 or any(
            len(by_role[role]) != 1 for role in ("baseline", "candidate")
        ):
            raise InputValidationError(
                "Evaluation roles must contain exactly one baseline and one candidate."
            )
        return MappingProxyType(
            {role: by_role[role][0] for role in ("baseline", "candidate")}
        )

    def add_case(
        self,
        case_id: str,
        *,
        content_sha256: str | None = None,
        content_bytes: bytes | None = None,
        critical_group_ids: Collection[str],
        invariance_group_ids: Collection[str],
        tags: Collection[str] = (),
        display_label: str | None = None,
        extensions: Mapping[str, Any] | None = None,
    ) -> AssurancePacket:
        if content_sha256 is not None and content_bytes is not None:
            raise InputValidationError(
                "Supply either content_sha256 or exact content_bytes, not both."
            )
        digest = (
            sha256_bytes(content_bytes) if content_bytes is not None else content_sha256
        )
        self._cases.append(
            {
                "record_type": "case",
                "case_id": case_id,
                "manifest_position": 0,
                "content_sha256": digest,
                "critical_group_ids": sorted(critical_group_ids),
                "invariance_group_ids": sorted(invariance_group_ids),
                "tags": sorted(tags),
                "display_label": display_label,
                "extensions": _copy_map(extensions),
            }
        )
        return self

    def add_cases(self, cases: Sequence[Mapping[str, Any]]) -> AssurancePacket:
        """Add already-semantic normalized case declarations in one call."""

        for case in cases:
            self.add_case(**deepcopy(dict(case)))
        return self

    def add_trial(
        self,
        *,
        case_id: str,
        evaluation_id: str,
        trial_id: str,
        source_order: int,
        status: str,
        pairing_key: str | None,
        label: str | None,
        score: Any,
        error: Mapping[str, Any] | None,
        reason: str | None = None,
        details: Any = None,
        provenance: Mapping[str, ComponentValue] | None = None,
        extensions: Mapping[str, Any] | None = None,
    ) -> AssurancePacket:
        self._trials.append(
            {
                "record_type": "trial",
                "case_id": case_id,
                "evaluation_id": evaluation_id,
                "trial_id": trial_id,
                "source_order": source_order,
                "pairing_key": pairing_key,
                "status": status,
                "label": label,
                "score": score,
                "reason": reason,
                "details": deepcopy(details),
                "error": None if error is None else _copy_map(error),
                "provenance": _copy_map(provenance),
                "extensions": _copy_map(extensions),
            }
        )
        return self

    def add_trials(self, trials: Sequence[Mapping[str, Any]]) -> AssurancePacket:
        """Add already-semantic normalized trial declarations in one call."""

        for trial in trials:
            self.add_trial(**deepcopy(dict(trial)))
        return self

    def add_critical_group(
        self,
        group_id: str,
        *,
        title: str,
        declaration_source: str,
        rationale: str,
        extensions: Mapping[str, Any] | None = None,
    ) -> AssurancePacket:
        self._critical_groups.append(
            {
                "record_type": "critical_group",
                "group_id": group_id,
                "title": title,
                "declaration_source": declaration_source,
                "rationale": rationale,
                "extensions": _copy_map(extensions),
            }
        )
        return self

    def add_invariance_group(
        self,
        group_id: str,
        *,
        member_case_ids: Sequence[str],
        transformation_id: str,
        transformation_version: str,
        expected_relation: str,
        relation_parameters: Mapping[str, Any],
        severity: str,
        declaration_source: str,
        rationale: str,
        extensions: Mapping[str, Any] | None = None,
    ) -> AssurancePacket:
        self._invariance_groups.append(
            {
                "record_type": "invariance_group",
                "group_id": group_id,
                "member_case_ids": list(member_case_ids),
                "transformation_id": transformation_id,
                "transformation_version": transformation_version,
                "expected_relation": expected_relation,
                "relation_parameters": _copy_map(relation_parameters),
                "severity": severity,
                "declaration_source": declaration_source,
                "rationale": rationale,
                "extensions": _copy_map(extensions),
            }
        )
        return self

    def add_anchor_set(
        self,
        anchor_set_id: str,
        *,
        label_space: Sequence[str],
        protocol_id: str,
        protocol_version: str,
        aggregation_method: str,
        clustering_unit: str,
        source_revision: str,
        source_sha256: str,
        license: str,
        provenance: Mapping[str, ComponentValue] | None = None,
        extensions: Mapping[str, Any] | None = None,
    ) -> AssurancePacket:
        self._anchor_sets.append(
            {
                "record_type": "anchor_set",
                "anchor_set_id": anchor_set_id,
                "label_space": list(label_space),
                "protocol_id": protocol_id,
                "protocol_version": protocol_version,
                "aggregation_method": aggregation_method,
                "clustering_unit": clustering_unit,
                "source_revision": source_revision,
                "source_sha256": source_sha256,
                "license": license,
                "provenance": _copy_map(provenance),
                "extensions": _copy_map(extensions),
            }
        )
        return self

    def add_anchor(
        self,
        anchor_id: str,
        *,
        anchor_set_id: str,
        case_id: str,
        cluster_id: str,
        annotation_id: str,
        annotator_id: str | None,
        kind: str,
        status: str,
        label: str | None,
        reason: str | None = None,
        aggregation_inputs: Collection[str] = (),
        adjudication_rationale: str | None = None,
        provenance: Mapping[str, ComponentValue] | None = None,
        extensions: Mapping[str, Any] | None = None,
    ) -> AssurancePacket:
        self._anchors.append(
            {
                "record_type": "anchor",
                "anchor_id": anchor_id,
                "anchor_set_id": anchor_set_id,
                "case_id": case_id,
                "cluster_id": cluster_id,
                "annotation_id": annotation_id,
                "annotator_id": annotator_id,
                "kind": kind,
                "status": status,
                "label": label,
                "reason": reason,
                "aggregation_inputs": sorted(aggregation_inputs),
                "adjudication_rationale": adjudication_rationale,
                "provenance": _copy_map(provenance),
                "extensions": _copy_map(extensions),
            }
        )
        return self

    def add_anchors(self, anchors: Sequence[Mapping[str, Any]]) -> AssurancePacket:
        """Add already-semantic normalized anchor declarations in one call."""

        for anchor in anchors:
            self.add_anchor(**deepcopy(dict(anchor)))
        return self

    def canonical_records(self) -> tuple[Record, ...]:
        """Finalize records in stable identity order and compute the manifest."""

        cases = sorted(deepcopy(self._cases), key=lambda item: item["case_id"])
        for position, item in enumerate(cases):
            item["manifest_position"] = position
        critical = sorted(
            deepcopy(self._critical_groups), key=lambda item: item["group_id"]
        )
        invariance = sorted(
            deepcopy(self._invariance_groups), key=lambda item: item["group_id"]
        )
        anchor_sets = sorted(
            deepcopy(self._anchor_sets), key=lambda item: item["anchor_set_id"]
        )
        trials = sorted(
            deepcopy(self._trials),
            key=lambda item: (
                item["case_id"],
                item["evaluation_id"],
                item["source_order"],
                item["trial_id"],
            ),
        )
        anchors = sorted(deepcopy(self._anchors), key=lambda item: item["anchor_id"])
        evaluations = sorted(
            (item.document(self._ownership) for item in self._evaluations),
            key=lambda item: item["role"],
        )
        header: Record = {
            "record_type": "header",
            "schema_version": INPUT_SCHEMA,
            "artifact_id": self._artifact_id,
            "corpus": {
                "corpus_id": self._corpus_id,
                "manifest_sha256": "0" * 64,
                "case_count": len(cases),
                "identity_level": self._identity_level,
                "manifest_algorithm": MANIFEST_ALGORITHM,
            },
            "judgment_spec": deepcopy(self._judgment_spec),
            "evaluations": evaluations,
            "component_ownership": dict(sorted(self._ownership.items())),
            "allowed_context_differences": sorted(
                deepcopy(self._context_differences),
                key=lambda item: item.get("component", ""),
            ),
            "provenance": deepcopy(self._provenance),
            "extensions": deepcopy(self._extensions),
        }
        header["corpus"]["manifest_sha256"] = compute_manifest_sha256(
            header, cases, critical, invariance
        )
        return tuple(
            [header, *critical, *invariance, *anchor_sets, *cases, *trials, *anchors]
        )

    def canonical_bytes(self, *, limits: Limits | None = None) -> bytes:
        """Serialize and validate through the same normative migrate validator."""

        records = self.canonical_records()
        data = b"\n".join(canonical_json_bytes(item) for item in records) + b"\n"
        with tempfile.TemporaryDirectory(
            prefix="evalcanary-producer-validate-"
        ) as temp:
            candidate = Path(temp) / "candidate.jsonl"
            candidate.write_bytes(data)
            load_artifact(candidate, limits=limits)
        return data

    def write(self, path: Path, *, limits: Limits | None = None) -> Path:
        """Validate first, then atomically publish one canonical JSONL file."""

        data = self.canonical_bytes(limits=limits)
        return _atomic_write_bytes(path, data, description="Producer output")


_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _artifact_path(value: str | os.PathLike[str]) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise InputValidationError(
            "Contract artifact must be an AssuranceArtifact or a path-like input."
        )
    try:
        return Path(value)
    except (OSError, TypeError, ValueError) as exc:
        raise InputValidationError(
            "Contract artifact path could not be interpreted safely."
        ) from exc


def _validate_target(path: Path) -> Path:
    target = Path(os.path.abspath(os.fspath(path)))
    components: list[Path] = []
    current = target
    while True:
        components.append(current)
        if current.parent == current:
            break
        current = current.parent
    missing = False
    for index, component in enumerate(reversed(components)):
        try:
            info = os.lstat(component)
        except FileNotFoundError:
            missing = True
            continue
        except OSError as exc:
            raise InputValidationError(
                "Producer output path could not be inspected safely."
            ) from exc
        if missing:
            raise InputValidationError(
                "Producer output topology changed during validation."
            )
        is_reparse = stat.S_ISLNK(info.st_mode) or bool(
            getattr(info, "st_file_attributes", 0) & _REPARSE_POINT
        )
        if is_reparse:
            raise InputValidationError(
                "Producer output must not traverse a reparse point or symbolic link."
            )
        is_target = index == len(components) - 1
        if is_target:
            if not stat.S_ISREG(info.st_mode):
                raise InputValidationError(
                    "Producer output target exists and is not a regular file."
                )
        elif not stat.S_ISDIR(info.st_mode):
            raise InputValidationError(
                "Producer output path has a non-directory ancestor."
            )
    return target


def _atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    description: str,
    validator: Any = None,
) -> Path:
    target = _validate_target(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InputValidationError(
            f"{description} could not be written atomically."
        ) from exc
    _validate_target(target)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if validator is not None:
            validator(temporary)
        _validate_target(target)
        os.replace(temporary, target)
    except OSError as exc:
        raise InputValidationError(
            f"{description} could not be written atomically."
        ) from exc
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        with suppress(FileNotFoundError):
            temporary.unlink()
    return target


__all__ = [
    "AssurancePacket",
    "ComponentInventories",
    "ComponentValue",
    "Contract",
    "Evaluation",
    "Rule",
    "complete_components",
    "complete_evaluation",
    "component_requirements",
    "component_value",
    "make_evaluation",
    "sha256_bytes",
    "sha256_value",
]
