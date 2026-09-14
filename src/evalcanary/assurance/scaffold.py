"""Inert evaluator-assurance authoring scaffold."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from ..errors import InputValidationError
from .constants import (
    FIXED_CONTEXT_COMPONENTS,
    FIXED_EVALUATOR_COMPONENTS,
    MOVABLE_COMPONENTS,
)
from .producer import _validate_target

SCAFFOLD_VERSION = "evaluator-assurance-scaffold-v1"

_UNDECIDED = (
    "status mapping",
    "parser ownership",
    "aggregation-policy ownership",
    "trial pairing keys",
    "invariance relations",
    "allowed context differences",
    "human-anchor interpretation",
    "contract thresholds, severities, and missing-evidence policy",
)


def _validate_labels(judgment: str, labels: list[str]) -> list[str]:
    if judgment == "numeric":
        if labels:
            raise InputValidationError("Numeric scaffold does not accept labels.")
        return []
    if not 2 <= len(labels) <= 64:
        raise InputValidationError(
            "Categorical scaffold requires between 2 and 64 explicit labels."
        )
    if len(set(labels)) != len(labels):
        raise InputValidationError("Scaffold labels must be unique.")
    for label in labels:
        if not label or len(label) > 64 or len(label.encode("utf-8")) > 256:
            raise InputValidationError("A scaffold label is outside its safe bound.")
    return list(labels)


def _readme(judgment: str, labels: list[str]) -> str:
    label_text = ", ".join(f"`{item}`" for item in labels) if labels else "none"
    todo = "\n".join(f"- [ ] Choose {item}." for item in _UNDECIDED)
    evaluator_components = "\n".join(
        f"- `{item}`" for item in sorted(FIXED_EVALUATOR_COMPONENTS)
    )
    context_components = "\n".join(
        f"- `{item}`" for item in sorted(FIXED_CONTEXT_COMPONENTS)
    )
    movable_components = "\n".join(f"- `{item}`" for item in sorted(MOVABLE_COMPONENTS))
    return f"""# EvalCanary evaluator-assurance scaffold

This inert scaffold records only the choices supplied to `evalcanary init`.
It is not an assurance input, contract, acceptance policy, or migration result.

- Judgment kind: `{judgment}`
- Explicit labels: {label_text}
- State: `INERT_REQUIRES_SEMANTIC_CHOICES`

## SEMANTIC DECISIONS

{todo}

These decisions belong to the maintainer. The producer never determines
whether component identities should change between evaluator versions. It also
does not select status mappings, pairing, invariance, context exceptions,
anchor interpretation, or acceptance policy.

## FIXED EVALUATOR COMPONENTS

{evaluator_components}

## FIXED CONTEXT COMPONENTS

{context_components}

## MOVABLE COMPONENTS

{movable_components}

Every movable component must be assigned explicitly to `evaluator` or
`context`. In particular, `parser` and `aggregation_policy` each require
an ownership decision. `component_requirements(ownership)` returns the exact
complete evaluator/context names from the producer\'s authoritative vocabulary;
it performs no environment inspection and infers neither ownership nor
presence.

Evaluator and context fingerprints must be supplied explicitly, or computed by
calling `sha256_bytes`/`sha256_value` over exact local values. Their single
canonical public import is `from evalcanary.assurance import sha256_bytes,
sha256_value`. Do not derive fingerprints from display names, filenames, paths,
imports, object representations, package metadata, the environment, or the
clock.

## MECHANICAL REPRESENTATION

Edit `producer_mapping.py`. Every unresolved declaration is a typed marker,
including identities, ownership, component facts, context differences, cases,
local trial rows, groups, and anchors. Scaffold-specific sentinel text, bytes,
and the direct `sha256_bytes(token.encode("utf-8"))` and `sha256_value(token)`
fingerprint digests are also blocked. This check recognizes only registered
scaffold markers, not arbitrary strings or fingerprint provenance. Renaming
marker descriptions cannot resolve them. The guard checks mapping keys/values
and supported collections, including sequences used by the public producer.
It blocks output while any marker remains; the normative validator then checks the completed packet. Neither
check establishes that an author's substantive semantic choice is true or
correct.

Implement `STATUS_MAPPING(source)` so its exact `status`, `label`, `score`, and
`error` result controls each emitted trial. Implement `PAIRING_POLICY(source)`
so its exact string or explicit `None` controls the emitted pairing key. These
functions map only the local rows you supply in `TRIAL_SOURCE`; the scaffold
does not inspect or infer arbitrary external source semantics. Both default
implementations fail with `AUTHORING_INCOMPLETE`.

An empty semantic choice must be affirmative: replace the corresponding marker
with `[]`, `{{}}`, or `None` only where the field permits that exact value. For
example, `ALLOWED_CONTEXT_DIFFERENCES = []` explicitly asserts that no context
difference is allowed, and returning `None` from `PAIRING_POLICY` explicitly
asserts that the trial is unpaired. Omitting either public argument is rejected.
`INVARIANCE_GROUPS = []` selects no invariance relations; otherwise its exact
group declarations control output. `ANCHOR_SETS = []` and `ANCHORS = []` select
no human anchors; otherwise the supplied interpretation, aggregation, and
clustering declarations control output.

Case/group membership has one supported mechanism. Supply both collections on
the case declaration passed to `packet.add_case(...)` or `packet.add_cases(...)`:

```python
{{
    "case_id": "case-a",
    "critical_group_ids": ["release-blockers"],
    "invariance_group_ids": ["paraphrase-pair"],
}}
```

Declare the matching group records separately. There is no
`assign_case_groups` method and no later group-assignment phase.

The complete authoring path is:

1. Define the semantic choices above.
2. Create the explicit baseline and candidate evaluations.
3. Create `AssurancePacket`.
4. Add cases, trials, groups, and anchors.
5. Write the finalized input with `input_path = packet.write(...)`.
6. Author explicit keyword-only `Rule` values and a `Contract`.
7. Write the contract with
   `contract.write(contract_path, artifact=input_path)`.
8. Run `evalcanary migrate --preflight ...`.
9. Run `evalcanary migrate ...`.

`write_outputs(contract=...)` performs steps 5 and 7 after `build_packet()`;
the caller must supply the reviewed contract. The scaffold emits no rule or
contract and does not claim that any example contract is appropriate.

The keyword-only rule shape is:

```python
Rule(
    rule_id=...,
    severity=...,
    scope=...,
    scope_id=...,
    metric=...,
    parameters=...,
    operator=...,
    threshold=...,
    missing_evidence=...,
    rationale=...,
)
```

Every value above is a semantic choice; no acceptance-policy defaults are
provided. `AssurancePacket.write` validates through the normative runtime
validator before atomically publishing JSONL. `Contract.write` accepts either
that finalized path or an explicitly preloaded `AssuranceArtifact` and uses the
same normative artifact validation path.

Inspect the offline structural contracts with:

```console
evalcanary schema input-record
evalcanary schema contract
```

Validate the completed artifact without evaluating policy or writing reports:

```console
evalcanary migrate --preflight --input evaluator-assurance.jsonl \
  --contract evaluator-contract.json
```

Generate the normal five-member report packet after preflight:

```console
evalcanary migrate --input evaluator-assurance.jsonl \
  --contract evaluator-contract.json --out report
```

No contract template is emitted because this scaffold does not choose an
acceptance threshold, severity, or missing-evidence policy.
"""


def _mapping(judgment: str, labels: list[str]) -> str:
    labels_literal = repr(labels if labels else None)
    score_choice = (
        "None"
        if judgment == "categorical"
        else 'unresolved("exact score specification")'
    )
    tolerance_choice = (
        "None"
        if judgment == "categorical"
        else 'unresolved("repeat-score tolerance; use None to affirm no tolerance")'
    )
    template = '''"""Supply every explicit declaration before producing an artifact."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

from evalcanary.assurance import (
    AssurancePacket,
    Contract,
    complete_evaluation,
    component_requirements,
    component_value,
    sha256_bytes,
    sha256_value,
)


_SCAFFOLD_SENTINEL_PREFIX = "TODO_EVALCANARY_SCAFFOLD:"
_SCAFFOLD_SENTINEL_TEXTS: set[str] = set()
_SCAFFOLD_SENTINEL_BYTES: set[bytes] = set()
_SCAFFOLD_SENTINEL_DIGESTS: set[str] = set()


class _UnresolvedChoice:
    """Typed marker: editing its description cannot turn it into a decision."""

    def __init__(self, description: str) -> None:
        self.description = description
        self.token = _SCAFFOLD_SENTINEL_PREFIX + description
        _SCAFFOLD_SENTINEL_TEXTS.add(self.token)
        _SCAFFOLD_SENTINEL_BYTES.add(self.token.encode("utf-8"))
        _SCAFFOLD_SENTINEL_DIGESTS.add(sha256_bytes(self.token.encode("utf-8")))
        _SCAFFOLD_SENTINEL_DIGESTS.add(sha256_value(self.token))


def unresolved(description: str) -> _UnresolvedChoice:
    return _UnresolvedChoice(description)


def _unresolved_paths(value: Any, path: str) -> list[str]:
    if isinstance(value, _UnresolvedChoice):
        return [path]
    if isinstance(value, str):
        return [path] if value in (
            _SCAFFOLD_SENTINEL_TEXTS | _SCAFFOLD_SENTINEL_DIGESTS
        ) else []
    if isinstance(value, bytes):
        return [path] if value in _SCAFFOLD_SENTINEL_BYTES else []
    if isinstance(value, Mapping):
        missing = []
        for key in sorted(value, key=str):
            missing.extend(_unresolved_paths(key, f"{path}[key]"))
            missing.extend(_unresolved_paths(value[key], f"{path}.{key}"))
        return missing
    if isinstance(value, Collection):
        return [
            nested
            for index, item in enumerate(value)
            for nested in _unresolved_paths(item, f"{path}[{index}]")
        ]
    return []


def require_structural_completion(**choices: Any) -> None:
    missing = _unresolved_paths(choices, "authoring")
    if missing:
        raise RuntimeError(
            "AUTHORING_INCOMPLETE: explicit declarations remain at " + ", ".join(missing)
        )


JUDGMENT_KIND = __JUDGMENT_KIND__
LABEL_SPACE = __LABEL_SPACE__
SCORE_SPEC = __SCORE_SPEC__
REPEAT_SCORE_TOLERANCE = __REPEAT_SCORE_TOLERANCE__

# Replace each marker with reviewed data. Empty lists/dicts and None are accepted
# when they are supplied deliberately and are structurally valid for that field.
COMPONENT_OWNERSHIP = unresolved("parser and aggregation-policy owners")
ALLOWED_CONTEXT_DIFFERENCES = unresolved("exact differences; use [] to affirm none")
PACKET = {
    "artifact_id": unresolved("artifact identity"),
    "corpus_id": unresolved("corpus identity"),
    "identity_level": unresolved("case_ids or content_hashes"),
    "judgment_spec_id": unresolved("judgment-spec identity"),
    "provenance": unresolved("packet provenance; use {} to affirm none"),
}
EVALUATIONS = {
    role: {
        "evaluation_id": unresolved(f"{role} evaluation identity"),
        "evaluator_id": unresolved(f"{role} evaluator identity"),
        "evaluator_version": unresolved(f"{role} evaluator version"),
        "evaluator_fingerprint_sha256": unresolved(f"{role} evaluator fingerprint"),
        "context_id": unresolved(f"{role} context identity"),
        "context_fingerprint_sha256": unresolved(f"{role} context fingerprint"),
        "component_values": unresolved(f"{role} component facts keyed by name"),
        "confirm_unlisted_not_applicable": unresolved(
            f"{role} explicit bulk not-applicable affirmation"
        ),
        "provenance": unresolved(f"{role} provenance; use {{}} to affirm none"),
    }
    for role in ("baseline", "candidate")
}
CASES = unresolved(
    "case declarations with explicit critical_group_ids and invariance_group_ids"
)
TRIAL_SOURCE = unresolved(
    "local trial rows whose status/error and pairing are mapped explicitly below"
)
CRITICAL_GROUPS = unresolved("critical-group declarations; use [] to affirm none")
INVARIANCE_GROUPS = unresolved("invariance declarations; use [] to affirm none")
ANCHOR_SETS = unresolved("anchor-set declarations; use [] to affirm none")
ANCHORS = unresolved("anchor declarations; use [] to affirm none")


def STATUS_MAPPING(source: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return exactly status, label, score, and error for one local source row."""

    del source
    raise RuntimeError("AUTHORING_INCOMPLETE: implement STATUS_MAPPING")


def PAIRING_POLICY(source: Mapping[str, Any]) -> str | None:
    """Return the reviewed pairing key, including explicit None when unpaired."""

    del source
    raise RuntimeError("AUTHORING_INCOMPLETE: implement PAIRING_POLICY")


def _evaluation(role: str, facts: Mapping[str, Any], ownership: Mapping[str, str]):
    return complete_evaluation(
        evaluation_id=facts["evaluation_id"],
        role=role,
        evaluator_id=facts["evaluator_id"],
        evaluator_version=facts["evaluator_version"],
        evaluator_fingerprint_sha256=facts["evaluator_fingerprint_sha256"],
        context_id=facts["context_id"],
        context_fingerprint_sha256=facts["context_fingerprint_sha256"],
        component_ownership=ownership,
        component_values=facts["component_values"],
        confirm_unlisted_not_applicable=facts["confirm_unlisted_not_applicable"],
        provenance=facts["provenance"],
    )


def build_packet() -> AssurancePacket:
    declarations = {
        "judgment_kind": JUDGMENT_KIND,
        "label_space": LABEL_SPACE,
        "score_spec": SCORE_SPEC,
        "repeat_score_tolerance": REPEAT_SCORE_TOLERANCE,
        "component_ownership": COMPONENT_OWNERSHIP,
        "allowed_context_differences": ALLOWED_CONTEXT_DIFFERENCES,
        "packet": PACKET,
        "evaluations": EVALUATIONS,
        "cases": CASES,
        "trial_source": TRIAL_SOURCE,
        "critical_groups": CRITICAL_GROUPS,
        "invariance_groups": INVARIANCE_GROUPS,
        "anchor_sets": ANCHOR_SETS,
        "anchors": ANCHORS,
    }
    require_structural_completion(**declarations)
    if not callable(STATUS_MAPPING) or not callable(PAIRING_POLICY):
        raise RuntimeError(
            "AUTHORING_INCOMPLETE: STATUS_MAPPING and PAIRING_POLICY must be callable"
        )
    ownership = dict(COMPONENT_OWNERSHIP)
    component_requirements(ownership)
    evaluations = [
        _evaluation(role, EVALUATIONS[role], ownership)
        for role in ("baseline", "candidate")
    ]
    packet = AssurancePacket(
        artifact_id=PACKET["artifact_id"],
        corpus_id=PACKET["corpus_id"],
        identity_level=PACKET["identity_level"],
        judgment_spec={
            "judgment_spec_id": PACKET["judgment_spec_id"],
            "kind": JUDGMENT_KIND,
            "label_space": LABEL_SPACE,
            "score_spec": SCORE_SPEC,
            "repeat_score_tolerance": REPEAT_SCORE_TOLERANCE,
        },
        evaluations=evaluations,
        component_ownership=ownership,
        provenance=PACKET["provenance"],
        allowed_context_differences=ALLOWED_CONTEXT_DIFFERENCES,
    )
    packet.add_cases(CASES)
    evaluation_ids = packet.evaluation_ids_by_role
    normalized_trials = []
    for source in TRIAL_SOURCE:
        status_fields = dict(STATUS_MAPPING(source))
        if set(status_fields) != {"status", "label", "score", "error"}:
            raise RuntimeError(
                "AUTHORING_INCOMPLETE: STATUS_MAPPING must return exactly "
                "status, label, score, and error"
            )
        trial = {
            key: source[key]
            for key in ("case_id", "role", "trial_id", "source_order")
        }
        trial.update(status_fields)
        trial["pairing_key"] = PAIRING_POLICY(source)
        require_structural_completion(normalized_trial=trial)
        role = trial.pop("role")
        trial["evaluation_id"] = evaluation_ids[role]
        normalized_trials.append(trial)
    packet.add_trials(normalized_trials)
    for declaration in CRITICAL_GROUPS:
        packet.add_critical_group(**dict(declaration))
    for declaration in INVARIANCE_GROUPS:
        packet.add_invariance_group(**dict(declaration))
    for declaration in ANCHOR_SETS:
        packet.add_anchor_set(**dict(declaration))
    packet.add_anchors(ANCHORS)
    return packet


def write_outputs(
    *,
    contract: Contract,
    input_path: Path = Path("evaluator-assurance.jsonl"),
    contract_path: Path = Path("evaluator-contract.json"),
) -> tuple[Path, Path]:
    """Publish input and the caller-authored contract through the golden path."""

    finalized_input = build_packet().write(input_path)
    finalized_contract = contract.write(contract_path, artifact=finalized_input)
    return finalized_input, finalized_contract


if __name__ == "__main__":
    build_packet().write(Path("evaluator-assurance.jsonl"))
'''
    return (
        template.replace("__JUDGMENT_KIND__", repr(judgment))
        .replace("__LABEL_SPACE__", labels_literal)
        .replace("__SCORE_SPEC__", score_choice)
        .replace("__REPEAT_SCORE_TOLERANCE__", tolerance_choice)
    )


def create_scaffold(*, judgment: str, labels: list[str], output: Path) -> Path:
    """Create one bounded, deterministic, deliberately non-executable scaffold."""

    if judgment not in {"categorical", "numeric", "categorical_and_numeric"}:
        raise InputValidationError("Unknown scaffold judgment kind.")
    checked_labels = _validate_labels(judgment, labels)
    target = Path(os.path.abspath(os.fspath(output)))
    if target.exists() or target.is_symlink():
        raise InputValidationError("Scaffold output must not already exist.")
    target = _validate_target(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    _validate_target(target)
    metadata = {
        "scaffold_version": SCAFFOLD_VERSION,
        "state": "INERT_REQUIRES_SEMANTIC_CHOICES",
        "judgment": {"kind": judgment, "labels": checked_labels},
        "component_inventory": {
            "fixed_evaluator_components": sorted(FIXED_EVALUATOR_COMPONENTS),
            "fixed_context_components": sorted(FIXED_CONTEXT_COMPONENTS),
            "movable_components": sorted(MOVABLE_COMPONENTS),
            "movable_owner_values": ["context", "evaluator"],
            "ownership_required": True,
        },
        "producer_helpers": [
            "component_requirements",
            "complete_components",
            "complete_evaluation",
            "make_evaluation",
            "AssurancePacket.add_cases",
            "AssurancePacket.add_trials",
            "AssurancePacket.add_anchors",
            "Rule",
            "Contract",
        ],
        "schema_selectors": ["contract", "input-record"],
        "contract_emitted": False,
        "undecided": list(_UNDECIDED),
    }
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    completed = False
    try:
        (temporary / "README.md").write_text(
            _readme(judgment, checked_labels), encoding="utf-8", newline="\n"
        )
        (temporary / "producer_mapping.py").write_text(
            _mapping(judgment, checked_labels), encoding="utf-8", newline="\n"
        )
        (temporary / "scaffold.json").write_text(
            json.dumps(
                metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        _validate_target(target)
        os.replace(temporary, target)
        completed = True
    except OSError as exc:
        raise InputValidationError("Scaffold could not be created atomically.") from exc
    finally:
        if not completed:
            shutil.rmtree(temporary, ignore_errors=True)
    return target


__all__ = ["SCAFFOLD_VERSION", "create_scaffold"]
