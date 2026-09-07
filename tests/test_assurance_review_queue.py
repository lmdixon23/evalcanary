from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from tests.assurance_helpers import (
    clone_records,
    contract,
    refresh_manifest,
    rule,
    write_json,
    write_records,
)

from evalcanary.assurance.engine import build_report
from evalcanary.assurance.numeric import canonical_json_bytes
from evalcanary.assurance.producer import component_value
from evalcanary.assurance.renderers import write_report_bundle
from evalcanary.assurance.review_queue import (
    build_review_queue,
    queue_view_model,
    resolve_pointer,
    review_queue_markdown,
    verify_review_queue_binding,
)
from evalcanary.assurance.schema import Limits, load_artifact, load_contract
from evalcanary.errors import InputValidationError


class ReviewQueueTests(unittest.TestCase):
    def _report(self, root: Path, *, with_contract: bool = True) -> dict[str, object]:
        records = clone_records(
            numeric=True, with_anchors=True, relation="swapped_preference"
        )
        case_one_candidate = next(
            item
            for item in records
            if item.get("record_type") == "trial"
            and item.get("case_id") == "case-1"
            and item.get("evaluation_id") == "eval-candidate"
        )
        case_one_candidate["label"] = "fail"
        case_one_candidate["score"] = 3
        case_two_candidate = next(
            item
            for item in records
            if item.get("record_type") == "trial"
            and item.get("case_id") == "case-2"
            and item.get("evaluation_id") == "eval-candidate"
        )
        case_two_candidate.update(
            {
                "status": "error",
                "label": None,
                "score": None,
                "reason": "PRIVATE_REASON_CANARY",
                "details": {"private": "PRIVATE_DETAILS_CANARY"},
                "error": {
                    "error_class": "ParserError",
                    "message": "PRIVATE_ERROR_CANARY",
                },
            }
        )
        refresh_manifest(records)
        input_path = write_records(root / "input.jsonl", records)
        artifact = load_artifact(input_path)
        if not with_contract:
            return build_report(artifact)
        contract_path = write_json(
            root / "contract.json",
            contract(
                rule(
                    "critical_regression_count",
                    scope="critical_group",
                    scope_id="critical-1",
                    parameters={"from_label": "pass", "to_label": "fail"},
                    operator="lte",
                    threshold=1,
                )
            ),
        )
        return build_report(artifact, load_contract(contract_path, artifact))

    def _role_aware_report(self, root: Path) -> dict[str, object]:
        records = clone_records(relation="same_label")
        baseline = next(
            item
            for item in records
            if item.get("record_type") == "trial"
            and item.get("case_id") == "case-2"
            and item.get("evaluation_id") == "eval-baseline"
        )
        baseline.update(
            {
                "status": "abstain",
                "label": None,
                "score": None,
                "error": None,
            }
        )
        baseline["provenance"]["evidence_policy"] = component_value(
            "present", identity="single_order_policy_exclusion"
        )
        candidate = next(
            item
            for item in records
            if item.get("record_type") == "trial"
            and item.get("case_id") == "case-2"
            and item.get("evaluation_id") == "eval-candidate"
        )
        candidate["label"] = "fail"
        refresh_manifest(records)
        artifact = load_artifact(write_records(root / "role-aware.jsonl", records))
        return build_report(artifact)

    def test_queue_is_deterministic_bound_and_report_status_invariant(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._report(Path(temp))
        original_bytes = canonical_json_bytes(report)
        original_status = report["report_status"]
        first = build_review_queue(report)
        second = build_review_queue(deepcopy(report))
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
        self.assertEqual(canonical_json_bytes(report), original_bytes)
        self.assertEqual(report["report_status"], original_status)
        verify_review_queue_binding(report, first)
        self.assertEqual(
            first["source_report_sha256"],
            hashlib.sha256(original_bytes + b"\n").hexdigest(),
        )
        ids = [item["queue_item_id"] for item in first["items"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [item["queue_item_id"] for item in second["items"]])
        for item in first["items"]:
            for pointer in item["source_pointers"]:
                resolve_pointer(report, pointer)

    def test_reason_semantics_privacy_and_projection_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._report(Path(temp))
        queue = build_review_queue(report)
        reasons = [item["reason_code"] for item in queue["items"]]
        self.assertIn("CRITICAL_LABEL_REGRESSION", reasons)
        self.assertIn("NEW_ERROR", reasons)
        self.assertIn("LABEL_CHANGED", reasons)
        self.assertIn("SCORE_CHANGED", reasons)
        self.assertIn("INVARIANCE_VIOLATED", reasons)
        self.assertIn("INVARIANCE_NOT_EVALUABLE", reasons)
        critical = next(
            item
            for item in queue["items"]
            if item["reason_code"] == "CRITICAL_LABEL_REGRESSION"
        )
        self.assertEqual(critical["contract_result"], "satisfied")
        self.assertEqual(critical["facts"]["from_label"], "pass")
        self.assertEqual(critical["facts"]["to_label"], "fail")
        serialized = canonical_json_bytes(queue)
        for canary in (
            b"PRIVATE_REASON_CANARY",
            b"PRIVATE_DETAILS_CANARY",
            b"PRIVATE_ERROR_CANARY",
            b"secret reason",
            b"provider-secret",
            b"private message",
        ):
            self.assertNotIn(canary, serialized)
        ids = [item["queue_item_id"] for item in queue["items"]]
        small = queue_view_model(queue, per_reason_limit=1)
        large = queue_view_model(queue, per_reason_limit=100)
        self.assertEqual(ids, [item["queue_item_id"] for item in queue["items"]])
        self.assertTrue(
            all(group["displayed_count"] <= 1 for group in small["groups"])
        )
        self.assertEqual(
            sum(group["displayed_count"] for group in large["groups"]),
            queue["item_count"],
        )

    def test_critical_group_membership_alone_does_not_infer_regression(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._report(Path(temp), with_contract=False)
        reasons = [item["reason_code"] for item in build_review_queue(report)["items"]]
        self.assertIn("LABEL_CHANGED", reasons)
        self.assertNotIn("CRITICAL_LABEL_REGRESSION", reasons)

    def test_binding_rejects_hash_identity_and_pointer_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._report(Path(temp))
        queue = build_review_queue(report)
        for key, replacement in (
            ("source_report_sha256", "0" * 64),
            ("source_report_id", "different-report"),
        ):
            changed = deepcopy(queue)
            changed[key] = replacement
            with self.assertRaises(InputValidationError):
                verify_review_queue_binding(report, changed)
        changed = deepcopy(queue)
        changed["items"][0]["source_pointers"] = ["/does/not/exist"]
        with self.assertRaises(InputValidationError):
            verify_review_queue_binding(report, changed)

    def test_role_aware_projection_orders_candidate_before_policy_exclusions(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._role_aware_report(Path(temp))
        queue = build_review_queue(report)
        self.assertEqual(
            queue["invariance_summary"],
            {
                "baseline": {
                    "satisfied": 0,
                    "violated": 0,
                    "not_evaluable": 1,
                    "declared_policy_not_evaluable": 1,
                },
                "candidate": {
                    "satisfied": 0,
                    "violated": 1,
                    "not_evaluable": 0,
                    "declared_policy_not_evaluable": 0,
                },
            },
        )
        markdown = review_queue_markdown(queue)
        candidate_position = markdown.index("Candidate invariance violations")
        baseline_position = markdown.index("Expected baseline policy exclusions")
        self.assertLess(candidate_position, baseline_position)
        self.assertIn(
            "expected not-evaluable consequences of the supplied baseline evidence policy",
            markdown,
        )
        self.assertIn("presented separately from candidate findings", markdown)

    def test_status_transition_is_neutral_grouped_and_machine_exhaustive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._role_aware_report(Path(temp))
        queue = build_review_queue(report)
        transitions = [
            item
            for item in queue["items"]
            if item["reason_code"] == "STATUS_TRANSITION"
        ]
        self.assertEqual(len(transitions), 1)
        transition = transitions[0]
        self.assertEqual(transition["role"], "candidate")
        self.assertEqual(transition["facts"]["baseline_status"], "abstain")
        self.assertEqual(transition["facts"]["candidate_status"], "determinate")
        self.assertEqual(transition["facts"]["case_id"], "case-2")
        self.assertEqual(
            transition["facts"]["baseline_trial_id"], "case-2-baseline-0"
        )
        self.assertEqual(
            transition["facts"]["candidate_trial_id"], "case-2-candidate-0"
        )
        for pointer in transition["source_pointers"]:
            resolve_pointer(report, pointer)
        serialized = canonical_json_bytes(transition).decode("utf-8").lower()
        for directional_claim in ("better", "worse", "improvement", "regression"):
            self.assertNotIn(directional_claim, serialized)
        markdown = review_queue_markdown(queue)
        self.assertIn("Neutral status transitions (grouped)", markdown)
        self.assertIn("| candidate | `abstain` | `determinate` | 1 |", markdown)
        self.assertNotIn(transition["subject_id"], markdown)
        self.assertEqual(queue["item_count"], len(queue["items"]))
        self.assertNotIn("OTHER_OBSERVED_CHANGE", queue["counts_by_reason"])

    def test_unique_subject_workload_deduplicates_overlapping_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._role_aware_report(Path(temp))
        queue = build_review_queue(report)
        self.assertEqual(
            queue["workload_summary"],
            {
                "items": 3,
                "unique_cases": 1,
                "unique_trials": 1,
                "unique_invariance_groups": 1,
                "unique_rules": 0,
                "unique_anchors": 0,
                "overall_unique_logical_subjects": 2,
                "logical_subject_identity": "subject_type+subject_id",
            },
        )
        view = queue_view_model(queue)
        policy_group = next(
            group
            for group in view["groups"]
            if group["heading"] == "Expected baseline policy exclusions"
        )
        self.assertEqual(policy_group["projection_mode"], "aggregate_only")
        self.assertEqual(policy_group["suppressed_item_count"], 1)
        verify_review_queue_binding(report, queue)

    def test_migrate_packet_contains_exhaustive_json_and_bounded_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self._report(root)
            output = root / "out"
            write_report_bundle(report, output, limits=Limits())
            report_bytes = (output / "report.json").read_bytes()
            queue_bytes = (output / "review-queue.json").read_bytes()
            queue = json.loads(queue_bytes, parse_float=Decimal)
            self.assertEqual(
                queue["source_report_sha256"], hashlib.sha256(report_bytes).hexdigest()
            )
            self.assertEqual(queue["item_count"], len(queue["items"]))
            markdown = (output / "review-queue.md").read_text(encoding="utf-8")
            self.assertIn("Priority is review ordering only", markdown)
            self.assertIn("displayed:", markdown)
            self.assertIn("omitted:", markdown)
            self.assertLess(len(markdown), len(queue_bytes))


if __name__ == "__main__":
    unittest.main()
