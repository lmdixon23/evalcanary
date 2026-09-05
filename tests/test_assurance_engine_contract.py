from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.assurance_helpers import (
    clone_records,
    component,
    contract,
    pure_numeric_records,
    rule,
    write_json,
    write_records,
)

from evalcanary.assurance.constants import METRICS, PROVENANCE_FIELDS
from evalcanary.assurance.engine import build_report, exit_code_for_report
from evalcanary.assurance.schema import load_artifact, load_contract
from evalcanary.errors import InputValidationError, PolicyConfigurationError


class AssuranceEngineTests(unittest.TestCase):
    def _report(
        self,
        items: list[dict[str, Any]],
        contract_document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = load_artifact(write_records(root / "input.jsonl", items))
            loaded_contract = (
                None
                if contract_document is None
                else load_contract(
                    write_json(root / "contract.json", contract_document), artifact
                )
            )
            return build_report(artifact, loaded_contract)

    def test_default_valid_report_is_isolated_and_contract_not_configured(self) -> None:
        report = self._report(clone_records())
        self.assertEqual(report["evidence_status"], "VALID")
        self.assertEqual(report["isolation_status"], "ISOLATED")
        self.assertEqual(report["contract_status"], "NOT_CONFIGURED")
        self.assertEqual(report["report_status"], "CONTRACT_NOT_CONFIGURED")
        self.assertEqual(exit_code_for_report(report), 0)

    def test_missing_evaluator_side_is_not_comparable(self) -> None:
        items = clone_records()
        items[:] = [
            item
            for item in items
            if not (
                item.get("record_type") == "trial"
                and item.get("case_id") == "case-2"
                and item.get("evaluation_id") == "eval-candidate"
            )
        ]
        report = self._report(items)
        self.assertEqual(report["evidence_status"], "NOT_COMPARABLE")
        self.assertEqual(report["missing_evaluator_side_case_ids"], ["case-2"])
        self.assertEqual(exit_code_for_report(report), 3)

    def test_exact_context_exception_requires_review_and_mismatch_is_not_comparable(
        self,
    ) -> None:
        items = clone_records()
        first = items[0]["evaluations"][0]["context_components"]["runtime"]
        second = component("python-3.14")
        items[0]["evaluations"][1]["context_components"]["runtime"] = second
        items[0]["allowed_context_differences"] = [
            {
                "component": "runtime",
                "expected_baseline_component_value": first,
                "expected_candidate_component_value": second,
                "rationale": "Exact reviewed difference.",
                "reviewer_id": "reviewer-1",
                "disposition": "not_isolated_review_required",
            }
        ]
        report = self._report(items)
        self.assertEqual(report["isolation_status"], "NOT_ISOLATED")
        self.assertEqual(report["report_status"], "REVIEW_REQUIRED")
        self.assertEqual(exit_code_for_report(report), 4)

        items[0]["evaluations"][1]["context_components"]["runtime"] = component(
            "python-3.15"
        )
        report = self._report(items)
        self.assertEqual(report["evidence_status"], "NOT_COMPARABLE")
        self.assertEqual(exit_code_for_report(report), 3)

    def test_repeat_diagnostics_keep_status_label_and_score_instability_separate(
        self,
    ) -> None:
        items = clone_records(numeric=True)
        baseline = next(
            item
            for item in items
            if item.get("trial_id") == "case-1-baseline-0"
        )
        baseline_repeat = dict(baseline)
        baseline_repeat.update(
            {
                "trial_id": "case-1-baseline-1",
                "source_order": 1,
                "pairing_key": "pair-repeat",
                "label": "fail",
                "score": 3,
            }
        )
        candidate = next(
            item
            for item in items
            if item.get("trial_id") == "case-1-candidate-0"
        )
        candidate_repeat = dict(candidate)
        candidate_repeat.update(
            {
                "trial_id": "case-1-candidate-1",
                "source_order": 1,
                "pairing_key": "pair-repeat",
                "status": "abstain",
                "label": None,
                "score": None,
            }
        )
        items.extend((baseline_repeat, candidate_repeat))
        report = self._report(items)
        baseline_case = report["repeat_diagnostics"]["baseline"]["cases"][0]
        candidate_case = report["repeat_diagnostics"]["candidate"]["cases"][0]
        self.assertTrue(baseline_case["label_instability"])
        self.assertTrue(baseline_case["score_instability"])
        self.assertFalse(baseline_case["status_instability"])
        self.assertTrue(candidate_case["status_instability"])

    def test_all_invariance_relations_emit_three_state_results(self) -> None:
        for relation in (
            "same_label",
            "swapped_preference",
            "same_score_within_tolerance",
        ):
            numeric = relation == "same_score_within_tolerance"
            satisfied = clone_records(relation=relation, numeric=numeric)
            if relation == "swapped_preference":
                for item in satisfied:
                    if item.get("record_type") == "trial" and item.get("case_id") == "case-2":
                        item["label"] = "fail"
            with self.subTest(relation=relation, result="satisfied"):
                result = self._report(satisfied)["invariance_groups"][0]["roles"][
                    "candidate"
                ][0]["result"]
                self.assertEqual(result, "satisfied")

            violated = clone_records(relation=relation, numeric=numeric)
            case_two = next(
                item
                for item in violated
                if item.get("record_type") == "trial"
                and item.get("case_id") == "case-2"
                and item.get("evaluation_id") == "eval-candidate"
            )
            if relation == "same_label":
                case_two["label"] = "fail"
            elif relation == "same_score_within_tolerance":
                case_two["score"] = 5
            with self.subTest(relation=relation, result="violated"):
                result = self._report(violated)["invariance_groups"][0]["roles"][
                    "candidate"
                ][0]["result"]
                self.assertEqual(result, "violated")

            not_evaluable = clone_records(relation=relation, numeric=numeric)
            case_two = next(
                item
                for item in not_evaluable
                if item.get("record_type") == "trial"
                and item.get("case_id") == "case-2"
                and item.get("evaluation_id") == "eval-candidate"
            )
            case_two.update({"status": "abstain", "label": None, "score": None})
            with self.subTest(relation=relation, result="not_evaluable"):
                result = self._report(not_evaluable)["invariance_groups"][0][
                    "roles"
                ]["candidate"][0]["result"]
                self.assertEqual(result, "not_evaluable")

    def test_anchor_coverage_and_confusion_are_annotation_aware(self) -> None:
        items = clone_records(with_anchors=True)
        second_anchor = next(
            item for item in items if item.get("anchor_id") == "anchor-1"
        )
        second_anchor["label"] = "fail"
        report = self._report(items)
        anchor = report["anchor_sets"][0]
        self.assertEqual(anchor["covered_case_count"], 2)
        self.assertEqual(anchor["coverage"]["numerator"], 1)
        self.assertEqual(anchor["coverage"]["denominator"], 1)
        self.assertEqual(anchor["roles"]["candidate"]["exact_label_disagreements"], 1)
        self.assertEqual(
            anchor["roles"]["candidate"]["confusion"],
            {"fail->pass": 1, "pass->pass": 1},
        )

    def test_provenance_delta_has_every_explicit_presence_state(self) -> None:
        items = clone_records()
        baseline = items[0]["evaluations"][0]["provenance"]
        candidate = items[0]["evaluations"][1]["provenance"]
        baseline["runner"] = component("runner-before")
        candidate["tool_version"] = component("tool-after")
        baseline["configuration"] = {
            "presence": "intentionally_omitted",
            "identity": None,
            "sha256": None,
        }
        candidate["configuration"] = component("configuration-after")
        delta = self._report(items)["provenance"]["evaluation_delta"]
        self.assertEqual(set(delta), set(PROVENANCE_FIELDS))
        self.assertEqual(delta["source_url"]["delta"], "same")
        self.assertEqual(delta["evaluator_source"]["delta"], "changed")
        self.assertEqual(delta["tool_version"]["delta"], "missing_before")
        self.assertEqual(delta["runner"]["delta"], "missing_after")
        self.assertEqual(delta["model_version"]["delta"], "missing_both")
        self.assertEqual(delta["configuration"]["delta"], "omitted")


class AssuranceContractTests(unittest.TestCase):
    def _report(
        self,
        items: list[dict[str, Any]],
        contract_document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = load_artifact(write_records(root / "input.jsonl", items))
            loaded_contract = (
                None
                if contract_document is None
                else load_contract(
                    write_json(root / "contract.json", contract_document), artifact
                )
            )
            return build_report(artifact, loaded_contract)

    def test_all_sixteen_locked_metrics_are_evaluated(self) -> None:
        rules = (
            rule("corpus_equal"),
            rule("context_isolated"),
            rule(
                "determinate_coverage",
                parameters={"role": "candidate"},
                threshold=1,
            ),
            rule("determinate_coverage_delta", threshold=0),
            rule(
                "status_count",
                parameters={"role": "candidate", "status": "determinate"},
                threshold=2,
            ),
            rule("new_status_count", parameters={"status": "error"}, threshold=0),
            rule(
                "determinate_label_count",
                parameters={"role": "candidate", "label": "pass"},
                threshold=2,
            ),
            rule(
                "determinate_label_transition_count",
                parameters={"from_label": "pass", "to_label": "fail"},
                threshold=0,
            ),
            rule(
                "critical_regression_count",
                scope="critical_group",
                scope_id="critical-1",
                parameters={"from_label": "pass", "to_label": "fail"},
                threshold=0,
            ),
            rule(
                "unstable_case_count",
                parameters={"role": "candidate", "dimension": "score"},
                threshold=0,
            ),
            rule(
                "invariance_violation_count",
                parameters={"role": "candidate"},
                threshold=0,
            ),
            rule(
                "invariance_not_evaluable_count",
                parameters={"role": "candidate"},
                threshold=0,
            ),
            rule(
                "anchor_coverage",
                scope="anchor_set",
                scope_id="anchors-1",
                threshold=1,
            ),
            rule(
                "anchor_disagreement_count",
                scope="anchor_set",
                scope_id="anchors-1",
                parameters={"role": "candidate"},
                threshold=0,
            ),
            rule(
                "provenance_present",
                scope="provenance",
                scope_id="artifact-1",
                parameters={"owner_type": "artifact", "field": "corpus_source"},
            ),
            rule("score_delta", threshold=1),
        )
        report = self._report(
            clone_records(
                relation="same_score_within_tolerance",
                with_anchors=True,
                numeric=True,
            ),
            contract(*rules),
        )
        self.assertEqual({item["metric"] for item in report["rule_results"]}, set(METRICS))
        self.assertTrue(
            all(item["result"] == "satisfied" for item in report["rule_results"])
        )
        self.assertEqual(report["contract_status"], "PASS")
        self.assertEqual(report["report_status"], "PASS")
        self.assertEqual(exit_code_for_report(report), 0)

    def test_severity_missing_evidence_and_report_precedence(self) -> None:
        violated = rule("corpus_equal", operator="ne")
        report = self._report(clone_records(), contract(violated))
        self.assertEqual(report["report_status"], "HARD_FAILURE")
        self.assertEqual(exit_code_for_report(report), 2)

        review = rule(
            "corpus_equal", operator="ne", severity="review", missing_evidence="review"
        )
        report = self._report(clone_records(), contract(review))
        self.assertEqual(report["report_status"], "REVIEW_REQUIRED")
        self.assertEqual(exit_code_for_report(report), 4)

        informational = rule(
            "corpus_equal", operator="ne", severity="info", missing_evidence="info"
        )
        report = self._report(clone_records(), contract(informational))
        self.assertEqual(report["contract_status"], "PASS")

        missing = rule("score_delta", missing_evidence="hard_fail")
        report = self._report(clone_records(), contract(missing))
        self.assertEqual(report["rule_results"][0]["result"], "not_applicable")
        self.assertEqual(report["report_status"], "HARD_FAILURE")

    def test_numeric_label_metrics_reach_not_applicable_for_every_policy(self) -> None:
        metrics = (
            (
                "determinate_label_count",
                "all_cases",
                None,
                {"role": "candidate", "label": "placeholder"},
            ),
            (
                "determinate_label_transition_count",
                "all_cases",
                None,
                {"from_label": "before", "to_label": "after"},
            ),
            (
                "critical_regression_count",
                "critical_group",
                "critical-1",
                {"from_label": "before", "to_label": "after"},
            ),
        )
        policies = (
            ("hard", "hard_fail", "HARD_FAILURE", 2),
            ("review", "review", "REVIEW_REQUIRED", 4),
            ("info", "info", "PASS", 0),
        )
        for metric, scope, scope_id, parameters in metrics:
            for severity, missing_evidence, contract_status, exit_code in policies:
                with self.subTest(metric=metric, policy=missing_evidence):
                    report = self._report(
                        pure_numeric_records(),
                        contract(
                            rule(
                                metric,
                                scope=scope,
                                scope_id=scope_id,
                                parameters=parameters,
                                severity=severity,
                                missing_evidence=missing_evidence,
                            )
                        ),
                    )
                    self.assertEqual(
                        report["rule_results"][0]["result"], "not_applicable"
                    )
                    self.assertEqual(report["contract_status"], contract_status)
                    self.assertEqual(exit_code_for_report(report), exit_code)

    def test_label_metric_parameters_stay_bounded_and_categorical_fail_closed(
        self,
    ) -> None:
        controls = (
            (
                "determinate_label_count",
                "all_cases",
                None,
                {"role": "candidate", "label": "illegal"},
            ),
            (
                "determinate_label_transition_count",
                "all_cases",
                None,
                {"from_label": "pass", "to_label": "illegal"},
            ),
            (
                "critical_regression_count",
                "critical_group",
                "critical-1",
                {"from_label": "pass", "to_label": "illegal"},
            ),
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = load_artifact(
                write_records(root / "categorical.jsonl", clone_records())
            )
            for metric, scope, scope_id, parameters in controls:
                with self.subTest(metric=metric), self.assertRaises(
                    PolicyConfigurationError
                ):
                    load_contract(
                        write_json(
                            root / f"{metric}.json",
                            contract(
                                rule(
                                    metric,
                                    scope=scope,
                                    scope_id=scope_id,
                                    parameters=parameters,
                                )
                            ),
                        ),
                        artifact,
                    )

            numeric = load_artifact(
                write_records(root / "numeric.jsonl", pure_numeric_records())
            )
            for bad_label in ("", "x" * 65, "bad\nlabel"):
                with self.subTest(label=repr(bad_label)), self.assertRaises(
                    InputValidationError
                ):
                    load_contract(
                        write_json(
                            root / "bad-numeric-label.json",
                            contract(
                                rule(
                                    "determinate_label_count",
                                    parameters={
                                        "role": "candidate",
                                        "label": bad_label,
                                    },
                                )
                            ),
                        ),
                        numeric,
                    )
    def test_incomplete_optional_evidence_never_silently_satisfies_zero(self) -> None:
        invariance_items = clone_records()
        candidate = next(
            item
            for item in invariance_items
            if item.get("trial_id") == "case-2-candidate-0"
        )
        candidate.update({"status": "abstain", "label": None})
        invariance_rule = rule(
            "invariance_violation_count",
            parameters={"role": "candidate"},
            severity="review",
            missing_evidence="review",
        )
        report = self._report(invariance_items, contract(invariance_rule))
        self.assertEqual(report["rule_results"][0]["result"], "missing")
        self.assertEqual(
            report["rule_results"][0]["evidence"]["partial_violation_count"], 0
        )
        self.assertEqual(report["report_status"], "REVIEW_REQUIRED")

        pairing_items = clone_records()
        baseline = next(
            item
            for item in pairing_items
            if item.get("trial_id") == "case-1-baseline-0"
        )
        baseline["pairing_key"] = None
        pairing_rule = rule(
            "new_status_count",
            parameters={"status": "error"},
            severity="review",
            missing_evidence="review",
        )
        report = self._report(pairing_items, contract(pairing_rule))
        self.assertEqual(report["rule_results"][0]["result"], "missing")
        self.assertEqual(
            report["rule_results"][0]["evidence"]["reason"], "incomplete_pairing"
        )

        anchor_items = clone_records(with_anchors=True)
        anchor_items[:] = [
            item for item in anchor_items if item.get("anchor_id") != "anchor-1"
        ]
        anchor_rule = rule(
            "anchor_disagreement_count",
            scope="anchor_set",
            scope_id="anchors-1",
            parameters={"role": "candidate"},
            severity="review",
            missing_evidence="review",
        )
        report = self._report(anchor_items, contract(anchor_rule))
        self.assertEqual(report["rule_results"][0]["result"], "missing")
        self.assertEqual(
            report["rule_results"][0]["evidence"]["reason"],
            "partial_anchor_coverage",
        )


if __name__ == "__main__":
    unittest.main()
