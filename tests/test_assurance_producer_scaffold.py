from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from pathlib import Path

from scripts.generate_assurance_examples import example_evaluation, example_packets

from evalcanary.assurance.producer import (
    AssurancePacket,
    component_value,
    sha256_bytes,
    sha256_value,
)
from evalcanary.assurance.schema import load_artifact
from evalcanary.cli import main
from evalcanary.errors import InputValidationError

EXAMPLE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "evalcanary"
    / "examples"
    / "assurance"
)


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
        with self.assertRaisesRegex(InputValidationError, "explicitly supply"):
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
                mapping = (output / "producer_mapping.py").read_text()
                self.assertIn("TODO_REQUIRED", mapping)
                self.assertIn("PARSER_OWNER = None", mapping)
                self.assertIn("STATUS_MAPPING = None", mapping)
                self.assertFalse((output / "evaluator-assurance.jsonl").exists())

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
