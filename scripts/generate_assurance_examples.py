#!/usr/bin/env python3
"""Generate deterministic offline assurance examples through the public producer."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evalcanary.assurance.producer import (  # noqa: E402
    AssurancePacket,
    Evaluation,
    component_value,
    sha256_bytes,
)

OUTPUT = ROOT / "src" / "evalcanary" / "examples" / "assurance"


def _present(identity: str) -> dict[str, object]:
    return component_value("present", identity=identity)


def example_evaluation(
    role: str,
    *,
    runtime_identity: str = "python-example",
    context_identity: str = "shared-context",
) -> Evaluation:
    return Evaluation(
        evaluation_id=f"eval-{role}",
        role=role,
        evaluator_id=f"evaluator-{role}",
        evaluator_version="example-v1",
        evaluator_fingerprint_sha256=sha256_bytes(
            f"exact-example-evaluator-{role}".encode()
        ),
        context_id=context_identity,
        context_fingerprint_sha256=sha256_bytes(
            f"exact-example-context-{runtime_identity}".encode()
        ),
        evaluator_components={
            "implementation": _present(f"example-{role}-implementation"),
            "aggregation_policy": _present("explicit-example-aggregation"),
        },
        evaluator_not_applicable={"rubric_prompt", "model_provider"},
        context_components={
            "runtime": _present(runtime_identity),
            "parser": _present("strict-jsonl-v1"),
        },
        context_not_applicable={
            "runner_adapter",
            "harness_configuration",
            "preprocessing",
            "dependency_lock",
            "container_image",
            "sampling_settings",
            "response_order",
            "locale_time",
            "resource_policy",
            "task_benchmark",
        },
        provenance={},
    )


def _packet(
    name: str,
    judgment_spec: dict[str, object],
    *,
    context_differences: list[dict[str, object]],
    baseline: Evaluation | None = None,
    candidate: Evaluation | None = None,
) -> AssurancePacket:
    return AssurancePacket(
        artifact_id=f"example-{name}",
        corpus_id=f"example-{name}-corpus",
        identity_level="content_hashes",
        judgment_spec=judgment_spec,
        evaluations=(
            baseline or example_evaluation("baseline"),
            candidate or example_evaluation("candidate"),
        ),
        component_ownership={"parser": "context", "aggregation_policy": "evaluator"},
        provenance={},
        allowed_context_differences=context_differences,
    )


def categorical_packet() -> AssurancePacket:
    packet = _packet(
        "categorical",
        {
            "judgment_spec_id": "categorical-v1",
            "kind": "categorical",
            "label_space": ["pass", "fail"],
            "score_spec": None,
            "repeat_score_tolerance": None,
        },
        context_differences=[],
    )
    packet.add_critical_group(
        "critical-example",
        title="Explicit critical example",
        declaration_source="offline-example",
        rationale="Demonstrates a declared critical membership without inferred polarity.",
    )
    packet.add_invariance_group(
        "swap-example",
        member_case_ids=["swap-a", "swap-b"],
        transformation_id="swap-response-order",
        transformation_version="1",
        expected_relation="swapped_preference",
        relation_parameters={"first_label": "pass", "second_label": "fail"},
        severity="review",
        declaration_source="offline-example",
        rationale="The user explicitly declares the swapped-preference relation.",
    )
    case_specs = {
        "abstention": ({}, "abstain", None),
        "error": ({}, "error", None),
        "indeterminate": ({}, "indeterminate", None),
        "repeat": ({}, "determinate", "pass"),
        "swap-a": ({"critical-example"}, "determinate", "pass"),
        "swap-b": (set(), "determinate", "fail"),
    }
    for case_id, (critical, status, label) in case_specs.items():
        packet.add_case(
            case_id,
            content_bytes=f"exact-example-content:{case_id}".encode(),
            critical_group_ids=critical,
            invariance_group_ids={"swap-example"}
            if case_id.startswith("swap-")
            else (),
        )
        repeat_count = 2 if case_id == "repeat" else 1
        for role in ("baseline", "candidate"):
            for order in range(repeat_count):
                trial_label = label
                if case_id == "repeat" and role == "candidate" and order == 1:
                    trial_label = "fail"
                error = (
                    {"error_class": "ExampleError", "message": "bounded example"}
                    if status == "error"
                    else None
                )
                packet.add_trial(
                    case_id=case_id,
                    evaluation_id=f"eval-{role}",
                    trial_id=f"{case_id}-{role}-{order}",
                    source_order=order,
                    pairing_key=f"pair-{order}",
                    status=status,
                    label=trial_label,
                    score=None,
                    error=error,
                )
    packet.add_anchor_set(
        "anchors-example",
        label_space=["pass", "fail"],
        protocol_id="explicit-protocol",
        protocol_version="1",
        aggregation_method="adjudicated",
        clustering_unit="case",
        source_revision="offline-v1",
        source_sha256=sha256_bytes(b"exact-offline-anchor-source"),
        license="CC0-1.0",
    )
    for suffix, label in (("a", "pass"), ("b", "fail")):
        packet.add_anchor(
            f"raw-{suffix}",
            anchor_set_id="anchors-example",
            case_id="swap-a",
            cluster_id="swap-a-cluster",
            annotation_id=f"annotation-{suffix}",
            annotator_id=f"synthetic-annotator-{suffix}",
            kind="raw_annotation",
            status="determinate",
            label=label,
        )
    packet.add_anchor(
        "aggregate-a",
        anchor_set_id="anchors-example",
        case_id="swap-a",
        cluster_id="swap-a-cluster",
        annotation_id="aggregate-annotation",
        annotator_id=None,
        kind="aggregate",
        status="determinate",
        label="pass",
        aggregation_inputs={"raw-a", "raw-b"},
        adjudication_rationale="Synthetic example adjudication.",
    )
    return packet


def numeric_packet() -> AssurancePacket:
    packet = _packet(
        "numeric",
        {
            "judgment_spec_id": "numeric-v1",
            "kind": "numeric",
            "label_space": None,
            "score_spec": {
                "scale_id": "zero-to-ten",
                "domain_min": Decimal("0"),
                "domain_max": Decimal("10"),
                "direction": "higher_is_better",
                "comparison": "delta",
                "valid_statuses": ["determinate"],
                "threshold_relationship": None,
            },
            "repeat_score_tolerance": Decimal("0.25"),
        },
        context_differences=[],
    )
    packet.add_invariance_group(
        "tolerance-example",
        member_case_ids=["numeric-a", "numeric-b"],
        transformation_id="format-preserving-change",
        transformation_version="1",
        expected_relation="same_score_within_tolerance",
        relation_parameters={"absolute_tolerance": Decimal("0.5")},
        severity="review",
        declaration_source="offline-example",
        rationale="The user explicitly supplies the absolute tolerance.",
    )
    for case_id, score in (
        ("numeric-a", Decimal("7.5")),
        ("numeric-b", Decimal("7.75")),
    ):
        packet.add_case(
            case_id,
            content_bytes=f"exact-example-content:{case_id}".encode(),
            critical_group_ids=(),
            invariance_group_ids={"tolerance-example"},
        )
        for role in ("baseline", "candidate"):
            packet.add_trial(
                case_id=case_id,
                evaluation_id=f"eval-{role}",
                trial_id=f"{case_id}-{role}",
                source_order=0,
                pairing_key="pair-0",
                status="determinate",
                label=None,
                score=score,
                error=None,
            )
    return packet


def categorical_numeric_packet() -> AssurancePacket:
    before = _present("python-example-before")
    after = _present("python-example-after")
    packet = _packet(
        "categorical-numeric",
        {
            "judgment_spec_id": "categorical-numeric-v1",
            "kind": "categorical_and_numeric",
            "label_space": ["pass", "fail"],
            "score_spec": {
                "scale_id": "zero-to-one",
                "domain_min": Decimal("0"),
                "domain_max": Decimal("1"),
                "direction": "higher_is_better",
                "comparison": "delta",
                "valid_statuses": ["determinate"],
                "threshold_relationship": {
                    "operator": "gte",
                    "threshold": Decimal("0.5"),
                    "below_label": "fail",
                    "above_label": "pass",
                },
            },
            "repeat_score_tolerance": Decimal("0.05"),
        },
        baseline=example_evaluation(
            "baseline",
            runtime_identity="python-example-before",
            context_identity="context-before",
        ),
        candidate=example_evaluation(
            "candidate",
            runtime_identity="python-example-after",
            context_identity="context-after",
        ),
        context_differences=[
            {
                "component": "runtime",
                "expected_baseline_component_value": before,
                "expected_candidate_component_value": after,
                "rationale": "Explicitly reviewed runtime-only example difference.",
                "reviewer_id": "example-reviewer",
                "disposition": "not_isolated_review_required",
            }
        ],
    )
    packet.add_case(
        "combined",
        content_bytes=b"exact-example-content:combined",
        critical_group_ids=(),
        invariance_group_ids=(),
    )
    for role, score in (("baseline", Decimal("0.6")), ("candidate", Decimal("0.8"))):
        packet.add_trial(
            case_id="combined",
            evaluation_id=f"eval-{role}",
            trial_id=f"combined-{role}",
            source_order=0,
            pairing_key="pair-0",
            status="determinate",
            label="pass",
            score=score,
            error=None,
        )
    return packet


def example_packets() -> dict[str, AssurancePacket]:
    return {
        "categorical.jsonl": categorical_packet(),
        "categorical-numeric.jsonl": categorical_numeric_packet(),
        "numeric.jsonl": numeric_packet(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for filename, packet in example_packets().items():
        path = OUTPUT / filename
        expected = packet.canonical_bytes()
        if args.check:
            if not path.is_file() or path.read_bytes() != expected:
                raise RuntimeError(f"Assurance example drift: {filename}")
        else:
            packet.write(path)
        print(path.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
