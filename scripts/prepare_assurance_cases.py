#!/usr/bin/env python3
"""Verify and prepare the locked, inert evaluator-assurance cases.

This development-only utility reads data and source bytes.  It never imports or
executes fetched source, fixture text, shell commands, patches, or model output.
Case C's tracked fixtures are original synthetic data; full source validation is
performed separately by ``validate_mt_bench_case.py`` under an ignored path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from evalcanary.assurance.constants import (
    FIXED_CONTEXT_COMPONENTS,
    FIXED_EVALUATOR_COMPONENTS,
)
from evalcanary.assurance.engine import build_report, exit_code_for_report
from evalcanary.assurance.numeric import canonical_json_text, canonical_sha256
from evalcanary.assurance.renderers import write_report_bundle
from evalcanary.assurance.schema import (
    Limits,
    compute_manifest_sha256,
    load_artifact,
    load_contract,
)

_START = ">>>>> Start Test Output"
_END = ">>>>> End Test Output"
_EXIT_CODE = re.compile(r">>>>> Test Exit Code:\s*(-?\d+)")
_RESULT = re.compile(r"^(PASSED|FAILED|ERROR)\s+([^\s]+)$", re.MULTILINE)
_CASE_C_EXTENSION = "org.evalcanary.case-c"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_case_lock(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Case lock must be one JSON object.")
    return value


def verify_source_files(source_root: Path, case_lock: dict[str, Any]) -> list[str]:
    verified: list[str] = []
    for relative, expected in sorted(case_lock["source_files"].items()):
        path = source_root / relative
        if not path.is_file():
            raise ValueError(f"Pinned source file is missing: {relative}")
        observed = _sha256(path.read_bytes())
        if observed != expected:
            raise ValueError(f"Pinned source hash mismatch: {relative}")
        verified.append(relative)
    return verified


def verify_source_semantics(source_root: Path, case_name: str) -> None:
    """Bind the tiny inert emulators to signatures in already hash-verified source."""

    required: tuple[tuple[str, str], ...]
    if case_name == "case_a":
        baseline = (source_root / "case-a/baseline/scorers.py").read_text(
            encoding="utf-8"
        )
        candidate = (source_root / "case-a/candidate/scorers.py").read_text(
            encoding="utf-8"
        )
        required = (
            (baseline, 'pass_to_pass_results = {k: "FAILED"'),
            (baseline, 'fail_to_pass_results = {k: "FAILED"'),
            (baseline, '"PASSED" == v'),
            (candidate, "if START_TEST_OUTPUT not in test_output:"),
            (candidate, "if END_TEST_OUTPUT not in test_output:"),
            (candidate, 'value = 1.0 if instance_report["resolved"] else 0.0'),
        )
    elif case_name == "case_b":
        grading = (source_root / "case-b/candidate/grading.py").read_text(
            encoding="utf-8"
        )
        constants = (source_root / "case-b/candidate/constants.py").read_text(
            encoding="utf-8"
        )
        utils = (source_root / "case-b/candidate/utils.py").read_text(encoding="utf-8")
        test = (
            source_root / "case-b/candidate/test_grading_spoofed_output.py"
        ).read_text(encoding="utf-8")
        required = (
            (grading, "exit_code not in (None, 0)"),
            (grading, "TEST_EXIT_CODE_RE"),
            (constants, 'TEST_EXIT_CODE = ">>>>> Test Exit Code"'),
            (utils, "def record_test_exit_code"),
            (test, "spoof"),
        )
    else:
        raise ValueError(f"No inert source semantics are defined for {case_name}.")
    if any(signature not in text for text, signature in required):
        raise ValueError(f"Pinned source semantic signature mismatch: {case_name}")


def judge_case_a(text: str, role: str) -> tuple[str, str | None]:
    if role == "candidate" and (_START not in text or _END not in text):
        return "error", None
    parsed = {test_id: status for status, test_id in _RESULT.findall(text)}
    passed = parsed.get("test_bar") == "PASSED" and parsed.get("test_foo") == "PASSED"
    return "determinate", "pass" if passed else "fail"


def judge_case_b(text: str, role: str) -> tuple[str, str]:
    start = text.find(_START)
    end = text.find(_END, start + len(_START))
    bounded = text[start + len(_START) : end] if start >= 0 and end >= 0 else ""
    parsed = {test_id: status for status, test_id in _RESULT.findall(bounded)}
    if role == "candidate":
        match = _EXIT_CODE.search(text)
        exit_code = int(match.group(1)) if match else None
        if (
            exit_code not in (None, 0)
            and parsed
            and not any(status in {"FAILED", "ERROR"} for status in parsed.values())
        ):
            parsed = {}
    return "determinate", "pass" if parsed.get("test_a") == "PASSED" else "fail"


def verify_fixture_vectors(case_name: str, case_lock: dict[str, Any]) -> None:
    judge = judge_case_a if case_name == "case_a" else judge_case_b
    for fixture in case_lock["fixtures"]:
        data = fixture["text"].encode("utf-8")
        if len(data) != fixture["bytes"] or _sha256(data) != fixture["sha256"]:
            raise ValueError(f"Fixture byte identity mismatch: {fixture['case_id']}")
        for role in ("baseline", "candidate"):
            if list(judge(fixture["text"], role)) != fixture[role]:
                raise ValueError(
                    f"Fixture expected judgment mismatch: {fixture['case_id']}:{role}"
                )


def normalize_case_c_winner(winner: str, game: int) -> tuple[str, str | None]:
    """Map a model-relative raw winner to the displayed-order label space."""

    if game not in {1, 2}:
        raise ValueError("Case C game must be 1 or 2.")
    if winner == "error":
        return "error", None
    if winner == "tie":
        return "determinate", "tie"
    if winner not in {"model_1", "model_2"}:
        raise ValueError(f"Unsupported Case C source winner: {winner}")
    first_model_winner = "model_1" if game == 1 else "model_2"
    return "determinate", "a" if winner == first_model_winner else "b"


def normalize_case_c_human_winner(winner: str) -> str:
    """Map a human row's actual displayed order into the common label space."""

    mapping = {"model_a": "a", "model_b": "b", "tie": "tie"}
    if winner not in mapping:
        raise ValueError(f"Unsupported Case C human winner: {winner}")
    return mapping[winner]


def _opaque_id(prefix: str, material: dict[str, Any]) -> str:
    return f"{prefix}-{canonical_sha256(material)[:24]}"


def _case_c_identity(
    case_lock: dict[str, Any], row: dict[str, Any], game: int
) -> dict[str, Any]:
    first = row["model_1"] if game == 1 else row["model_2"]
    second = row["model_2"] if game == 1 else row["model_1"]
    return {
        "raw_revision": case_lock["raw_source"]["revision"],
        "question_id": row["question_id"],
        "turn": row["turn"],
        "displayed_first_model": first,
        "displayed_second_model": second,
    }


def case_c_group_key(row: dict[str, Any]) -> tuple[int, int, tuple[str, str]]:
    models = sorted((str(row["model_1"]), str(row["model_2"])))
    return (
        int(row["question_id"]),
        int(row["turn"]),
        (models[0], models[1]),
    )


def case_c_group_id(case_lock: dict[str, Any], row: dict[str, Any]) -> str:
    models = sorted((str(row["model_1"]), str(row["model_2"])))
    material = {
        "raw_revision": case_lock["raw_source"]["revision"],
        "question_id": row["question_id"],
        "turn": row["turn"],
        "unordered_models": models,
    }
    return _opaque_id("case-c-group", material)


def case_c_case_id(case_lock: dict[str, Any], row: dict[str, Any], game: int) -> str:
    return _opaque_id("case-c-case", _case_c_identity(case_lock, row, game))


def _case_c_evaluation(case_lock: dict[str, Any], role: str) -> dict[str, Any]:
    evaluator = {name: _component() for name in FIXED_EVALUATOR_COMPONENTS}
    context = {name: _component() for name in FIXED_CONTEXT_COMPONENTS}
    policy = (
        "single-order-evidence-policy"
        if role == "baseline"
        else "dual-order-evidence-policy"
    )
    evaluator["implementation"] = _component("frozen-source-evidence-policy-v1")
    evaluator["aggregation_policy"] = _component(policy)
    context["parser"] = _component("pinned-fastchat-jsonl-metadata-parser-v1")
    context["runner_adapter"] = _component("offline-frozen-artifact-reader")
    context["harness_configuration"] = _component("case-c-revised-lock")
    context["runtime"] = _component("python-stdlib-offline")
    context["dependency_lock"] = _component("pinned-pyarrow-fixture-decoder")
    context["response_order"] = _component("raw-game-1-and-swapped-game-2")
    context["resource_policy"] = _component("evaluator-assurance-default-limits")
    context["task_benchmark"] = _component("mt-bench-frozen-pair-evidence")
    return {
        "evaluation_id": f"case-c-{role}",
        "role": role,
        "evaluator_id": f"case-c-{role}-evidence-policy",
        "evaluator_version": "1",
        "evaluator_fingerprint_sha256": canonical_sha256(evaluator),
        "evaluator_components": evaluator,
        "context_id": "case-c-shared-frozen-context",
        "context_fingerprint_sha256": canonical_sha256(context),
        "context_components": context,
        "provenance": _provenance(
            corpus_source=_component(case_lock["raw_source"]["repository"]),
            corpus_revision=_component(case_lock["raw_source"]["revision"]),
            corpus_hash=_component(sha256=case_lock["raw_source"]["sha256"]),
            corpus_license=_component(case_lock["raw_source"]["declared_license"]),
            aggregation_policy=_component(policy),
            source_url=_component(case_lock["raw_source"]["url"]),
        ),
    }


def _case_c_trial(
    case_lock: dict[str, Any],
    row: dict[str, Any],
    game: int,
    role: str,
) -> dict[str, Any]:
    raw_winner = str(row[f"g{game}_winner"])
    source_status, source_label = normalize_case_c_winner(raw_winner, game)
    excluded = role == "baseline" and game == 2
    status = "abstain" if excluded else source_status
    label = None if excluded else source_label
    first = str(row["model_1"] if game == 1 else row["model_2"])
    second = str(row["model_2"] if game == 1 else row["model_1"])
    policy = (
        "single_order_policy_exclusion"
        if excluded
        else "single_order_policy_selected"
        if role == "baseline"
        else "dual_order_policy_inclusion"
    )
    case_id = case_c_case_id(case_lock, row, game)
    return {
        "record_type": "trial",
        "case_id": case_id,
        "evaluation_id": f"case-c-{role}",
        "trial_id": f"{case_id}-{role}",
        "source_order": 0,
        "pairing_key": "frozen-source-evidence",
        "status": status,
        "label": label,
        "score": None,
        "reason": None,
        "details": None,
        "error": {"error_class": "SourceJudgeError"} if status == "error" else None,
        "provenance": _provenance(
            original_artifact_hash=_component(sha256=case_lock["raw_source"]["sha256"]),
            source_row=_component(f"raw-row-{int(row['source_position'])}-game-{game}"),
            response_order=_component(f"{first}:{second}"),
            source_judgment=_component(raw_winner),
            evidence_policy=_component(policy),
        ),
        "extensions": {
            _CASE_C_EXTENSION: {
                "source_position": row["source_position"],
                "game": game,
                "source_model_order": [row["model_1"], row["model_2"]],
                "display_model_order": [first, second],
                "source_winner": raw_winner,
            }
        },
    }


def build_case_c_artifact(
    case_lock: dict[str, Any],
    selected_rows: list[dict[str, Any]],
    human_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a source-independent Case C packet from already validated metadata."""

    selected = sorted(selected_rows, key=lambda row: int(row["source_position"]))
    header: dict[str, Any] = {
        "record_type": "header",
        "schema_version": "evaluator-assurance-input-v1",
        "artifact_id": "case-c-frozen-policy-migration",
        "corpus": {
            "corpus_id": "case-c-frozen-dual-order-corpus",
            "manifest_sha256": "0" * 64,
            "case_count": len(selected) * 2,
            "identity_level": "full_artifact",
            "manifest_algorithm": "evaluator-assurance-manifest-v1",
        },
        "judgment_spec": {
            "judgment_spec_id": "case-c-displayed-preference-v1",
            "kind": "categorical",
            "label_space": ["a", "b", "tie"],
            "score_spec": None,
            "repeat_score_tolerance": None,
        },
        "evaluations": [
            _case_c_evaluation(case_lock, "baseline"),
            _case_c_evaluation(case_lock, "candidate"),
        ],
        "component_ownership": {
            "parser": "context",
            "aggregation_policy": "evaluator",
        },
        "allowed_context_differences": [],
        "provenance": _provenance(
            corpus_source=_component(case_lock["raw_source"]["repository"]),
            corpus_revision=_component(case_lock["raw_source"]["revision"]),
            corpus_hash=_component(sha256=case_lock["raw_source"]["sha256"]),
            corpus_license=_component(case_lock["raw_source"]["declared_license"]),
            original_artifact_hash=_component(sha256=case_lock["raw_source"]["sha256"]),
            source_url=_component(case_lock["raw_source"]["url"]),
        ),
        "extensions": {},
    }
    invariance: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    trials: list[dict[str, Any]] = []
    selected_by_key: dict[tuple[int, int, tuple[str, str]], dict[str, Any]] = {}
    case_ids_by_key_game: dict[tuple[tuple[int, int, tuple[str, str]], int], str] = {}
    for group_position, row in enumerate(selected):
        key = case_c_group_key(row)
        if key in selected_by_key:
            raise ValueError("Case C selected rows contain a duplicate group key.")
        selected_by_key[key] = row
        group_id = case_c_group_id(case_lock, row)
        member_ids = [case_c_case_id(case_lock, row, game) for game in (1, 2)]
        invariance.append(
            {
                "record_type": "invariance_group",
                "group_id": group_id,
                "member_case_ids": member_ids,
                "transformation_id": "response-order-swap",
                "transformation_version": "1",
                "expected_relation": "swapped_preference",
                "relation_parameters": {
                    "first_label": "a",
                    "second_label": "b",
                    "tie_label": "tie",
                },
                "severity": "review",
                "declaration_source": "case-c-revised-lock",
                "rationale": "Preserve model preference when display positions swap.",
                "extensions": {},
            }
        )
        for game, case_id in zip((1, 2), member_ids, strict=True):
            identity = _case_c_identity(case_lock, row, game)
            case_ids_by_key_game[(key, game)] = case_id
            cases.append(
                {
                    "record_type": "case",
                    "case_id": case_id,
                    "manifest_position": group_position * 2 + game - 1,
                    "content_sha256": canonical_sha256(identity),
                    "critical_group_ids": [],
                    "invariance_group_ids": [group_id],
                    "tags": ["case-c", "dual-order"],
                    "display_label": f"case-c-{group_position}-game-{game}",
                    "extensions": {_CASE_C_EXTENSION: identity},
                }
            )
            trials.extend(
                _case_c_trial(case_lock, row, game, role)
                for role in ("baseline", "candidate")
            )
    anchor_set = {
        "record_type": "anchor_set",
        "anchor_set_id": "case-c-human-anchors",
        "label_space": ["a", "b", "tie"],
        "protocol_id": "mt-bench-human-pairwise",
        "protocol_version": case_lock["revision"][:12],
        "aggregation_method": "none",
        "clustering_unit": "revision-question-turn-unordered-model-pair",
        "source_revision": case_lock["revision"],
        "source_sha256": case_lock["source_files"]["case-c/human.parquet"],
        "license": case_lock["license"],
        "provenance": _provenance(
            corpus_source=_component(case_lock["dataset"]),
            corpus_revision=_component(case_lock["revision"]),
            corpus_hash=_component(
                sha256=case_lock["source_files"]["case-c/human.parquet"]
            ),
            corpus_license=_component(case_lock["license"]),
            license_url=_component(
                "https://huggingface.co/datasets/lmsys/mt_bench_human_judgments"
            ),
        ),
        "extensions": {},
    }
    anchors: list[dict[str, Any]] = []
    for position, human in enumerate(human_rows):
        human_models = sorted((str(human["model_a"]), str(human["model_b"])))
        key = (
            int(human["question_id"]),
            int(human["turn"]),
            (human_models[0], human_models[1]),
        )
        selected_row = selected_by_key.get(key)
        if selected_row is None:
            raise ValueError("Case C human anchor has no selected raw group.")
        order = (str(human["model_a"]), str(human["model_b"]))
        source_order = (str(selected_row["model_1"]), str(selected_row["model_2"]))
        if order == source_order:
            game = 1
        elif order == tuple(reversed(source_order)):
            game = 2
        else:
            raise ValueError("Case C human anchor order does not match either game.")
        annotation_id = str(
            human.get("annotation_id", f"case-c-human-annotation-{position}")
        )
        anchor_id = _opaque_id(
            "case-c-anchor",
            {"revision": case_lock["revision"], "annotation_id": annotation_id},
        )
        annotator = str(human["judge"])
        annotator_id = _opaque_id(
            "case-c-annotator",
            {"revision": case_lock["revision"], "annotator": annotator},
        )
        anchors.append(
            {
                "record_type": "anchor",
                "anchor_id": anchor_id,
                "anchor_set_id": "case-c-human-anchors",
                "case_id": case_ids_by_key_game[(key, game)],
                "cluster_id": case_c_group_id(case_lock, selected_row),
                "annotation_id": annotation_id,
                "annotator_id": annotator_id,
                "kind": "raw_annotation",
                "status": "determinate",
                "label": normalize_case_c_human_winner(str(human["winner"])),
                "reason": None,
                "aggregation_inputs": [],
                "adjudication_rationale": None,
                "provenance": _provenance(
                    source_row=_component(
                        f"human-row-{int(human.get('source_position', position))}"
                    ),
                    original_artifact_hash=_component(
                        sha256=case_lock["source_files"]["case-c/human.parquet"]
                    ),
                    response_order=_component(f"{order[0]}:{order[1]}"),
                    source_judgment=_component(str(human["winner"])),
                ),
                "extensions": {
                    _CASE_C_EXTENSION: {
                        "game": game,
                        "display_model_order": list(order),
                    }
                },
            }
        )
    header["corpus"]["manifest_sha256"] = compute_manifest_sha256(
        header, cases, [], invariance
    )
    return [header, *invariance, anchor_set, *cases, *trials, *anchors]


def synthetic_case_c_rows(
    case_lock: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    human: list[dict[str, Any]] = []
    human_position = 0
    for source_position, fixture in enumerate(case_lock["synthetic_fixtures"]):
        row = {
            "source_position": source_position,
            "question_id": fixture["question_id"],
            "turn": fixture["turn"],
            "model_1": fixture["model_1"],
            "model_2": fixture["model_2"],
            "g1_winner": fixture["g1_winner"],
            "g2_winner": fixture["g2_winner"],
            "judge": "synthetic-source-judge",
        }
        selected.append(row)
        for anchor in fixture["anchors"]:
            game = int(anchor["game"])
            first = fixture["model_1"] if game == 1 else fixture["model_2"]
            second = fixture["model_2"] if game == 1 else fixture["model_1"]
            human.append(
                {
                    "source_position": human_position,
                    "question_id": fixture["question_id"],
                    "turn": fixture["turn"],
                    "model_a": first,
                    "model_b": second,
                    "winner": anchor["winner"],
                    "judge": anchor["annotator"],
                    "annotation_id": anchor["annotation_id"],
                }
            )
            human_position += 1
    return selected, human


def verify_case_c_synthetic_vectors(case_lock: dict[str, Any]) -> None:
    for fixture in case_lock["synthetic_fixtures"]:
        first = normalize_case_c_winner(str(fixture["g1_winner"]), 1)
        second = normalize_case_c_winner(str(fixture["g2_winner"]), 2)
        if first[0] != "determinate" or second[0] != "determinate":
            observed = "not_evaluable"
        elif (first[1], second[1]) in {("a", "b"), ("b", "a"), ("tie", "tie")}:
            observed = "satisfied"
        else:
            observed = "violated"
        if observed != fixture["expected_candidate_invariance"]:
            raise ValueError(
                f"Synthetic Case C expectation mismatch: {fixture['fixture_id']}"
            )


def _component(
    identity: str | None = None,
    sha256: str | None = None,
    *,
    presence: str | None = None,
) -> dict[str, Any]:
    effective = presence or (
        "present" if identity is not None or sha256 is not None else "not_applicable"
    )
    return {"presence": effective, "identity": identity, "sha256": sha256}


def _provenance(**values: dict[str, Any]) -> dict[str, Any]:
    return values


def _revision_url(repository: str, revision: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repository}/{revision}/{path}"


def _evaluation(
    case_name: str,
    role: str,
    case_lock: dict[str, Any],
) -> dict[str, Any]:
    revision = case_lock[f"{role}_revision"]
    source_files = {
        name: digest
        for name, digest in case_lock["source_files"].items()
        if f"/{role}/" in name and not name.endswith("LICENSE")
    }
    fingerprint = _sha256(
        "\n".join(
            f"{name}:{digest}" for name, digest in sorted(source_files.items())
        ).encode()
    )
    evaluator = {name: _component() for name in FIXED_EVALUATOR_COMPONENTS}
    context = {name: _component() for name in FIXED_CONTEXT_COMPONENTS}
    evaluator["implementation"] = _component(
        f"{case_name}-{role}-implementation", fingerprint
    )
    evaluator["parser"] = _component(f"{case_name}-{role}-parser", fingerprint)
    evaluator["aggregation_policy"] = _component("exact-required-test-conjunction")
    context["runner_adapter"] = _component("offline-inert-fixture-reader")
    context["harness_configuration"] = _component(f"{case_name}-locked-fixture")
    context["runtime"] = _component("python-stdlib-offline")
    context["dependency_lock"] = _component("hash-verified-upstream-source-only")
    context["resource_policy"] = _component("evaluator-assurance-default-limits")
    context["task_benchmark"] = _component(f"{case_name}-inert-fixtures")
    source_path = (
        "src/inspect_evals/swe_bench/scorers.py"
        if case_name == "case_a"
        else "swebench/harness/grading.py"
    )
    return {
        "evaluation_id": f"{case_name}-{role}",
        "role": role,
        "evaluator_id": f"{case_name}-{role}-evaluator",
        "evaluator_version": revision,
        "evaluator_fingerprint_sha256": fingerprint,
        "evaluator_components": evaluator,
        "context_id": f"{case_name}-shared-context",
        "context_fingerprint_sha256": canonical_sha256(context),
        "context_components": context,
        "provenance": _provenance(
            evaluator_source=_component(f"{case_name}-{role}-verified-source"),
            corpus_revision=_component(revision),
            source_url=_component(
                _revision_url(case_lock["repository"], revision, source_path)
            ),
        ),
    }


def _rule(
    rule_id: str,
    metric: str,
    *,
    scope: str = "all_cases",
    scope_id: str | None = None,
    parameters: dict[str, Any] | None = None,
    threshold: Decimal | int | None = 0,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "severity": "hard",
        "scope": scope,
        "scope_id": scope_id,
        "metric": metric,
        "operator": "eq",
        "threshold": threshold,
        "parameters": parameters or {},
        "missing_evidence": "hard_fail",
        "rationale": "Locked inert fixture expectation.",
        "extensions": {},
    }


def build_case_c_contract(
    *,
    group_count: int,
    baseline_error_count: int,
    candidate_error_count: int,
    candidate_not_evaluable_count: int,
) -> dict[str, Any]:
    rules = [
        _rule("corpus-equal", "corpus_equal", threshold=None),
        _rule("context-isolated", "context_isolated", threshold=None),
        _rule(
            "baseline-policy-exclusions",
            "status_count",
            parameters={"role": "baseline", "status": "abstain"},
            threshold=group_count,
        ),
        _rule(
            "baseline-source-errors",
            "status_count",
            parameters={"role": "baseline", "status": "error"},
            threshold=baseline_error_count,
        ),
        _rule(
            "candidate-source-errors",
            "status_count",
            parameters={"role": "candidate", "status": "error"},
            threshold=candidate_error_count,
        ),
        _rule(
            "baseline-invariance-not-evaluable",
            "invariance_not_evaluable_count",
            parameters={"role": "baseline"},
            threshold=group_count,
        ),
        _rule(
            "candidate-invariance-not-evaluable",
            "invariance_not_evaluable_count",
            parameters={"role": "candidate"},
            threshold=candidate_not_evaluable_count,
        ),
    ]
    return {
        "schema_version": "evaluator-assurance-contract-v1",
        "contract_id": "case-c-locked-contract",
        "contract_version": "1",
        "applies_to_input_schema": "evaluator-assurance-input-v1",
        "rules": rules,
        "extensions": {},
    }


def _contract(case_name: str) -> dict[str, Any]:
    if case_name == "case_a":
        rules = [
            _rule(
                "baseline-coverage",
                "determinate_coverage",
                parameters={"role": "baseline"},
                threshold=1,
            ),
            _rule(
                "candidate-coverage",
                "determinate_coverage",
                parameters={"role": "candidate"},
                threshold=Decimal("0.6"),
            ),
            _rule(
                "boundary-errors",
                "status_count",
                scope="critical_group",
                scope_id="missing-test-phase-boundary",
                parameters={"role": "candidate", "status": "error"},
                threshold=2,
            ),
            _rule(
                "new-boundary-errors",
                "new_status_count",
                parameters={"status": "error"},
                threshold=2,
            ),
        ]
    elif case_name == "case_b":
        rules = [
            _rule(
                "candidate-coverage",
                "determinate_coverage",
                parameters={"role": "candidate"},
                threshold=1,
            ),
            _rule(
                "closed-spoof-transition",
                "determinate_label_transition_count",
                parameters={"from_label": "pass", "to_label": "fail"},
                threshold=1,
            ),
            _rule(
                "critical-spoof-closure",
                "critical_regression_count",
                scope="critical_group",
                scope_id="spoofed-output-boundary",
                parameters={"from_label": "pass", "to_label": "fail"},
                threshold=1,
            ),
        ]
    elif case_name == "case_c":
        return build_case_c_contract(
            group_count=5,
            baseline_error_count=1,
            candidate_error_count=1,
            candidate_not_evaluable_count=1,
        )
    else:
        raise ValueError(f"Unknown assurance case: {case_name}")
    return {
        "schema_version": "evaluator-assurance-contract-v1",
        "contract_id": f"{case_name}-locked-contract",
        "contract_version": "1",
        "applies_to_input_schema": "evaluator-assurance-input-v1",
        "rules": rules,
        "extensions": {},
    }


def build_artifact(case_name: str, case_lock: dict[str, Any]) -> list[dict[str, Any]]:
    if case_name == "case_c":
        selected, human = synthetic_case_c_rows(case_lock)
        return build_case_c_artifact(case_lock, selected, human)
    if case_name not in {"case_a", "case_b"}:
        raise ValueError("Unknown assurance case.")
    group_id = (
        "missing-test-phase-boundary"
        if case_name == "case_a"
        else "spoofed-output-boundary"
    )
    group_members = (
        {"a-missing-start", "a-missing-end"}
        if case_name == "case_a"
        else {"b-spoof-nonzero"}
    )
    header: dict[str, Any] = {
        "record_type": "header",
        "schema_version": "evaluator-assurance-input-v1",
        "artifact_id": f"{case_name}-locked-artifact",
        "corpus": {
            "corpus_id": f"{case_name}-locked-corpus",
            "manifest_sha256": "0" * 64,
            "case_count": len(case_lock["fixtures"]),
            "identity_level": "content_hashes",
            "manifest_algorithm": "evaluator-assurance-manifest-v1",
        },
        "judgment_spec": {
            "judgment_spec_id": f"{case_name}-pass-fail-v1",
            "kind": "categorical",
            "label_space": ["pass", "fail"],
            "score_spec": None,
            "repeat_score_tolerance": None,
        },
        "evaluations": [
            _evaluation(case_name, "baseline", case_lock),
            _evaluation(case_name, "candidate", case_lock),
        ],
        "component_ownership": {
            "parser": "evaluator",
            "aggregation_policy": "evaluator",
        },
        "allowed_context_differences": [],
        "provenance": _provenance(
            corpus_source=_component(case_lock["repository"]),
            corpus_revision=_component(case_lock["candidate_revision"]),
            corpus_license=_component(case_lock["license"]),
            source_url=_component(f"https://github.com/{case_lock['repository']}"),
            license_url=_component(
                _revision_url(
                    case_lock["repository"], case_lock["candidate_revision"], "LICENSE"
                )
            ),
        ),
        "extensions": {},
    }
    critical = {
        "record_type": "critical_group",
        "group_id": group_id,
        "title": "Locked critical parser boundary",
        "declaration_source": "frozen-case-lock",
        "rationale": "Aggregate results cannot cancel this declared boundary.",
        "extensions": {},
    }
    cases: list[dict[str, Any]] = []
    trials: list[dict[str, Any]] = []
    judge = judge_case_a if case_name == "case_a" else judge_case_b
    for position, fixture in enumerate(case_lock["fixtures"]):
        case_id = fixture["case_id"]
        cases.append(
            {
                "record_type": "case",
                "case_id": case_id,
                "manifest_position": position,
                "content_sha256": fixture["sha256"],
                "critical_group_ids": [group_id] if case_id in group_members else [],
                "invariance_group_ids": [],
                "tags": [],
                "display_label": case_id,
                "extensions": {},
            }
        )
        for role in ("baseline", "candidate"):
            status, label = judge(fixture["text"], role)
            trial_provenance = _provenance(
                source_row=_component(case_id),
                source_judgment=_component(f"{status}-{label or 'null'}"),
                original_artifact_hash=_component(sha256=fixture["sha256"]),
            )
            if case_name == "case_b":
                match = _EXIT_CODE.search(fixture["text"])
                trial_provenance["test_command_status"] = _component(
                    match.group(1) if match else None,
                    presence="present" if match else "missing",
                )
                reset_failed = "error: pathspec" in fixture["text"]
                trial_provenance["reset_status"] = _component(
                    "failed" if reset_failed else None,
                    presence="present" if reset_failed else "missing",
                )
            trials.append(
                {
                    "record_type": "trial",
                    "case_id": case_id,
                    "evaluation_id": f"{case_name}-{role}",
                    "trial_id": f"{case_id}-{role}",
                    "source_order": 0,
                    "pairing_key": "locked-fixture",
                    "status": status,
                    "label": label,
                    "score": None,
                    "reason": None,
                    "details": None,
                    "error": {"error_class": "MissingTestPhaseBoundary"}
                    if status == "error"
                    else None,
                    "provenance": trial_provenance,
                    "extensions": {},
                }
            )
    header["corpus"]["manifest_sha256"] = compute_manifest_sha256(
        header, cases, [critical], []
    )
    return [header, critical, *cases, *trials]


def _write_json(path: Path, value: Any, *, jsonl: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if jsonl:
        data = "\n".join(canonical_json_text(item) for item in value) + "\n"
    else:
        data = canonical_json_text(value) + "\n"
    path.write_text(data, encoding="utf-8", newline="\n")


def prepare_case(
    source_root: Path,
    output_root: Path,
    case_name: str,
    case_lock: dict[str, Any],
) -> dict[str, Any]:
    if case_name == "case_c":
        verify_case_c_synthetic_vectors(case_lock)
        verified = ["tracked-original-synthetic-fixtures"]
        fixture_count = len(case_lock["synthetic_fixtures"])
        output_name = "case-c-synthetic"
    else:
        verified = verify_source_files(source_root, case_lock)
        verify_source_semantics(source_root, case_name)
        verify_fixture_vectors(case_name, case_lock)
        fixture_count = len(case_lock["fixtures"])
        output_name = case_name.replace("_", "-")
    case_output = output_root / output_name
    input_path = case_output / "input.jsonl"
    contract_path = case_output / "contract.json"
    _write_json(input_path, build_artifact(case_name, case_lock), jsonl=True)
    _write_json(contract_path, _contract(case_name))
    artifact = load_artifact(input_path)
    loaded_contract = load_contract(contract_path, artifact)
    report = build_report(artifact, loaded_contract)
    write_report_bundle(
        report,
        case_output / "report",
        limits=Limits(),
        source_paths=(input_path, contract_path),
    )
    if exit_code_for_report(report) != 0:
        raise ValueError(f"Locked case contract did not pass: {case_name}")
    return {
        "case": case_name,
        "verified_source_files": verified,
        "fixture_count": fixture_count,
        "input_sha256": _sha256(input_path.read_bytes()),
        "contract_sha256": _sha256(contract_path.read_bytes()),
        "report_sha256": _sha256((case_output / "report/report.json").read_bytes()),
        "report_status": report["report_status"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--case-lock", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--case", choices=("case_a", "case_b", "case_c", "all"), default="all"
    )
    args = parser.parse_args()
    locks = load_case_lock(args.case_lock)
    selected = ("case_a", "case_b", "case_c") if args.case == "all" else (args.case,)
    results = [
        prepare_case(args.source_root, args.out, name, locks[name]) for name in selected
    ]
    print(canonical_json_text({"results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
