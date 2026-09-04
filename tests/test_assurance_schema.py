from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from tests.assurance_helpers import (
    clone_records,
    contract,
    records,
    refresh_manifest,
    rule,
    write_json,
    write_records,
)

from evalcanary.assurance.constants import LIMIT_CEILINGS, LIMIT_DEFAULTS
from evalcanary.assurance.numeric import canonical_json_text
from evalcanary.assurance.schema import Limits, load_artifact, load_contract
from evalcanary.errors import InputValidationError, PolicyConfigurationError


class AssuranceSchemaTests(unittest.TestCase):
    def _load(self, items: list[dict[str, object]]) -> object:
        with tempfile.TemporaryDirectory() as temp:
            return load_artifact(write_records(Path(temp) / "input.jsonl", items))

    def test_complete_valid_artifact_loads(self) -> None:
        artifact = self._load(records(with_anchors=True))
        self.assertEqual(len(artifact.cases), 2)
        self.assertEqual(len(artifact.trials), 4)
        self.assertEqual(artifact.header["component_ownership"]["parser"], "context")

    def test_unknown_core_field_and_record_type_fail_closed(self) -> None:
        items = clone_records()
        items[0]["surprise"] = True
        with self.assertRaisesRegex(InputValidationError, "Unknown core field"):
            self._load(items)
        items = clone_records()
        items.append({"record_type": "plugin"})
        with self.assertRaisesRegex(InputValidationError, "Unknown or duplicate record type"):
            self._load(items)

    def test_duplicate_json_keys_bom_blank_and_non_utf8_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            good = canonical_json_text(records()[0])
            for name, data, message in (
                ("duplicate", good.replace('"artifact_id":"artifact-1"', '"artifact_id":"artifact-1","artifact_id":"two"').encode(), "Duplicate JSON"),
                ("bom", b"\xef\xbb\xbf" + good.encode(), "BOM"),
                ("blank", (good + "\n\n").encode(), "Blank lines"),
                ("utf8", b"{\xff}\n", "UTF-8"),
            ):
                path = root / f"{name}.jsonl"
                path.write_bytes(data)
                with self.subTest(name=name), self.assertRaisesRegex(
                    InputValidationError, message
                ):
                    load_artifact(path)

    def test_header_must_be_first_and_unique(self) -> None:
        items = clone_records()
        items[0], items[1] = items[1], items[0]
        with self.assertRaisesRegex(InputValidationError, "first record"):
            self._load(items)
        items = clone_records()
        items.append(items[0].copy())
        with self.assertRaisesRegex(InputValidationError, "duplicate record type"):
            self._load(items)

    def test_complete_component_inventory_and_declared_ownership(self) -> None:
        items = clone_records()
        del items[0]["evaluations"][0]["context_components"]["runtime"]
        with self.assertRaisesRegex(InputValidationError, "inventory"):
            self._load(items)
        items = clone_records()
        parser = items[0]["evaluations"][0]["context_components"].pop("parser")
        items[0]["evaluations"][0]["evaluator_components"]["parser"] = parser
        with self.assertRaisesRegex(InputValidationError, "inventory"):
            self._load(items)

    def test_manifest_count_positions_hash_memberships_and_content_hash(self) -> None:
        mutations = []
        first = clone_records()
        first[0]["corpus"]["case_count"] = 3
        mutations.append((first, "case_count"))
        second = clone_records()
        cases = [item for item in second if item["record_type"] == "case"]
        cases[1]["manifest_position"] = 2
        refresh_manifest(second)
        mutations.append((second, "positions"))
        third = clone_records()
        third[0]["corpus"]["manifest_sha256"] = "f" * 64
        mutations.append((third, "manifest SHA"))
        fourth = clone_records()
        case = next(item for item in fourth if item["record_type"] == "case")
        case["critical_group_ids"] = ["missing-group"]
        refresh_manifest(fourth)
        mutations.append((fourth, "undeclared group"))
        fifth = clone_records()
        case = next(item for item in fifth if item["record_type"] == "case")
        case["content_sha256"] = None
        mutations.append((fifth, "content_sha256"))
        for items, message in mutations:
            with self.subTest(message=message), self.assertRaisesRegex(
                InputValidationError, message
            ):
                self._load(items)

    def test_manifest_excludes_display_tags_rationale_trials_and_anchors(self) -> None:
        items = clone_records(with_anchors=True)
        case = next(item for item in items if item["record_type"] == "case")
        case["display_label"] = "review label"
        case["tags"] = ["review-tag"]
        critical = next(
            item for item in items if item["record_type"] == "critical_group"
        )
        critical["rationale"] = "updated non-identity rationale"
        trial = next(item for item in items if item["record_type"] == "trial")
        trial["reason"] = "updated non-identity trial reason"
        anchor = next(item for item in items if item["record_type"] == "anchor")
        anchor["reason"] = "updated non-identity anchor reason"
        self._load(items)

        critical["title"] = "identity-bearing declaration title"
        with self.assertRaisesRegex(InputValidationError, "manifest SHA"):
            self._load(items)

    def test_identity_bearing_manifest_text_must_be_nfc(self) -> None:
        items = clone_records()
        critical = next(
            item for item in items if item["record_type"] == "critical_group"
        )
        critical["title"] = "Cafe\u0301"
        refresh_manifest(items)
        with self.assertRaisesRegex(InputValidationError, "NFC-normalized"):
            self._load(items)

    def test_status_label_score_and_error_combinations(self) -> None:
        items = clone_records()
        trial = next(item for item in items if item["record_type"] == "trial")
        trial["status"] = "abstain"
        trial["label"] = "pass"
        with self.assertRaisesRegex(InputValidationError, "label must be null"):
            self._load(items)
        items = clone_records()
        trial = next(item for item in items if item["record_type"] == "trial")
        trial["status"] = "error"
        trial["label"] = None
        trial["error"] = None
        with self.assertRaisesRegex(InputValidationError, "must be an object"):
            self._load(items)
        items = clone_records()
        trial = next(item for item in items if item["record_type"] == "trial")
        trial["score"] = 1
        with self.assertRaisesRegex(InputValidationError, "cannot carry a score"):
            self._load(items)
        items = clone_records(numeric=True)
        trial = next(item for item in items if item["record_type"] == "trial")
        trial["score"] = 11
        with self.assertRaisesRegex(InputValidationError, "outside the declared domain"):
            self._load(items)

    def test_trial_identity_source_order_and_pairing_rules(self) -> None:
        items = clone_records()
        trials = [item for item in items if item["record_type"] == "trial"]
        trials[1]["trial_id"] = trials[0]["trial_id"]
        with self.assertRaisesRegex(InputValidationError, "Duplicate trial"):
            self._load(items)
        items = clone_records()
        baseline = next(item for item in items if item.get("trial_id") == "case-1-baseline-0")
        extra = baseline.copy()
        extra["trial_id"] = "case-1-baseline-2"
        extra["source_order"] = 2
        extra["pairing_key"] = "pair-2"
        items.append(extra)
        with self.assertRaisesRegex(InputValidationError, "gap-free"):
            self._load(items)
        items = clone_records()
        baseline = next(item for item in items if item.get("trial_id") == "case-1-baseline-0")
        extra = baseline.copy()
        extra["trial_id"] = "case-1-baseline-1"
        extra["source_order"] = 1
        items.append(extra)
        with self.assertRaisesRegex(InputValidationError, "pairing_key"):
            self._load(items)

    def test_exact_context_exception_shape_and_values(self) -> None:
        items = clone_records()
        evaluations = items[0]["evaluations"]
        first = evaluations[0]["context_components"]["runtime"]
        second = {"presence": "present", "identity": "python-3.14", "sha256": None}
        evaluations[1]["context_components"]["runtime"] = second
        items[0]["allowed_context_differences"] = [
            {
                "component": "runtime",
                "expected_baseline_component_value": first,
                "expected_candidate_component_value": second,
                "rationale": "reviewed exact drift",
                "reviewer_id": "reviewer-1",
                "disposition": "not_isolated_review_required",
            }
        ]
        artifact = self._load(items)
        self.assertEqual(len(artifact.header["allowed_context_differences"]), 1)
        items[0]["allowed_context_differences"][0]["expected_candidate_component_value"] = first
        with self.assertRaisesRegex(InputValidationError, "must differ"):
            self._load(items)

    def test_anchor_identity_lineage_and_aggregation(self) -> None:
        items = clone_records(with_anchors=True)
        anchor_set = next(item for item in items if item["record_type"] == "anchor_set")
        anchor_set["aggregation_method"] = "majority"
        raw = next(item for item in items if item["record_type"] == "anchor")
        aggregate = raw.copy()
        aggregate.update(
            {
                "anchor_id": "aggregate-1",
                "annotation_id": "aggregate-annotation",
                "kind": "aggregate",
                "annotator_id": None,
                "aggregation_inputs": [raw["anchor_id"]],
            }
        )
        items.append(aggregate)
        artifact = self._load(items)
        self.assertEqual(len(artifact.anchors), 3)
        aggregate["aggregation_inputs"] = ["unknown-anchor"]
        with self.assertRaisesRegex(InputValidationError, "retained raw anchor"):
            self._load(items)

        aggregate["aggregation_inputs"] = [raw["anchor_id"], raw["anchor_id"]]
        with self.assertRaisesRegex(InputValidationError, "must be unique"):
            self._load(items)

    def test_anchor_error_status_fails_closed_without_an_error_field(self) -> None:
        items = clone_records(with_anchors=True)
        anchor = next(item for item in items if item["record_type"] == "anchor")
        anchor.update({"status": "error", "label": None})
        with self.assertRaisesRegex(InputValidationError, "cannot be represented"):
            self._load(items)

    def test_depth_bombs_and_bounded_details_fail_without_echoing_content(self) -> None:
        items = clone_records()
        nested: dict[str, object] = {}
        cursor = nested
        for _ in range(20):
            child: dict[str, object] = {}
            cursor["next"] = child
            cursor = child
        items[0]["extensions"] = {"fixture.example": nested}
        with self.assertRaisesRegex(InputValidationError, "nesting_depth"):
            self._load(items)

        items = clone_records()
        private_canary = "PRIVATE_DETAILS_CANARY" * 20
        trial = next(item for item in items if item["record_type"] == "trial")
        trial["details"] = {"note": private_canary}
        values = dict(LIMIT_DEFAULTS)
        values["details_bytes"] = 8
        with tempfile.TemporaryDirectory() as temp:
            path = write_records(Path(temp) / "input.jsonl", items)
            with self.assertRaises(InputValidationError) as raised:
                load_artifact(path, limits=Limits(values=values))
        self.assertNotIn(private_canary, str(raised.exception))


class AssuranceContractSchemaTests(unittest.TestCase):
    def _load(self, document: dict[str, object]) -> object:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = load_artifact(write_records(root / "input.jsonl", records()))
            return load_contract(write_json(root / "contract.json", document), artifact)

    def test_contract_rejects_unknown_metric_scope_and_extra_parameters(self) -> None:
        unknown = contract(rule("corpus_equal"))
        unknown["rules"][0]["metric"] = "future_metric"
        with self.assertRaisesRegex(InputValidationError, "unknown enum"):
            self._load(unknown)

        wrong_scope = contract(rule("corpus_equal", scope="critical_group", scope_id="critical-1"))
        with self.assertRaisesRegex(PolicyConfigurationError, "unsupported scope"):
            self._load(wrong_scope)

        extra = contract(rule("determinate_coverage", parameters={"role": "candidate"}))
        extra["rules"][0]["parameters"]["extra"] = True
        with self.assertRaisesRegex(InputValidationError, "Unknown core field"):
            self._load(extra)

    def test_contract_rejects_bad_thresholds_duplicate_ids_and_severity_policy(
        self,
    ) -> None:
        noninteger = contract(
            rule(
                "status_count",
                parameters={"role": "candidate", "status": "error"},
                threshold=Decimal("0.5"),
            )
        )
        with self.assertRaisesRegex(PolicyConfigurationError, "non-negative integer"):
            self._load(noninteger)

        coverage = contract(
            rule(
                "determinate_coverage",
                parameters={"role": "candidate"},
                threshold=Decimal("1.0001"),
            )
        )
        with self.assertRaisesRegex(PolicyConfigurationError, r"\[0,1\]"):
            self._load(coverage)

        boolean = contract(rule("corpus_equal"))
        boolean["rules"][0]["threshold"] = 1
        with self.assertRaisesRegex(PolicyConfigurationError, "threshold=null"):
            self._load(boolean)

        duplicate = contract(rule("corpus_equal"), rule("context_isolated"))
        duplicate["rules"][1]["rule_id"] = duplicate["rules"][0]["rule_id"]
        with self.assertRaisesRegex(PolicyConfigurationError, "unique"):
            self._load(duplicate)

        info = contract(
            rule(
                "corpus_equal",
                severity="info",
                missing_evidence="review",
            )
        )
        with self.assertRaisesRegex(PolicyConfigurationError, "Info rule"):
            self._load(info)


class LimitPolicyBoundaryTests(unittest.TestCase):
    """Large ceilings use the parser's comparison abstraction, avoiding hostile allocation."""

    def test_every_locked_default_boundary_minus_equal_plus(self) -> None:
        limits = Limits()
        self.assertEqual(set(limits.values), set(LIMIT_DEFAULTS))
        self.assertEqual(set(LIMIT_DEFAULTS), set(LIMIT_CEILINGS))
        for name, boundary in LIMIT_DEFAULTS.items():
            with self.subTest(name=name, point="minus"):
                limits.enforce(name, boundary - 1, field_path="test")
            with self.subTest(name=name, point="equal"):
                limits.enforce(name, boundary, field_path="test")
            with self.subTest(name=name, point="plus"), self.assertRaisesRegex(
                InputValidationError, name
            ):
                limits.enforce(name, boundary + 1, field_path="test")

    def test_override_cannot_exceed_ceiling_or_raise_nonoverridable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "limits.json"
            path.write_text('{"limits":{"cases":50000}}', encoding="utf-8")
            limits = Limits.from_path(path)
            self.assertEqual(limits.get("cases"), 50_000)
            self.assertIsNotNone(limits.source_sha256)
            path.write_text('{"limits":{"cases":50001}}', encoding="utf-8")
            with self.assertRaisesRegex(InputValidationError, "ceiling"):
                Limits.from_path(path)
            path.write_text('{"limits":{"nesting_depth":13}}', encoding="utf-8")
            with self.assertRaisesRegex(InputValidationError, "cannot be raised"):
                Limits.from_path(path)


if __name__ == "__main__":
    unittest.main()
