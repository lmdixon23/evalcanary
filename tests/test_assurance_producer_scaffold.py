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


def _small_packet(case_order: tuple[str, ...]) -> AssurancePacket:
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
    )
    for case_id in case_order:
        packet.add_case(case_id, content_bytes=f"content:{case_id}".encode())
    for case_id in reversed(case_order):
        for role in ("candidate", "baseline"):
            packet.add_trial(
                case_id=case_id,
                evaluation_id=f"eval-{role}",
                trial_id=f"{case_id}-{role}",
                source_order=0,
                pairing_key="pair-0",
                status="determinate",
                label="pass",
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


class AssuranceProducerScaffoldTests(unittest.TestCase):
    def test_exact_hash_helpers_and_explicit_component_values(self) -> None:
        self.assertEqual(sha256_value({"b": 2, "a": 1}), sha256_value({"a": 1, "b": 2}))
        self.assertNotEqual(sha256_bytes(b"exact-a"), sha256_bytes(b"exact-b"))
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
                "unexpected_component": component_value(
                    "present", sha256="1" * 64
                ),
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
        self.assertIn(
            "duplicate_supplied_or_not_applicable=[implementation]", message
        )
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
        self.assertEqual(
            packet.evaluation_ids_by_role["baseline"], "eval-baseline"
        )

    def test_authoring_bridge_adds_no_mandatory_runtime_dependency(self) -> None:
        project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
        self.assertEqual(project["project"]["dependencies"], [])

    def test_equivalent_addition_orders_are_byte_identical(self) -> None:
        first = _small_packet(("case-b", "case-a"))
        second = _small_packet(("case-a", "case-b"))
        self.assertEqual(first.canonical_bytes(), second.canonical_bytes())

    def test_atomic_write_uses_normative_validator_and_retains_explicit_identity(self) -> None:
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

    def test_invalid_references_and_inventories_fail_before_final_artifact(self) -> None:
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
            incomplete.document({"parser": "context", "aggregation_policy": "evaluator"})

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
        self.assertTrue({"determinate", "abstain", "indeterminate", "error"} <= statuses)
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
                self.assertIn("TODO_REQUIRED", mapping)
                self.assertIn("PARSER_OWNER = None", mapping)
                self.assertIn("STATUS_MAPPING = None", mapping)
                self.assertIn("component_requirements(ownership)", mapping)
                self.assertIn("complete_components(", mapping)
                self.assertIn('role="baseline"', mapping)
                self.assertIn('role="candidate"', mapping)
                self.assertIn("packet.add_case(", mapping)
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
                self.assertIn("contract.write(contract_path, artifact=input_path)", readme)
                self.assertIn("explicit keyword-only `Rule`", readme)
                self.assertIn("evalcanary migrate --preflight", readme)
                self.assertIn("evalcanary migrate --input", readme)
                self.assertFalse((output / "evaluator-assurance.jsonl").exists())

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
            exec(compile(mapping_path.read_text(), str(mapping_path), "exec"), namespace)
            namespace.update(
                {
                    "PARSER_OWNER": "context",
                    "AGGREGATION_POLICY_OWNER": "evaluator",
                    "STATUS_MAPPING": {"pass": "determinate", "fail": "determinate"},
                    "PAIRING_POLICY": "explicit-pairing-key",
                    "CONTEXT_DIFFERENCES": [],
                    "ANCHOR_INTERPRETATION": "no-anchors-in-synthetic-example",
                    "CONFIRM_UNLISTED_NOT_APPLICABLE": True,
                }
            )
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
