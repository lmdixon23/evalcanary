from __future__ import annotations

import io
import json
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from decimal import Decimal
from itertools import product
from pathlib import Path

from scripts.generate_assurance_examples import example_evaluation, example_packets

from evalcanary.assurance import (
    complete_evaluation as public_complete_evaluation,
)
from evalcanary.assurance import (
    sha256_bytes as public_sha256_bytes,
)
from evalcanary.assurance import (
    sha256_value as public_sha256_value,
)
from evalcanary.assurance.constants import (
    FIXED_CONTEXT_COMPONENTS,
    FIXED_EVALUATOR_COMPONENTS,
    MOVABLE_COMPONENTS,
)
from evalcanary.assurance.numeric import canonical_json_bytes
from evalcanary.assurance.producer import (
    AssurancePacket,
    Contract,
    Rule,
    complete_components,
    complete_evaluation,
    component_requirements,
    component_value,
    make_evaluation,
    sha256_bytes,
    sha256_value,
)
from evalcanary.assurance.schema import load_artifact, load_contract
from evalcanary.cli import main
from evalcanary.errors import InputValidationError

EXAMPLE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "evalcanary"
    / "examples"
    / "assurance"
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _small_packet(
    case_order: tuple[str, ...], *, pairing_key: str | None = "pair-0"
) -> AssurancePacket:
    packet = AssurancePacket(
        artifact_id="deterministic-example",
        corpus_id="deterministic-corpus",
        identity_level="content_hashes",
        judgment_spec={
            "judgment_spec_id": "labels-v1",
            "kind": "categorical",
            "label_space": ["pass", "fail"],
            "score_spec": None,
            "repeat_score_tolerance": None,
        },
        evaluations=[example_evaluation("candidate"), example_evaluation("baseline")],
        component_ownership={"aggregation_policy": "evaluator", "parser": "context"},
        provenance={},
        allowed_context_differences=[],
    )
    for case_id in case_order:
        packet.add_case(
            case_id,
            content_bytes=f"content:{case_id}".encode(),
            critical_group_ids=(),
            invariance_group_ids=(),
        )
    for case_id in reversed(case_order):
        for role in ("candidate", "baseline"):
            packet.add_trial(
                case_id=case_id,
                evaluation_id=f"eval-{role}",
                trial_id=f"{case_id}-{role}",
                source_order=0,
                pairing_key=pairing_key,
                status="determinate",
                label="pass",
                score=None,
                error=None,
            )
    return packet


def _small_contract() -> Contract:
    return Contract(
        contract_id="compact-contract",
        contract_version="1",
        rules=[
            Rule(
                rule_id="no-new-errors",
                severity="hard",
                scope="all_cases",
                scope_id=None,
                metric="new_status_count",
                operator="lte",
                threshold=0,
                parameters={"status": "error"},
                missing_evidence="hard_fail",
                rationale="Reject newly observed source errors.",
            )
        ],
    )


def _completed_scaffold_choices() -> dict[str, object]:
    ownership = {"parser": "context", "aggregation_policy": "evaluator"}
    evaluations = {}
    for role in ("baseline", "candidate"):
        evaluations[role] = {
            "evaluation_id": f"eval-{role}",
            "evaluator_id": f"evaluator-{role}",
            "evaluator_version": "1",
            "evaluator_fingerprint_sha256": sha256_bytes(f"evaluator-{role}".encode()),
            "context_id": "shared-context",
            "context_fingerprint_sha256": sha256_bytes(b"shared-context"),
            "component_values": {
                "implementation": component_value(
                    "present", identity=f"implementation-{role}"
                ),
                "aggregation_policy": component_value(
                    "present", identity="aggregation-v1"
                ),
                "parser": component_value("present", identity="parser-v1"),
            },
            "confirm_unlisted_not_applicable": True,
            "provenance": {},
        }
    trial_source = [
        {
            "case_id": "case-a",
            "role": role,
            "trial_id": f"case-a-{role}",
            "source_order": 0,
            "mapped_pairing_key": "pair-a",
            "mapped_status": "determinate",
            "mapped_label": "pass",
            "mapped_score": None,
            "mapped_error": None,
        }
        for role in ("baseline", "candidate")
    ]

    def status_mapping(source):
        return {
            "status": source["mapped_status"],
            "label": source["mapped_label"],
            "score": source["mapped_score"],
            "error": source["mapped_error"],
        }

    def pairing_policy(source):
        return source["mapped_pairing_key"]

    return {
        "COMPONENT_OWNERSHIP": ownership,
        "ALLOWED_CONTEXT_DIFFERENCES": [],
        "PACKET": {
            "artifact_id": "completed-scaffold",
            "corpus_id": "completed-corpus",
            "identity_level": "content_hashes",
            "judgment_spec_id": "completed-labels-v1",
            "provenance": {},
        },
        "EVALUATIONS": evaluations,
        "CASES": [
            {
                "case_id": "case-a",
                "content_bytes": b"case-a",
                "critical_group_ids": [],
                "invariance_group_ids": [],
            }
        ],
        "TRIAL_SOURCE": trial_source,
        "STATUS_MAPPING": status_mapping,
        "PAIRING_POLICY": pairing_policy,
        "CRITICAL_GROUPS": [],
        "INVARIANCE_GROUPS": [],
        "ANCHOR_SETS": [],
        "ANCHORS": [],
    }


class AssuranceProducerScaffoldTests(unittest.TestCase):
    def test_exact_hash_helpers_and_explicit_component_values(self) -> None:
        self.assertEqual(sha256_value({"b": 2, "a": 1}), sha256_value({"a": 1, "b": 2}))
        self.assertNotEqual(sha256_bytes(b"exact-a"), sha256_bytes(b"exact-b"))
        self.assertIs(public_sha256_bytes, sha256_bytes)
        self.assertIs(public_sha256_value, sha256_value)
        self.assertEqual(
            component_value("present", identity="caller-supplied"),
            {"presence": "present", "identity": "caller-supplied", "sha256": None},
        )
        with self.assertRaises(InputValidationError):
            component_value("present")

    def test_public_component_requirements_match_authoritative_vocabulary(self) -> None:
        for parser_owner, aggregation_owner in product(
            ("evaluator", "context"), repeat=2
        ):
            ownership = {
                "parser": parser_owner,
                "aggregation_policy": aggregation_owner,
            }
            requirements = component_requirements(ownership)
            expected_evaluator = set(FIXED_EVALUATOR_COMPONENTS)
            expected_context = set(FIXED_CONTEXT_COMPONENTS)
            for name, owner in ownership.items():
                (expected_evaluator if owner == "evaluator" else expected_context).add(
                    name
                )
            self.assertEqual(
                requirements["evaluator_components"],
                tuple(sorted(expected_evaluator)),
            )
            self.assertEqual(
                requirements["context_components"],
                tuple(sorted(expected_context)),
            )
        self.assertEqual(set(MOVABLE_COMPONENTS), {"parser", "aggregation_policy"})
        with self.assertRaisesRegex(InputValidationError, r"missing=\[parser\]"):
            component_requirements({"aggregation_policy": "evaluator"})

    def test_public_guide_eliminates_the_three_mechanical_ambiguities(self) -> None:
        guide = (PROJECT_ROOT / "docs" / "EVALUATOR_ASSURANCE.md").read_text()
        self.assertIn(
            "from evalcanary.assurance import sha256_bytes, sha256_value", guide
        )
        self.assertNotIn(
            "from evalcanary.assurance.producer import sha256_bytes", guide
        )
        self.assertIn('critical_group_ids=["release-blockers"]', guide)
        self.assertIn('invariance_group_ids=["paraphrase-pair"]', guide)
        self.assertIn("There is no\n`assign_case_groups` API", guide)

    def test_semantic_empty_choices_must_be_explicit_but_remain_available(
        self,
    ) -> None:
        evaluation_args = {
            "artifact_id": "missing-context-choice",
            "corpus_id": "corpus",
            "identity_level": "content_hashes",
            "judgment_spec": {
                "judgment_spec_id": "labels-v1",
                "kind": "categorical",
                "label_space": ["pass", "fail"],
                "score_spec": None,
                "repeat_score_tolerance": None,
            },
            "evaluations": [
                example_evaluation("baseline"),
                example_evaluation("candidate"),
            ],
            "component_ownership": {
                "aggregation_policy": "evaluator",
                "parser": "context",
            },
            "provenance": {},
        }
        with self.assertRaisesRegex(TypeError, "allowed_context_differences"):
            AssurancePacket(**evaluation_args)

        packet = _small_packet(("case-a",))
        with self.assertRaisesRegex(TypeError, "pairing_key"):
            packet.add_trial(
                case_id="case-a",
                evaluation_id="eval-baseline",
                trial_id="omitted-pairing",
                source_order=1,
                status="determinate",
                label="pass",
                score=None,
                error=None,
            )
        with self.assertRaisesRegex(TypeError, "label"):
            packet.add_trial(
                case_id="case-a",
                evaluation_id="eval-baseline",
                trial_id="omitted-label",
                source_order=1,
                status="determinate",
                pairing_key="pair-1",
                score=None,
                error=None,
            )
        with self.assertRaisesRegex(TypeError, "error"):
            packet.add_trial(
                case_id="case-a",
                evaluation_id="eval-baseline",
                trial_id="omitted-error-applicability",
                source_order=1,
                status="determinate",
                pairing_key="pair-1",
                label="pass",
                score=None,
            )
        with self.assertRaisesRegex(TypeError, "critical_group_ids"):
            packet.add_case(
                "case-b",
                content_bytes=b"case-b",
                invariance_group_ids=(),
            )

        explicitly_empty = _small_packet(("case-a",), pairing_key=None)
        explicitly_empty.canonical_bytes()
        records = explicitly_empty.canonical_records()
        self.assertEqual(records[0]["allowed_context_differences"], [])
        trials = [record for record in records if record["record_type"] == "trial"]
        self.assertTrue(all(trial["pairing_key"] is None for trial in trials))

    def test_bulk_not_applicable_is_explicit_and_preserves_overrides(self) -> None:
        ownership = {"parser": "context", "aggregation_policy": "evaluator"}
        declarations = {
            "evaluator_components": {
                "implementation": component_value(
                    "present", identity="explicit-implementation"
                ),
                "rubric_prompt": component_value("missing"),
            },
            "context_components": {
                "runtime": component_value("intentionally_omitted"),
                "response_order": component_value("not_applicable"),
            },
        }
        with self.assertRaisesRegex(
            InputValidationError, "confirm_unlisted_not_applicable=True"
        ):
            complete_components(ownership=ownership, **declarations)
        completed = complete_components(
            ownership=ownership,
            **declarations,
            confirm_unlisted_not_applicable=True,
        )
        self.assertEqual(
            completed.evaluator_components["rubric_prompt"]["presence"], "missing"
        )
        self.assertEqual(
            completed.context_components["runtime"]["presence"],
            "intentionally_omitted",
        )
        self.assertEqual(
            completed.context_components["response_order"]["presence"],
            "not_applicable",
        )
        self.assertEqual(
            completed.evaluator_components["model_provider"]["presence"],
            "not_applicable",
        )
        with self.assertRaisesRegex(InputValidationError, "duplicate_across_sides"):
            complete_components(
                ownership=ownership,
                evaluator_components={
                    "implementation": component_value(
                        "present", identity="explicit-evaluator"
                    )
                },
                context_components={
                    "implementation": component_value(
                        "present", identity="explicit-context"
                    )
                },
                confirm_unlisted_not_applicable=True,
            )

    def test_inventory_diagnostics_are_field_specific_and_private_value_free(
        self,
    ) -> None:
        incomplete = example_evaluation("candidate")
        object.__setattr__(
            incomplete,
            "evaluator_components",
            {
                "implementation": component_value(
                    "present", identity="PRIVATE_COMPONENT_IDENTITY"
                ),
                "unexpected_component": component_value("present", sha256="1" * 64),
            },
        )
        object.__setattr__(
            incomplete,
            "evaluator_not_applicable",
            ["implementation", "implementation"],
        )
        with self.assertRaises(InputValidationError) as caught:
            incomplete.document(
                {"parser": "context", "aggregation_policy": "evaluator"}
            )
        message = str(caught.exception)
        self.assertIn("candidate evaluation eval-candidate", message)
        self.assertIn("evaluator_components", message)
        self.assertIn(
            "missing=[aggregation_policy, model_provider, rubric_prompt]", message
        )
        self.assertIn("unexpected=[unexpected_component]", message)
        self.assertIn("duplicate_supplied_or_not_applicable=[implementation]", message)
        self.assertNotIn("PRIVATE_COMPONENT_IDENTITY", message)
        self.assertNotIn("111111", message)

    def test_runtime_inventory_diagnostic_lists_side_missing_and_unexpected(
        self,
    ) -> None:
        records = list(deepcopy(_small_packet(("case-a",)).canonical_records()))
        candidate = records[0]["evaluations"][1]
        candidate["context_components"].pop("response_order")
        candidate["context_components"]["unexpected_component"] = component_value(
            "present", identity="PRIVATE_COMPONENT_IDENTITY"
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "invalid.jsonl"
            path.write_bytes(
                b"\n".join(canonical_json_bytes(item) for item in records) + b"\n"
            )
            with self.assertRaises(InputValidationError) as caught:
                load_artifact(path)
        message = str(caught.exception)
        self.assertIn("candidate evaluation eval-candidate", message)
        self.assertIn("context_components missing=[response_order]", message)
        self.assertIn("unexpected=[unexpected_component]", message)
        self.assertNotIn("PRIVATE_COMPONENT_IDENTITY", message)

    def test_compact_evaluation_factory_matches_explicit_construction(self) -> None:
        ownership = {"parser": "context", "aggregation_policy": "evaluator"}
        direct = example_evaluation("baseline")
        completed = complete_components(
            ownership=ownership,
            evaluator_components=direct.evaluator_components,
            context_components=direct.context_components,
            confirm_unlisted_not_applicable=True,
        )
        compact = make_evaluation(
            evaluation_id=direct.evaluation_id,
            role=direct.role,
            evaluator_id=direct.evaluator_id,
            evaluator_version=direct.evaluator_version,
            evaluator_fingerprint_sha256=direct.evaluator_fingerprint_sha256,
            context_id=direct.context_id,
            context_fingerprint_sha256=direct.context_fingerprint_sha256,
            component_ownership=ownership,
            components=completed,
            provenance=direct.provenance,
        )
        self.assertEqual(compact.document(ownership), direct.document(ownership))
        with self.assertRaisesRegex(InputValidationError, "does not match"):
            make_evaluation(
                evaluation_id=direct.evaluation_id,
                role=direct.role,
                evaluator_id=direct.evaluator_id,
                evaluator_version=direct.evaluator_version,
                evaluator_fingerprint_sha256=direct.evaluator_fingerprint_sha256,
                context_id=direct.context_id,
                context_fingerprint_sha256=direct.context_fingerprint_sha256,
                component_ownership={
                    "parser": "evaluator",
                    "aggregation_policy": "context",
                },
                components=completed,
                provenance=direct.provenance,
            )

    def test_flat_component_evaluation_is_explicit_and_byte_equivalent(self) -> None:
        ownership = {"parser": "context", "aggregation_policy": "evaluator"}
        direct = example_evaluation("baseline")
        component_values = {
            **direct.evaluator_components,
            **direct.context_components,
        }
        compact = complete_evaluation(
            evaluation_id=direct.evaluation_id,
            role=direct.role,
            evaluator_id=direct.evaluator_id,
            evaluator_version=direct.evaluator_version,
            evaluator_fingerprint_sha256=direct.evaluator_fingerprint_sha256,
            context_id=direct.context_id,
            context_fingerprint_sha256=direct.context_fingerprint_sha256,
            component_ownership=ownership,
            component_values=component_values,
            confirm_unlisted_not_applicable=True,
            provenance=direct.provenance,
        )
        self.assertIs(public_complete_evaluation, complete_evaluation)
        self.assertEqual(compact.document(ownership), direct.document(ownership))
        with self.assertRaisesRegex(
            InputValidationError, "confirm_unlisted_not_applicable=True"
        ):
            complete_evaluation(
                evaluation_id=direct.evaluation_id,
                role=direct.role,
                evaluator_id=direct.evaluator_id,
                evaluator_version=direct.evaluator_version,
                evaluator_fingerprint_sha256=direct.evaluator_fingerprint_sha256,
                context_id=direct.context_id,
                context_fingerprint_sha256=direct.context_fingerprint_sha256,
                component_ownership=ownership,
                component_values=component_values,
                confirm_unlisted_not_applicable=False,
                provenance=direct.provenance,
            )

    def test_compact_contract_matches_direct_normative_contract(self) -> None:
        direct = {
            "schema_version": "evaluator-assurance-contract-v1",
            "contract_id": "compact-contract",
            "contract_version": "1",
            "applies_to_input_schema": "evaluator-assurance-input-v1",
            "rules": [
                {
                    "rule_id": "no-new-errors",
                    "severity": "hard",
                    "scope": "all_cases",
                    "scope_id": None,
                    "metric": "new_status_count",
                    "operator": "lte",
                    "threshold": 0,
                    "parameters": {"status": "error"},
                    "missing_evidence": "hard_fail",
                    "rationale": "Reject newly observed source errors.",
                    "extensions": {},
                }
            ],
            "extensions": {},
        }
        compact = _small_contract()
        self.assertEqual(compact.document(), direct)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact_path = _small_packet(("case-a",)).write(root / "input.jsonl")
            artifact = load_artifact(artifact_path)
            contract_path = compact.write(root / "contract.json", artifact=artifact)
            self.assertEqual(load_contract(contract_path, artifact).document, direct)
        with self.assertRaisesRegex(InputValidationError, "parameters are invalid"):
            Rule(
                rule_id="bad-signature",
                severity="hard",
                scope="all_cases",
                scope_id=None,
                metric="new_status_count",
                operator="lte",
                threshold=0,
                parameters={},
                missing_evidence="hard_fail",
                rationale="No inferred parameter.",
            ).document()
        with self.assertRaisesRegex(InputValidationError, "non-empty"):
            Contract(
                contract_id="no-policy",
                contract_version="1",
                rules=[],
            ).document()

    def test_contract_write_accepts_object_and_path_with_byte_parity(self) -> None:
        contract = _small_contract()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = _small_packet(("case-a",)).write(root / "input.jsonl")
            artifact = load_artifact(input_path)
            object_path = contract.write(root / "object.json", artifact=artifact)
            path_path = contract.write(root / "path.json", artifact=input_path)
            string_path = contract.write(root / "string.json", artifact=str(input_path))

            self.assertEqual(object_path.read_bytes(), path_path.read_bytes())
            self.assertEqual(path_path.read_bytes(), string_path.read_bytes())
            self.assertEqual(
                load_contract(object_path, artifact).document,
                load_contract(path_path, artifact).document,
            )

    def test_contract_path_failure_is_normative_and_private_value_free(self) -> None:
        secret = "PRIVATE_SOURCE_VALUE_MUST_NOT_APPEAR"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            invalid_path = root / "invalid.jsonl"
            invalid_path.write_text(
                json.dumps({"record_type": "header", "private_value": secret}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(InputValidationError) as normative:
                load_artifact(invalid_path)
            output_path = root / "must-not-exist.json"
            with self.assertRaises(InputValidationError) as bridged:
                _small_contract().write(output_path, artifact=invalid_path)

            self.assertEqual(str(bridged.exception), str(normative.exception))
            self.assertNotIn(secret, str(bridged.exception))
            self.assertFalse(output_path.exists())

    def test_rule_is_keyword_only_and_retains_exact_semantics(self) -> None:
        expected = _small_contract().document()["rules"][0]
        self.assertEqual(next(iter(_small_contract().rules)).document(), expected)
        with self.assertRaisesRegex(TypeError, "positional argument"):
            Rule(
                "no-new-errors",
                "hard",
                "all_cases",
                None,
                "new_status_count",
                {"status": "error"},
                "lte",
                0,
                "hard_fail",
                "Reject newly observed source errors.",
            )

    def test_evaluation_ids_by_role_is_exact_and_read_only(self) -> None:
        packet = _small_packet(("case-a",))
        evaluation_ids = packet.evaluation_ids_by_role
        self.assertEqual(
            dict(evaluation_ids),
            {"baseline": "eval-baseline", "candidate": "eval-candidate"},
        )
        with self.assertRaises(TypeError):
            evaluation_ids["baseline"] = "mutated"
        self.assertEqual(packet.evaluation_ids_by_role["baseline"], "eval-baseline")

    def test_authoring_bridge_adds_no_mandatory_runtime_dependency(self) -> None:
        project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
        self.assertEqual(project["project"]["dependencies"], [])

    def test_equivalent_addition_orders_are_byte_identical(self) -> None:
        first = _small_packet(("case-b", "case-a"))
        second = _small_packet(("case-a", "case-b"))
        self.assertEqual(first.canonical_bytes(), second.canonical_bytes())

    def test_atomic_write_uses_normative_validator_and_retains_explicit_identity(
        self,
    ) -> None:
        packet = _small_packet(("case-a", "case-b"))
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "nested" / "assurance.jsonl"
            self.assertEqual(packet.write(target), target.resolve())
            artifact = load_artifact(target)
        evaluations = {item["role"]: item for item in artifact.header["evaluations"]}
        self.assertEqual(
            evaluations["baseline"]["evaluator_fingerprint_sha256"],
            sha256_bytes(b"exact-example-evaluator-baseline"),
        )

    def test_invalid_references_and_inventories_fail_before_final_artifact(
        self,
    ) -> None:
        packet = _small_packet(("case-a",))
        packet._cases[0]["invariance_group_ids"] = ["undeclared-group"]
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "must-not-exist.jsonl"
            with self.assertRaisesRegex(InputValidationError, "undeclared group"):
                packet.write(target)
            self.assertFalse(target.exists())
        incomplete = example_evaluation("baseline")
        object.__setattr__(incomplete, "context_not_applicable", set())
        with self.assertRaisesRegex(
            InputValidationError, "context_components inventory is invalid"
        ):
            incomplete.document(
                {"parser": "context", "aggregation_policy": "evaluator"}
            )

    def test_release_examples_are_exact_valid_and_cover_required_concepts(self) -> None:
        generated = example_packets()
        self.assertEqual(
            set(generated),
            {"categorical.jsonl", "categorical-numeric.jsonl", "numeric.jsonl"},
        )
        artifacts = {}
        for filename, packet in generated.items():
            path = EXAMPLE_ROOT / filename
            self.assertEqual(path.read_bytes(), packet.canonical_bytes())
            artifacts[filename] = load_artifact(path)
        categorical = artifacts["categorical.jsonl"]
        statuses = {trial["status"] for trial in categorical.trials}
        self.assertTrue(
            {"determinate", "abstain", "indeterminate", "error"} <= statuses
        )
        self.assertGreater(len(categorical.trials), len(categorical.cases) * 2)
        self.assertIn(
            "swapped_preference",
            {item["expected_relation"] for item in categorical.invariance_groups},
        )
        self.assertEqual(
            {item["kind"] for item in categorical.anchors},
            {"raw_annotation", "aggregate"},
        )
        numeric = artifacts["numeric.jsonl"]
        self.assertEqual(numeric.header["judgment_spec"]["kind"], "numeric")
        self.assertIn(
            "same_score_within_tolerance",
            {item["expected_relation"] for item in numeric.invariance_groups},
        )
        combined = artifacts["categorical-numeric.jsonl"]
        self.assertEqual(
            combined.header["judgment_spec"]["kind"], "categorical_and_numeric"
        )
        self.assertEqual(len(combined.header["allowed_context_differences"]), 1)
        scores = {trial["score"] for trial in combined.trials}
        self.assertEqual(scores, {Decimal("0.6"), Decimal("0.8")})

    def test_init_is_inert_for_all_judgment_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            invocations = (
                ("categorical", ["--label", "pass", "--label", "fail"]),
                ("numeric", []),
                (
                    "categorical_and_numeric",
                    ["--label", "pass", "--label", "fail"],
                ),
            )
            for judgment, labels in invocations:
                output = root / judgment
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "init",
                            "--judgment",
                            judgment,
                            *labels,
                            "--out",
                            str(output),
                        ]
                    )
                self.assertEqual(code, 0)
                self.assertEqual(
                    {item.name for item in output.iterdir()},
                    {"README.md", "producer_mapping.py", "scaffold.json"},
                )
                metadata = json.loads((output / "scaffold.json").read_text())
                self.assertEqual(metadata["state"], "INERT_REQUIRES_SEMANTIC_CHOICES")
                self.assertFalse(metadata["contract_emitted"])
                self.assertEqual(
                    metadata["component_inventory"]["fixed_evaluator_components"],
                    sorted(FIXED_EVALUATOR_COMPONENTS),
                )
                self.assertEqual(
                    metadata["component_inventory"]["fixed_context_components"],
                    sorted(FIXED_CONTEXT_COMPONENTS),
                )
                self.assertEqual(
                    metadata["component_inventory"]["movable_components"],
                    sorted(MOVABLE_COMPONENTS),
                )
                mapping = (output / "producer_mapping.py").read_text()
                compile(mapping, str(output / "producer_mapping.py"), "exec")
                self.assertIn("AUTHORING_INCOMPLETE", mapping)
                self.assertIn("class _UnresolvedChoice", mapping)
                self.assertIn("COMPONENT_OWNERSHIP = unresolved", mapping)
                self.assertIn("ALLOWED_CONTEXT_DIFFERENCES = unresolved", mapping)
                self.assertIn("CASES = unresolved", mapping)
                self.assertIn("TRIAL_SOURCE = unresolved", mapping)
                self.assertIn("def STATUS_MAPPING(", mapping)
                self.assertIn("def PAIRING_POLICY(", mapping)
                self.assertIn("component_requirements(ownership)", mapping)
                self.assertIn("complete_evaluation(", mapping)
                self.assertIn('("baseline", "candidate")', mapping)
                self.assertIn("packet.add_cases(CASES)", mapping)
                self.assertIn("packet.add_trials(", mapping)
                self.assertIn("packet.evaluation_ids_by_role", mapping)
                self.assertIn("def write_outputs(", mapping)
                self.assertIn("artifact=finalized_input", mapping)
                readme = (output / "README.md").read_text()
                self.assertIn("SEMANTIC DECISIONS", readme)
                self.assertIn("MECHANICAL REPRESENTATION", readme)
                self.assertIn("FIXED EVALUATOR COMPONENTS", readme)
                self.assertIn("FIXED CONTEXT COMPONENTS", readme)
                self.assertIn("MOVABLE COMPONENTS", readme)
                self.assertIn("response_order", readme)
                self.assertIn("sampling_settings", readme)
                self.assertIn(
                    "never determines\nwhether component identities should change",
                    readme,
                )
                self.assertIn("substantive semantic choice is true or", readme)
                self.assertIn("There is no\n`assign_case_groups` method", readme)
                self.assertIn(
                    "contract.write(contract_path, artifact=input_path)", readme
                )
                self.assertIn("explicit keyword-only `Rule`", readme)
                self.assertIn("replaydocket migrate --preflight", readme)
                self.assertIn("replaydocket migrate --input", readme)
                self.assertFalse((output / "evaluator-assurance.jsonl").exists())
                namespace = {"__name__": "untouched_scaffold_under_test"}
                exec(
                    compile(mapping, str(output / "producer_mapping.py"), "exec"),
                    namespace,
                )
                with self.assertRaisesRegex(RuntimeError, "AUTHORING_INCOMPLETE"):
                    namespace["write_outputs"](
                        contract=_small_contract(),
                        input_path=output / "evaluator-assurance.jsonl",
                        contract_path=output / "contract.json",
                    )
                self.assertFalse((output / "evaluator-assurance.jsonl").exists())
                self.assertFalse((output / "contract.json").exists())

    def test_scaffold_guard_rejects_every_unresolved_semantic_class(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            scaffold = Path(temp) / "scaffold"
            self.assertEqual(
                main(
                    [
                        "init",
                        "--judgment",
                        "categorical",
                        "--label",
                        "pass",
                        "--label",
                        "fail",
                        "--out",
                        str(scaffold),
                    ]
                ),
                0,
            )
            mapping = (scaffold / "producer_mapping.py").read_text()
            namespace: dict[str, object] = {"__name__": "guard_under_test"}
            exec(
                compile(mapping, str(scaffold / "producer_mapping.py"), "exec"),
                namespace,
            )
            unresolved = namespace["unresolved"]
            paths = (
                ("artifact identity", ("PACKET", "artifact_id")),
                ("corpus identity", ("PACKET", "corpus_id")),
                ("judgment identity", ("PACKET", "judgment_spec_id")),
                (
                    "evaluation identity",
                    ("EVALUATIONS", "baseline", "evaluation_id"),
                ),
                ("evaluator identity", ("EVALUATIONS", "baseline", "evaluator_id")),
                (
                    "evaluator version",
                    ("EVALUATIONS", "baseline", "evaluator_version"),
                ),
                (
                    "evaluator fingerprint",
                    (
                        "EVALUATIONS",
                        "baseline",
                        "evaluator_fingerprint_sha256",
                    ),
                ),
                ("context identity", ("EVALUATIONS", "baseline", "context_id")),
                (
                    "context fingerprint",
                    ("EVALUATIONS", "baseline", "context_fingerprint_sha256"),
                ),
                (
                    "component identity",
                    (
                        "EVALUATIONS",
                        "baseline",
                        "component_values",
                        "implementation",
                        "identity",
                    ),
                ),
                ("parser ownership", ("COMPONENT_OWNERSHIP", "parser")),
                (
                    "aggregation ownership",
                    ("COMPONENT_OWNERSHIP", "aggregation_policy"),
                ),
                ("case identity", ("CASES", 0, "case_id")),
                ("case content", ("CASES", 0, "content_bytes")),
                ("critical group decision", ("CASES", 0, "critical_group_ids")),
                (
                    "case invariance decision",
                    ("CASES", 0, "invariance_group_ids"),
                ),
                ("trial case identity", ("TRIAL_SOURCE", 0, "case_id")),
                (
                    "trial pairing mapping",
                    ("TRIAL_SOURCE", 0, "mapped_pairing_key"),
                ),
                ("trial status mapping", ("TRIAL_SOURCE", 0, "mapped_status")),
                ("trial label mapping", ("TRIAL_SOURCE", 0, "mapped_label")),
                ("trial score mapping", ("TRIAL_SOURCE", 0, "mapped_score")),
                ("trial error mapping", ("TRIAL_SOURCE", 0, "mapped_error")),
                ("context differences", ("ALLOWED_CONTEXT_DIFFERENCES",)),
                ("critical groups", ("CRITICAL_GROUPS",)),
                ("invariance relations", ("INVARIANCE_GROUPS",)),
                ("anchor-set interpretation", ("ANCHOR_SETS",)),
                ("anchor declarations", ("ANCHORS",)),
            )
            for name, path in paths:
                with self.subTest(name=name):
                    choices = _completed_scaffold_choices()
                    cursor = choices
                    for key in path[:-1]:
                        cursor = cursor[key]
                    cursor[path[-1]] = unresolved(f"still unresolved: {name}")
                    namespace.update(choices)
                    with self.assertRaisesRegex(RuntimeError, "AUTHORING_INCOMPLETE"):
                        namespace["build_packet"]()

            explicit_empty = _completed_scaffold_choices()
            for trial in explicit_empty["TRIAL_SOURCE"]:
                trial["mapped_pairing_key"] = None
            namespace.update(explicit_empty)
            namespace["build_packet"]().canonical_bytes()

    def test_status_and_pairing_mappings_causally_control_trial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            scaffold = Path(temp) / "scaffold"
            self.assertEqual(
                main(
                    [
                        "init",
                        "--judgment",
                        "categorical",
                        "--label",
                        "pass",
                        "--label",
                        "fail",
                        "--out",
                        str(scaffold),
                    ]
                ),
                0,
            )
            mapping_path = scaffold / "producer_mapping.py"
            namespace: dict[str, object] = {"__name__": "binding_under_test"}
            exec(
                compile(mapping_path.read_text(), str(mapping_path), "exec"), namespace
            )
            choices = _completed_scaffold_choices()
            baseline, candidate = choices["TRIAL_SOURCE"]
            baseline.update(
                mapped_status="abstain",
                mapped_label=None,
                mapped_score=None,
                mapped_error=None,
            )
            candidate["mapped_pairing_key"] = None
            namespace.update(choices)
            trials = {
                record["trial_id"]: record
                for record in namespace["build_packet"]().canonical_records()
                if record["record_type"] == "trial"
            }
            self.assertEqual(trials["case-a-baseline"]["status"], "abstain")
            self.assertIsNone(trials["case-a-baseline"]["label"])
            self.assertIsNone(trials["case-a-baseline"]["error"])
            self.assertIsNone(trials["case-a-candidate"]["pairing_key"])

    def test_scaffold_rejects_placeholder_tokens_digests_and_mapping_stubs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            scaffold = Path(temp) / "scaffold"
            self.assertEqual(
                main(
                    [
                        "init",
                        "--judgment",
                        "categorical",
                        "--label",
                        "pass",
                        "--label",
                        "fail",
                        "--out",
                        str(scaffold),
                    ]
                ),
                0,
            )
            mapping_path = scaffold / "producer_mapping.py"
            namespace: dict[str, object] = {"__name__": "placeholder_under_test"}
            exec(
                compile(mapping_path.read_text(), str(mapping_path), "exec"), namespace
            )
            artifact_marker = namespace["PACKET"]["artifact_id"]
            fingerprint_marker = namespace["EVALUATIONS"]["baseline"][
                "evaluator_fingerprint_sha256"
            ]

            todo_identity = _completed_scaffold_choices()
            todo_identity["PACKET"]["artifact_id"] = artifact_marker.token
            namespace.update(todo_identity)
            with self.assertRaisesRegex(RuntimeError, "AUTHORING_INCOMPLETE"):
                namespace["build_packet"]()

            todo_fingerprint = _completed_scaffold_choices()
            todo_fingerprint["EVALUATIONS"]["baseline"][
                "evaluator_fingerprint_sha256"
            ] = sha256_bytes(fingerprint_marker.token.encode("utf-8"))
            namespace.update(todo_fingerprint)
            with self.assertRaisesRegex(RuntimeError, "AUTHORING_INCOMPLETE"):
                namespace["build_packet"]()

            non_callable = _completed_scaffold_choices()
            non_callable["STATUS_MAPPING"] = "reviewed"
            namespace.update(non_callable)
            with self.assertRaisesRegex(RuntimeError, "AUTHORING_INCOMPLETE"):
                namespace["build_packet"]()

            def not_implemented(source):
                del source
                raise RuntimeError("AUTHORING_INCOMPLETE: mapping not implemented")

            callable_stub = _completed_scaffold_choices()
            callable_stub["PAIRING_POLICY"] = not_implemented
            namespace.update(callable_stub)
            with self.assertRaisesRegex(RuntimeError, "AUTHORING_INCOMPLETE"):
                namespace["build_packet"]()

            incomplete_fields = _completed_scaffold_choices()
            incomplete_fields["STATUS_MAPPING"] = lambda source: {
                "status": source["mapped_status"],
                "label": source["mapped_label"],
                "score": source["mapped_score"],
            }
            namespace.update(incomplete_fields)
            with self.assertRaisesRegex(RuntimeError, "AUTHORING_INCOMPLETE"):
                namespace["build_packet"]()

    def test_known_sentinel_representations_fail_before_publication(self) -> None:
        from evalcanary.assurance.scaffold import create_scaffold

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_scaffold(
                judgment="categorical",
                labels=["pass", "fail"],
                output=root / "scaffold",
            )
            mapping_path = root / "scaffold" / "producer_mapping.py"
            namespace = {"__name__": "sentinel_representations_under_test"}
            exec(
                compile(mapping_path.read_text(), str(mapping_path), "exec"), namespace
            )
            markers = (
                namespace["EVALUATIONS"]["candidate"]["evaluator_fingerprint_sha256"],
                namespace["unresolved"]("new explicit fingerprint \u03bb"),
            )
            paths = (
                [
                    ("EVALUATIONS", role, field)
                    for role in ("baseline", "candidate")
                    for field in (
                        "evaluator_fingerprint_sha256",
                        "context_fingerprint_sha256",
                    )
                ]
                + [
                    ("EVALUATIONS", role, "component_values", "implementation", field)
                    for role in ("baseline", "candidate")
                    for field in ("identity", "sha256")
                ]
                + [
                    ("CASES", 0, "content_bytes"),
                    ("PACKET", "provenance", "nested"),
                    ("LABEL_SPACE", 2),
                    ("JUDGMENT_KIND",),
                ]
            )
            for marker in markers:
                forms = {
                    "typed": marker,
                    "text": marker.token,
                    "bytes": marker.token.encode("utf-8"),
                    "raw_digest": public_sha256_bytes(marker.token.encode("utf-8")),
                    "canonical_digest": public_sha256_value(marker.token),
                }
                for (form, value), path in product(forms.items(), paths):
                    with self.subTest(marker=marker.description, form=form, path=path):
                        choices = _completed_scaffold_choices()
                        choices["LABEL_SPACE"] = ["pass", "fail", "explicit-extra"]
                        choices["JUDGMENT_KIND"] = "categorical"
                        cursor = choices
                        for key in path[:-1]:
                            cursor = cursor[key]
                        cursor[path[-1]] = (
                            [{"tuple": (value,)}] if path[-1] == "nested" else value
                        )
                        namespace.update(choices)
                        with self.assertRaisesRegex(
                            RuntimeError, "AUTHORING_INCOMPLETE"
                        ):
                            namespace["write_outputs"](
                                contract=_small_contract(),
                                input_path=root
                                / f"{markers.index(marker)}-{form}-{paths.index(path)}.jsonl",
                                contract_path=root
                                / f"{markers.index(marker)}-{form}-{paths.index(path)}.json",
                            )
                        self.assertFalse(
                            (
                                root
                                / f"{markers.index(marker)}-{form}-{paths.index(path)}.jsonl"
                            ).exists()
                        )
                        self.assertFalse(
                            (
                                root
                                / f"{markers.index(marker)}-{form}-{paths.index(path)}.json"
                            ).exists()
                        )

    def test_sentinel_callback_results_and_detached_flags_fail_closed(self) -> None:
        from evalcanary.assurance.scaffold import create_scaffold

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_scaffold(
                judgment="categorical",
                labels=["pass", "fail"],
                output=root / "scaffold",
            )
            mapping_path = root / "scaffold" / "producer_mapping.py"
            namespace = {"__name__": "callback_sentinel_under_test"}
            exec(
                compile(mapping_path.read_text(), str(mapping_path), "exec"), namespace
            )
            marker = namespace["EVALUATIONS"]["candidate"][
                "evaluator_fingerprint_sha256"
            ]
            digest = public_sha256_value(marker.token)
            for mode in ("pairing", "status", "detached"):
                with self.subTest(mode=mode):
                    choices = _completed_scaffold_choices()
                    if mode == "pairing":
                        choices["PAIRING_POLICY"] = lambda source: digest
                    elif mode == "status":
                        choices["STATUS_MAPPING"] = lambda source: {
                            "status": "determinate",
                            "label": digest,
                            "score": None,
                            "error": None,
                        }
                    else:
                        choices["EVALUATIONS"]["candidate"][
                            "evaluator_fingerprint_sha256"
                        ] = digest
                    namespace.update(choices)
                    namespace.update(
                        DECLARATIONS=_completed_scaffold_choices(),
                        SEMANTIC_CHOICES_REVIEWED=True,
                        STATUS_MAPPING_REVIEWED=True,
                        PAIRING_POLICY_REVIEWED=True,
                    )
                    with self.assertRaisesRegex(RuntimeError, "AUTHORING_INCOMPLETE"):
                        namespace["write_outputs"](
                            contract=_small_contract(),
                            input_path=root / f"{mode}.jsonl",
                            contract_path=root / f"{mode}.json",
                        )
                    self.assertFalse((root / f"{mode}.jsonl").exists())
                    self.assertFalse((root / f"{mode}.json").exists())

    def test_scaffold_accepts_unrelated_strings_and_explicit_fingerprints(self) -> None:
        from evalcanary.assurance.scaffold import create_scaffold

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_scaffold(
                judgment="categorical",
                labels=["pass", "fail"],
                output=root / "scaffold",
            )
            mapping_path = root / "scaffold" / "producer_mapping.py"
            namespace = {"__name__": "valid_fingerprint_under_test"}
            exec(
                compile(mapping_path.read_text(), str(mapping_path), "exec"), namespace
            )
            for fingerprint in (
                "0123456789abcdef" * 4,
                public_sha256_bytes(b"exact caller-reviewed implementation bytes"),
                public_sha256_value({"implementation": "explicit", "revision": 2}),
            ):
                with self.subTest(fingerprint=fingerprint):
                    choices = _completed_scaffold_choices()
                    choices["PACKET"]["artifact_id"] = (
                        "TODO_EVALCANARY_SCAFFOLD:ordinary-user-identity"
                    )
                    choices["EVALUATIONS"]["candidate"][
                        "evaluator_fingerprint_sha256"
                    ] = fingerprint
                    namespace.update(choices)
                    input_path, contract_path = namespace["write_outputs"](
                        contract=_small_contract(),
                        input_path=root / f"{fingerprint}.jsonl",
                        contract_path=root / f"{fingerprint}.json",
                    )
                    artifact = load_artifact(input_path)
                    load_contract(contract_path, artifact)
                    candidate = next(
                        item
                        for item in artifact.header["evaluations"]
                        if item["role"] == "candidate"
                    )
                    self.assertEqual(
                        candidate["evaluator_fingerprint_sha256"], fingerprint
                    )
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(
                            main(
                                [
                                    "migrate",
                                    "--preflight",
                                    "--input",
                                    str(input_path),
                                    "--contract",
                                    str(contract_path),
                                ]
                            ),
                            0,
                        )

    def test_public_collection_declarations_cannot_hide_sentinels(self) -> None:
        from collections import UserList, deque

        from evalcanary.assurance.scaffold import create_scaffold

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_scaffold(
                judgment="categorical",
                labels=["pass", "fail"],
                output=root / "scaffold",
            )
            mapping_path = root / "scaffold" / "producer_mapping.py"
            namespace = {"__name__": "collection_sentinel_under_test"}
            exec(
                compile(mapping_path.read_text(), str(mapping_path), "exec"), namespace
            )
            marker = namespace["EVALUATIONS"]["candidate"][
                "evaluator_fingerprint_sha256"
            ]
            forms = (
                marker,
                marker.token,
                marker.token.encode("utf-8"),
                public_sha256_bytes(marker.token.encode("utf-8")),
                public_sha256_value(marker.token),
            )
            for index, value in enumerate(forms):
                for container in ("sequence", "mapping_keys", "key_view", "deque"):
                    with self.subTest(form=index, container=container):
                        choices = _completed_scaffold_choices()
                        if container == "sequence":
                            del choices["CASES"][0]["content_bytes"]
                            choices["CASES"][0]["content_sha256"] = value
                            choices["CASES"] = UserList(choices["CASES"])
                        else:
                            choices["CASES"][0]["tags"] = {
                                "mapping_keys": {value: None},
                                "key_view": {value: None}.keys(),
                                "deque": deque([value]),
                            }[container]
                        namespace.update(choices)
                        with self.assertRaisesRegex(
                            RuntimeError, "AUTHORING_INCOMPLETE"
                        ):
                            namespace["write_outputs"](
                                contract=_small_contract(),
                                input_path=root / f"{index}-{container}.jsonl",
                                contract_path=root / f"{index}-{container}.json",
                            )
                        self.assertFalse((root / f"{index}-{container}.jsonl").exists())
                        self.assertFalse((root / f"{index}-{container}.json").exists())

            choices = _completed_scaffold_choices()
            choices["CASES"][0]["tags"] = {"ordinary-tag": None}
            choices["CASES"] = UserList(choices["CASES"])
            choices["TRIAL_SOURCE"] = UserList(choices["TRIAL_SOURCE"])
            namespace.update(choices)
            input_path, contract_path = namespace["write_outputs"](
                contract=_small_contract(),
                input_path=root / "explicit.jsonl",
                contract_path=root / "explicit.json",
            )
            artifact = load_artifact(input_path)
            load_contract(contract_path, artifact)
            self.assertEqual(artifact.cases[0]["tags"], ["ordinary-tag"])

    def test_superficial_scaffold_sentinel_renaming_does_not_bypass_guard(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            scaffold = Path(temp) / "scaffold"
            self.assertEqual(
                main(
                    [
                        "init",
                        "--judgment",
                        "categorical",
                        "--label",
                        "pass",
                        "--label",
                        "fail",
                        "--out",
                        str(scaffold),
                    ]
                ),
                0,
            )
            mapping_path = scaffold / "producer_mapping.py"
            renamed = (
                mapping_path.read_text()
                .replace("_UnresolvedChoice", "_PendingChoice")
                .replace("unresolved", "pending")
            )
            namespace: dict[str, object] = {"__name__": "renamed_guard_under_test"}
            exec(compile(renamed, str(mapping_path), "exec"), namespace)
            namespace.update(
                SEMANTIC_CHOICES_REVIEWED=True,
                STATUS_MAPPING_REVIEWED=True,
                PAIRING_POLICY_REVIEWED=True,
            )
            with self.assertRaisesRegex(RuntimeError, "AUTHORING_INCOMPLETE"):
                namespace["build_packet"]()

    def test_repeated_authoring_uses_zero_new_mapping_logic_without_identity_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            scaffold = Path(temp) / "scaffold"
            self.assertEqual(
                main(
                    [
                        "init",
                        "--judgment",
                        "categorical",
                        "--label",
                        "pass",
                        "--label",
                        "fail",
                        "--out",
                        str(scaffold),
                    ]
                ),
                0,
            )
            mapping_path = scaffold / "producer_mapping.py"
            namespace: dict[str, object] = {"__name__": "repeat_under_test"}
            exec(
                compile(mapping_path.read_text(), str(mapping_path), "exec"), namespace
            )
            first_choices = _completed_scaffold_choices()
            namespace.update(first_choices)
            build_packet = namespace["build_packet"]
            first = build_packet()

            second_choices = deepcopy(first_choices)
            second_choices["PACKET"]["artifact_id"] = "completed-scaffold-u2"
            candidate = second_choices["EVALUATIONS"]["candidate"]
            candidate["evaluation_id"] = "eval-candidate-u2"
            candidate["evaluator_version"] = "2"
            candidate["evaluator_fingerprint_sha256"] = sha256_bytes(
                b"evaluator-candidate-u2"
            )
            namespace.update(second_choices)
            second = build_packet()

            first_records = first.canonical_records()
            second_records = second.canonical_records()
            first_evaluations = {
                item["role"]: item for item in first_records[0]["evaluations"]
            }
            second_evaluations = {
                item["role"]: item for item in second_records[0]["evaluations"]
            }
            self.assertEqual(
                first_evaluations["baseline"], second_evaluations["baseline"]
            )
            first_candidate = deepcopy(first_evaluations["candidate"])
            second_candidate = deepcopy(second_evaluations["candidate"])
            for field in (
                "evaluation_id",
                "evaluator_version",
                "evaluator_fingerprint_sha256",
            ):
                first_candidate.pop(field)
                second_candidate.pop(field)
            self.assertEqual(first_candidate, second_candidate)
            self.assertIs(build_packet, namespace["build_packet"])

    def test_scaffold_executes_the_documented_golden_authoring_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scaffold = root / "scaffold"
            self.assertEqual(
                main(
                    [
                        "init",
                        "--judgment",
                        "categorical",
                        "--label",
                        "pass",
                        "--label",
                        "fail",
                        "--out",
                        str(scaffold),
                    ]
                ),
                0,
            )
            mapping_path = scaffold / "producer_mapping.py"
            namespace: dict[str, object] = {"__name__": "scaffold_under_test"}
            exec(
                compile(mapping_path.read_text(), str(mapping_path), "exec"), namespace
            )
            namespace.update(_completed_scaffold_choices())
            input_path, contract_path = namespace["write_outputs"](
                contract=_small_contract(),
                input_path=root / "evaluator-assurance.jsonl",
                contract_path=root / "evaluator-contract.json",
            )
            artifact = load_artifact(input_path)
            load_contract(contract_path, artifact)

            for arguments in (
                [
                    "migrate",
                    "--preflight",
                    "--input",
                    str(input_path),
                    "--contract",
                    str(contract_path),
                ],
                [
                    "migrate",
                    "--input",
                    str(input_path),
                    "--contract",
                    str(contract_path),
                    "--out",
                    str(root / "report"),
                ],
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(main(arguments), 0)
            self.assertEqual(
                {item.name for item in (root / "report").iterdir()},
                {
                    "report.json",
                    "report.md",
                    "report.html",
                    "review-queue.json",
                    "review-queue.md",
                },
            )

    def test_init_refuses_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "existing"
            output.mkdir()
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = main(
                    [
                        "init",
                        "--judgment",
                        "categorical",
                        "--label",
                        "pass",
                        "--label",
                        "fail",
                        "--out",
                        str(output),
                    ]
                )
            self.assertEqual(code, 3)
            self.assertIn("must not already exist", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
