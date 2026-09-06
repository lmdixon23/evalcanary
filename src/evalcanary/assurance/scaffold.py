"""Inert evaluator-assurance authoring scaffold."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from ..errors import InputValidationError
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
    return f"""# EvalCanary evaluator-assurance scaffold

This inert scaffold records only the choices supplied to `evalcanary init`.
It is not an assurance input, contract, acceptance policy, or migration result.

- Judgment kind: `{judgment}`
- Explicit labels: {label_text}
- State: `INERT_REQUIRES_SEMANTIC_CHOICES`

## Required choices

{todo}

Evaluator and context fingerprints must be supplied explicitly, or computed by
calling `sha256_bytes`/`sha256_value` over exact local values. Do not derive
them from display names, filenames, paths, imports, object representations,
package metadata, the environment, or the clock.

Edit `producer_mapping.py`. Its guard intentionally prevents output until all
TODO choices are resolved. Then use `AssurancePacket.write`, which validates
through the normative runtime validator before atomically publishing JSONL.

Inspect the offline structural contracts with:

```console
evalcanary schema input-record
evalcanary schema contract
```

Validate the completed artifact without evaluating policy or writing reports:

```console
evalcanary migrate --preflight --input evaluator-assurance.jsonl
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
    return f'''"""Complete these explicit choices before producing an artifact."""

from evalcanary.assurance.producer import AssurancePacket, Evaluation

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
    score_spec = {score_todo}
    judgment_spec = {{
        "judgment_spec_id": "TODO_EXPLICIT_ID",
        "kind": JUDGMENT_KIND,
        "label_space": LABEL_SPACE,
        "score_spec": score_spec,
        "repeat_score_tolerance": None,
    }}
    # Construct explicit baseline/candidate Evaluation objects here. Their
    # fingerprint fields have no defaults and must not be inferred.
    evaluations: list[Evaluation] = []
    if len(evaluations) != 2:
        raise RuntimeError("TODO_REQUIRED: supply baseline and candidate identity")
    return AssurancePacket(
        artifact_id="TODO_EXPLICIT_ID",
        corpus_id="TODO_EXPLICIT_ID",
        identity_level="content_hashes",
        judgment_spec=judgment_spec,
        evaluations=evaluations,
        component_ownership={{
            "parser": PARSER_OWNER,
            "aggregation_policy": AGGREGATION_POLICY_OWNER,
        }},
        provenance={{}},
        allowed_context_differences=CONTEXT_DIFFERENCES,
    )
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
