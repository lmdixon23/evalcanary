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
    movable_components = "\n".join(
        f"- `{item}`" for item in sorted(MOVABLE_COMPONENTS)
    )
    return f"""# EvalCanary evaluator-assurance scaffold

This inert scaffold records only the choices supplied to `evalcanary init`.
It is not an assurance input, contract, acceptance policy, or migration result.

- Judgment kind: `{judgment}`
- Explicit labels: {label_text}
- State: `INERT_REQUIRES_SEMANTIC_CHOICES`

## Required choices

{todo}

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
calling `sha256_bytes`/`sha256_value` over exact local values. Do not derive
them from display names, filenames, paths, imports, object representations,
package metadata, the environment, or the clock.

Edit `producer_mapping.py`. It contains one compact baseline/candidate/case/
trial mapping with obvious synthetic placeholders and an optional group
extension point. Its guard intentionally prevents output until all TODO choices
and the bulk not-applicable affirmation are resolved. `AssurancePacket.write`
validates through the normative runtime validator before atomically publishing
JSONL.

Inspect the offline structural contracts with:

```console
evalcanary schema input-record
evalcanary schema contract
```

Validate the completed artifact without evaluating policy or writing reports:

```console
evalcanary migrate --preflight --input evaluator-assurance.jsonl
```

Generate the normal five-member report packet after preflight:

```console
evalcanary migrate --input evaluator-assurance.jsonl --out report
```

No contract template is emitted because this scaffold does not choose an
acceptance threshold, severity, or missing-evidence policy.
"""


def _mapping(judgment: str, labels: list[str]) -> str:
    labels_literal = repr(labels if labels else None)
    score_todo = (
        "None"
        if judgment == "categorical"
        else "TODO_SCORE_SPEC  # exact scale/domain/direction/status choices required"
    )
    example_label = "None" if judgment == "numeric" else "LABEL_SPACE[0]"
    example_score = "None" if judgment == "categorical" else 'Decimal("0.5")'
    score_guard = (
        ""
        if judgment == "categorical"
        else '\n    if TODO_SCORE_SPEC is None:\n'
        '        raise RuntimeError("TODO_REQUIRED: supply the exact score specification")'
    )
    return f'''"""Complete these explicit choices before producing an artifact."""

from decimal import Decimal
from pathlib import Path

from evalcanary.assurance import (
    AssurancePacket,
    complete_components,
    component_requirements,
    component_value,
    make_evaluation,
)
from evalcanary.assurance.producer import sha256_bytes

JUDGMENT_KIND = {judgment!r}
LABEL_SPACE = {labels_literal}
TODO_SCORE_SPEC = None

# Required semantic decisions. Keep these unresolved until a human supplies them.
PARSER_OWNER = None
AGGREGATION_POLICY_OWNER = None
STATUS_MAPPING = None
PAIRING_POLICY = None
CONTEXT_DIFFERENCES = None
ANCHOR_INTERPRETATION = None
CONFIRM_UNLISTED_NOT_APPLICABLE = False


def components_for(role: str, ownership: dict[str, str]):
    # These are synthetic placeholders, not inferred identities or presence.
    # Explicit missing/omitted/present/not_applicable declarations override
    # the bulk confirmation for the named component.
    return complete_components(
        ownership=ownership,
        evaluator_components={{
            "implementation": component_value(
                "present", identity=f"TODO_{{role}}_implementation"
            ),
            "model_provider": component_value("intentionally_omitted"),
            "rubric_prompt": component_value("missing"),
        }},
        context_components={{
            "runner_adapter": component_value(
                "present", identity="TODO_SHARED_RUNNER_ADAPTER"
            ),
        }},
        confirm_unlisted_not_applicable=CONFIRM_UNLISTED_NOT_APPLICABLE,
    )


def add_optional_groups(packet: AssurancePacket) -> AssurancePacket:
    # Add explicit critical, invariance, or anchor declarations here. This
    # extension point intentionally creates none.
    return packet


def build_packet() -> AssurancePacket:
    required = (
        PARSER_OWNER,
        AGGREGATION_POLICY_OWNER,
        STATUS_MAPPING,
        PAIRING_POLICY,
        CONTEXT_DIFFERENCES,
        ANCHOR_INTERPRETATION,
    )
    if any(value is None for value in required):
        raise RuntimeError("TODO_REQUIRED: resolve every listed semantic choice")
    if CONFIRM_UNLISTED_NOT_APPLICABLE is not True:
        raise RuntimeError(
            "TODO_REQUIRED: affirm every unlisted owned component is not applicable"
        ){score_guard}
    ownership = {{
        "parser": PARSER_OWNER,
        "aggregation_policy": AGGREGATION_POLICY_OWNER,
    }}
    # Public, deterministic machine surface for the exact required names.
    component_requirements(ownership)
    score_spec = {score_todo}
    judgment_spec = {{
        "judgment_spec_id": "TODO_EXPLICIT_JUDGMENT_SPEC_ID",
        "kind": JUDGMENT_KIND,
        "label_space": LABEL_SPACE,
        "score_spec": score_spec,
        "repeat_score_tolerance": None,
    }}
    baseline = make_evaluation(
        evaluation_id="TODO_BASELINE_EVALUATION_ID",
        role="baseline",
        evaluator_id="TODO_BASELINE_EVALUATOR_ID",
        evaluator_version="TODO_BASELINE_VERSION",
        evaluator_fingerprint_sha256=sha256_bytes(
            b"TODO_REPLACE_WITH_EXACT_BASELINE_FINGERPRINT_BYTES"
        ),
        context_id="TODO_BASELINE_CONTEXT_ID",
        context_fingerprint_sha256=sha256_bytes(
            b"TODO_REPLACE_WITH_EXACT_BASELINE_CONTEXT_BYTES"
        ),
        component_ownership=ownership,
        components=components_for("baseline", ownership),
        provenance={{}},
    )
    candidate = make_evaluation(
        evaluation_id="TODO_CANDIDATE_EVALUATION_ID",
        role="candidate",
        evaluator_id="TODO_CANDIDATE_EVALUATOR_ID",
        evaluator_version="TODO_CANDIDATE_VERSION",
        evaluator_fingerprint_sha256=sha256_bytes(
            b"TODO_REPLACE_WITH_EXACT_CANDIDATE_FINGERPRINT_BYTES"
        ),
        context_id="TODO_CANDIDATE_CONTEXT_ID",
        context_fingerprint_sha256=sha256_bytes(
            b"TODO_REPLACE_WITH_EXACT_CANDIDATE_CONTEXT_BYTES"
        ),
        component_ownership=ownership,
        components=components_for("candidate", ownership),
        provenance={{}},
    )
    packet = AssurancePacket(
        artifact_id="TODO_EXPLICIT_ARTIFACT_ID",
        corpus_id="TODO_EXPLICIT_CORPUS_ID",
        identity_level="content_hashes",
        judgment_spec=judgment_spec,
        evaluations=[baseline, candidate],
        component_ownership=ownership,
        provenance={{}},
        allowed_context_differences=CONTEXT_DIFFERENCES,
    )
    packet.add_case(
        "synthetic-case-1",
        content_bytes=b"TODO_REPLACE_WITH_EXACT_SYNTHETIC_CASE_BYTES",
    )
    # These rows are already normalized to ScoreWitness semantics. Apply the
    # explicit STATUS_MAPPING to source rows before constructing them.
    packet.add_trials(
        [
            {{
                "case_id": "synthetic-case-1",
                "evaluation_id": baseline.evaluation_id,
                "trial_id": "synthetic-baseline-trial-1",
                "source_order": 0,
                "pairing_key": "synthetic-pair-1",
                "status": "determinate",
                "label": {example_label},
                "score": {example_score},
            }},
            {{
                "case_id": "synthetic-case-1",
                "evaluation_id": candidate.evaluation_id,
                "trial_id": "synthetic-candidate-trial-1",
                "source_order": 0,
                "pairing_key": "synthetic-pair-1",
                "status": "determinate",
                "label": {example_label},
                "score": {example_score},
            }},
        ]
    )
    return add_optional_groups(packet)


if __name__ == "__main__":
    build_packet().write(Path("evaluator-assurance.jsonl"))
'''


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
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent)
    )
    completed = False
    try:
        (temporary / "README.md").write_text(
            _readme(judgment, checked_labels), encoding="utf-8", newline="\n"
        )
        (temporary / "producer_mapping.py").write_text(
            _mapping(judgment, checked_labels), encoding="utf-8", newline="\n"
        )
        (temporary / "scaffold.json").write_text(
            json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
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
