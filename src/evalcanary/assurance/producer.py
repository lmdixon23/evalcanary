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
from collections.abc import Collection, Mapping, Sequence
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import InputValidationError
from .constants import (
    FIXED_CONTEXT_COMPONENTS,
    FIXED_EVALUATOR_COMPONENTS,
    INPUT_SCHEMA,
    MANIFEST_ALGORITHM,
    MOVABLE_COMPONENTS,
)
from .numeric import canonical_json_bytes, canonical_sha256
from .schema import Limits, compute_manifest_sha256, load_artifact

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
        evaluator_names = set(FIXED_EVALUATOR_COMPONENTS)
        context_names = set(FIXED_CONTEXT_COMPONENTS)
        for name in MOVABLE_COMPONENTS:
            owner = ownership.get(name)
            if owner == "evaluator":
                evaluator_names.add(name)
            elif owner == "context":
                context_names.add(name)
            else:
                raise InputValidationError(
                    "Parser and aggregation-policy ownership must be explicit."
                )
        evaluator = self._inventory(
            evaluator_names,
            self.evaluator_components,
            self.evaluator_not_applicable,
            "evaluator",
        )
        context = self._inventory(
            context_names,
            self.context_components,
            self.context_not_applicable,
            "context",
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
    ) -> dict[str, ComponentValue]:
        supplied_names = set(supplied)
        confirmed = set(confirmed_not_applicable)
        if supplied_names & confirmed:
            raise InputValidationError(
                f"The {inventory_name} inventory declares a component twice."
            )
        if supplied_names | confirmed != expected:
            raise InputValidationError(
                f"The {inventory_name} inventory must explicitly supply or confirm "
                "not_applicable for every owned component."
            )
        return {
            name: (
                deepcopy(supplied[name])
                if name in supplied
                else component_value("not_applicable")
            )
            for name in sorted(expected)
        }


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
        allowed_context_differences: Sequence[Mapping[str, Any]] = (),
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

    def add_case(
        self,
        case_id: str,
        *,
        content_sha256: str | None = None,
        content_bytes: bytes | None = None,
        critical_group_ids: Collection[str] = (),
        invariance_group_ids: Collection[str] = (),
        tags: Collection[str] = (),
        display_label: str | None = None,
        extensions: Mapping[str, Any] | None = None,
    ) -> AssurancePacket:
        if content_sha256 is not None and content_bytes is not None:
            raise InputValidationError(
                "Supply either content_sha256 or exact content_bytes, not both."
            )
        digest = sha256_bytes(content_bytes) if content_bytes is not None else content_sha256
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

    def add_trial(
        self,
        *,
        case_id: str,
        evaluation_id: str,
        trial_id: str,
        source_order: int,
        status: str,
        pairing_key: str | None = None,
        label: str | None = None,
        score: Any = None,
        reason: str | None = None,
        details: Any = None,
        error: Mapping[str, Any] | None = None,
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
        with tempfile.TemporaryDirectory(prefix="evalcanary-producer-validate-") as temp:
            candidate = Path(temp) / "candidate.jsonl"
            candidate.write_bytes(data)
            load_artifact(candidate, limits=limits)
        return data

    def write(self, path: Path, *, limits: Limits | None = None) -> Path:
        """Validate first, then atomically publish one canonical JSONL file."""

        data = self.canonical_bytes(limits=limits)
        target = _validate_target(path)
        target.parent.mkdir(parents=True, exist_ok=True)
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
            _validate_target(target)
            os.replace(temporary, target)
        except OSError as exc:
            raise InputValidationError(
                "Producer output could not be written atomically."
            ) from exc
        finally:
            if descriptor is not None:
                with suppress(OSError):
                    os.close(descriptor)
            with suppress(FileNotFoundError):
                temporary.unlink()
        return target


_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


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
            raise InputValidationError("Producer output topology changed during validation.")
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


__all__ = [
    "AssurancePacket",
    "ComponentValue",
    "Evaluation",
    "component_value",
    "sha256_bytes",
    "sha256_value",
]
