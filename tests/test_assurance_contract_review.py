from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from tests.assurance_helpers import (
    clone_records,
    contract,
    pure_numeric_records,
    rule,
    write_json,
    write_records,
)

from evalcanary.assurance._contract_review import _review_contract, _review_text
from evalcanary.assurance.engine import build_report
from evalcanary.assurance.numeric import canonical_json_text
from evalcanary.assurance.review_queue import build_review_queue, resolve_pointer
from evalcanary.assurance.schema import Limits, load_artifact, load_contract
from evalcanary.assurance.structural import METRIC_SIGNATURES
from evalcanary.cli import main
from evalcanary.errors import InputValidationError


class ContractReviewCLITests(unittest.TestCase):
    def test_minimal_review_is_bound_read_only_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = write_records(root / "input.jsonl", clone_records())
            policy = write_json(root / "contract.json", contract(rule("corpus_equal")))
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            outputs = []
            for _ in range(2):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = main(
                        [
                            "contract-review",
                            "--input",
                            str(source),
                            "--contract",
                            str(policy),
                        ]
                    )
                self.assertEqual(code, 0)
                outputs.append(output.getvalue())
            self.assertEqual(outputs[0], outputs[1])
            review = json.loads(outputs[0])
            self.assertEqual(
                review["contract"]["source_sha256"],
                hashlib.sha256(policy.read_bytes()).hexdigest(),
            )
            self.assertEqual(review["coverage"]["metrics"]["denominator_count"], 16)
            self.assertEqual(review["coverage"]["metrics"]["covered_count"], 1)
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})


class ContractCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def analyze(self, rules, items=None):
        source = write_records(
            self.root / "input.jsonl", clone_records() if items is None else items
        )
        policy = write_json(self.root / "contract.json", contract(*rules))
        artifact = load_artifact(source)
        loaded = load_contract(policy, artifact)
        report = build_report(artifact, loaded)
        original_report = canonical_json_text(report)
        original_contract = canonical_json_text(loaded.document)
        queue = canonical_json_text(build_review_queue(report))
        review = _review_contract(loaded, report)
        self.assertEqual(original_report, canonical_json_text(report))
        self.assertEqual(original_contract, canonical_json_text(loaded.document))
        self.assertEqual(queue, canonical_json_text(build_review_queue(report)))
        for section in review["coverage"].values():
            for row in section["findings"]:
                resolve_pointer(loaded.document, row["contract_pointer"])
                self.assertEqual(len(row["finding_id"]), 64)
        return review, report

    def test_all_metrics_and_signature_denominators_are_registry_derived(self):
        params = {
            "role": "candidate",
            "status": "determinate",
            "label": "pass",
            "from_label": "pass",
            "to_label": "fail",
            "dimension": "score",
            "owner_type": "artifact",
            "field": "corpus_source",
        }
        ids = {
            "all_cases": None,
            "critical_group": "critical-1",
            "anchor_set": "anchors-1",
            "provenance": "artifact-1",
            "invariance_group": "invariance-1",
        }
        rules = []
        for metric, (scopes, fields) in sorted(METRIC_SIGNATURES.items()):
            scope = sorted(scopes)[0]
            rules.append(
                rule(
                    metric,
                    scope=scope,
                    scope_id=ids[scope],
                    parameters={k: params[k] for k in fields},
                )
            )
        review, _ = self.analyze(rules, clone_records(numeric=True, with_anchors=True))
        coverage = review["coverage"]
        self.assertEqual(coverage["metrics"]["covered_count"], 16)
        self.assertEqual(coverage["metrics"]["not_covered_count"], 0)
        expected = sum(
            len(scopes) * (2 if "role" in fields else 1)
            for scopes, fields in METRIC_SIGNATURES.values()
        )
        self.assertEqual(coverage["metric_scope_roles"]["denominator_count"], expected)
        self.assertEqual(len(coverage["metric_scope_roles"]["findings"]), expected)
        for section in ("metrics", "metric_scope_roles", "trial_status_evidence"):
            self.assertTrue(coverage[section]["denominator"])

    def test_partial_scope_and_role_do_not_imply_all_cases_or_other_role(self):
        review, _ = self.analyze(
            [
                rule(
                    "status_count",
                    scope="critical_group",
                    scope_id="critical-1",
                    parameters={"role": "candidate", "status": "determinate"},
                )
            ]
        )
        signatures = review["coverage"]["metric_scope_roles"]["findings"]
        covered = [r for r in signatures if r["coverage"] == "covered"]
        self.assertEqual(
            [(r["metric"], r["scope"], r["explicit_role"]) for r in covered],
            [("status_count", "critical_group", "candidate")],
        )
        statuses = review["coverage"]["trial_status_evidence"]["findings"]
        self.assertTrue(all(r["coverage"] == "not covered" for r in statuses))
        self.assertEqual(sum(r["observed_trial_count"] for r in statuses), 4)
        review, _ = self.analyze(
            [
                rule(
                    "status_count",
                    parameters={"role": "candidate", "status": "determinate"},
                )
            ]
        )
        covered = [
            r
            for r in review["coverage"]["trial_status_evidence"]["findings"]
            if r["coverage"] == "covered"
        ]
        self.assertEqual(
            [(r["role"], r["status"]) for r in covered], [("candidate", "determinate")]
        )

    def test_missing_not_applicable_unknown_and_observed_remain_distinct(self):
        for items, expected in (
            (clone_records(), "not applicable"),
            (pure_numeric_records(), "observed"),
            (clone_records(numeric=True), "observed"),
        ):
            with self.subTest(
                expected=expected, kind=items[0]["judgment_spec"]["kind"]
            ):
                review, _ = self.analyze([rule("score_delta")], items)
                self.assertEqual(
                    review["coverage"]["rules"]["findings"][0]["availability"], expected
                )
        items = clone_records(numeric=True)
        next(r for r in items if r.get("trial_id") == "case-1-candidate-0")["score"] = (
            None
        )
        for policy in ("hard_fail", "review", "info"):
            review, report = self.analyze(
                [rule("score_delta", missing_evidence=policy)], items
            )
            self.assertEqual(
                review["coverage"]["rules"]["availability_counts"]["not evaluable"], 1
            )
            self.assertEqual(
                report["contract_status"],
                {
                    "hard_fail": "HARD_FAILURE",
                    "review": "REVIEW_REQUIRED",
                    "info": "PASS",
                }[policy],
            )
        items = [r for r in items if r.get("trial_id") != "case-1-candidate-0"]
        review, report = self.analyze([rule("corpus_equal")], items)
        self.assertEqual(report["contract_status"], "NOT_EVALUATED")
        self.assertEqual(
            review["coverage"]["rules"]["availability_counts"]["unknown"], 1
        )

    def test_unknown_isolation_is_not_replaced_by_coverage(self):
        items = clone_records()
        for evaluation in items[0]["evaluations"]:
            evaluation["context_components"]["runtime"] = {
                "presence": "missing",
                "identity": None,
                "sha256": None,
            }
        review, report = self.analyze([rule("context_isolated")], items)
        self.assertEqual(review["report"]["isolation_status"], "UNKNOWN")
        self.assertEqual(report["rule_results"][0]["result"], "missing")

    def test_large_contract_counts_are_complete_and_details_are_bounded(self):
        rules = [dict(rule("corpus_equal"), rule_id=f"rule-{i}") for i in range(1024)]
        review, _ = self.analyze(rules)
        details = review["coverage"]["rules"]
        self.assertEqual(
            (
                details["total_findings"],
                details["displayed_findings"],
                details["omitted_findings"],
            ),
            (1024, 100, 924),
        )
        self.assertEqual(details["availability_counts"]["observed"], 1024)
        self.assertEqual(details["findings"][-1]["contract_pointer"], "/rules/99")
        self.assertEqual(review["coverage"]["metrics"]["covered_count"], 1)
        self.assertLess(len(_review_text(review, Limits())), 150000)
        with self.assertRaises(InputValidationError):
            _review_text(
                review, Limits(values={**Limits().values, "json_report_bytes": 10})
            )

    def test_private_content_is_not_projected_and_network_is_not_used(self):
        secret = "PRIVATE_LABEL_TOKEN"
        items = clone_records()
        items[0]["judgment_spec"]["label_space"] = [secret, "fail"]
        for item in items:
            if item.get("label") == "pass":
                item["label"] = secret
        candidate = rule(
            "determinate_label_count", parameters={"role": "candidate", "label": secret}
        )
        candidate["rationale"] = "private rationale C:/private/path"
        candidate["extensions"] = {"example.private": {"text": "private extension"}}
        with patch("socket.socket", side_effect=AssertionError("network")):
            review, _ = self.analyze([candidate], items)
        text = _review_text(review, Limits())
        for token in (
            secret,
            "private rationale",
            "private extension",
            "private message",
            "secret reason",
            "provider-secret",
            str(self.root),
        ):
            self.assertNotIn(token, text)

    def test_cli_review_completion_is_not_a_migration_pass(self):
        source = write_records(self.root / "input.jsonl", clone_records())
        policy = write_json(
            self.root / "contract.json", contract(rule("corpus_equal", operator="ne"))
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                main(
                    [
                        "contract-review",
                        "--input",
                        str(source),
                        "--contract",
                        str(policy),
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "migrate",
                        "--input",
                        str(source),
                        "--contract",
                        str(policy),
                        "--out",
                        str(self.root / "packet"),
                    ]
                ),
                2,
            )
        packet = self.root / "packet"
        self.assertEqual(len(list(packet.iterdir())), 5)

    def test_invalid_contracts_still_use_normative_validation(self):
        source = write_records(self.root / "input.jsonl", clone_records())
        invalids = [
            contract(rule("unsupported_metric")),
            contract(rule("corpus_equal"), rule("corpus_equal")),
            contract(rule("corpus_equal", parameters={"role": "candidate"})),
            contract(
                rule("corpus_equal", scope="critical_group", scope_id="critical-1")
            ),
        ]
        for invalid in invalids:
            policy = write_json(self.root / "contract.json", invalid)
            output = io.StringIO()
            with (
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(
                    main(
                        [
                            "contract-review",
                            "--input",
                            str(source),
                            "--contract",
                            str(policy),
                        ]
                    ),
                    3,
                )
            self.assertEqual(output.getvalue(), "")


class ContractLintTests(unittest.TestCase):
    setUp = ContractCoverageTests.setUp
    analyze = ContractCoverageTests.analyze

    def test_duplicate_evaluation_fields_are_located_without_rewriting(self):
        one = rule("corpus_equal")
        two = dict(one, rule_id="another", rationale="A separate human purpose.")
        review, report = self.analyze([one, two])
        lint = review["lint"]
        self.assertEqual(lint["total_findings"], 1)
        self.assertEqual(len(report["rule_results"]), 2)
        finding = lint["findings"][0]
        self.assertEqual(finding["code"], "REPEATED_EVALUATION_FIELDS")
        self.assertEqual(finding["level"], "WARNING")
        self.assertEqual(finding["contract_pointer"], "/rules/1")
        self.assertEqual(finding["first_rule_pointer"], "/rules/0")

    def test_every_operative_field_near_neighbor_stays_unflagged(self):
        base = rule(
            "status_count",
            parameters={"role": "candidate", "status": "error"},
            threshold=1,
        )
        neighbors = [
            dict(base, threshold=2),
            dict(base, operator="ne"),
            dict(base, severity="review", missing_evidence="review"),
            dict(base, missing_evidence="info"),
            dict(base, scope="critical_group", scope_id="critical-1"),
            dict(base, parameters={"role": "baseline", "status": "error"}),
            dict(base, parameters={"role": "candidate", "status": "abstain"}),
            rule(
                "determinate_label_count",
                parameters={"role": "candidate", "label": "fail"},
                threshold=1,
            ),
        ]
        for index, neighbor in enumerate(neighbors):
            with self.subTest(neighbor=index):
                neighbor["rule_id"] = "distinct"
                review, _ = self.analyze([base, neighbor])
                self.assertEqual(review["lint"]["total_findings"], 0)
        # Severity alone differs, with the same valid missing-evidence choice.
        review, _ = self.analyze(
            [
                dict(base, missing_evidence="info"),
                dict(
                    base, rule_id="distinct", severity="review", missing_evidence="info"
                ),
            ]
        )
        self.assertEqual(review["lint"]["total_findings"], 0)
        # Different valid owner IDs under the same provenance selector.
        first = rule(
            "provenance_present",
            scope="provenance",
            scope_id="eval-baseline",
            parameters={"owner_type": "evaluation", "field": "evaluator_source"},
        )
        second = dict(first, rule_id="other", scope_id="eval-candidate")
        review, _ = self.analyze([first, second])
        self.assertEqual(review["lint"]["total_findings"], 0)

    def test_exact_numbers_and_parameter_order_but_no_label_normalization(self):
        first = rule(
            "status_count",
            parameters={"role": "candidate", "status": "error"},
            threshold=Decimal("0.00"),
        )
        second = dict(
            first,
            rule_id="second",
            threshold=Decimal("-0"),
            parameters={"status": "error", "role": "candidate"},
            extensions={"example.audit": {"purpose": "separate"}},
        )
        review, _ = self.analyze([first, second])
        self.assertEqual(review["lint"]["total_findings"], 1)
        first = rule(
            "score_delta", threshold=Decimal("0.12345678901234567890123456789")
        )
        second = dict(
            first,
            rule_id="second",
            threshold=Decimal("0.12345678901234567890123456790"),
        )
        review, _ = self.analyze([first, second], clone_records(numeric=True))
        self.assertEqual(review["lint"]["total_findings"], 0)
        first = rule(
            "determinate_label_count", parameters={"role": "candidate", "label": "pass"}
        )
        second = dict(
            first, rule_id="second", parameters={"role": "candidate", "label": "fail"}
        )
        review, _ = self.analyze([first, second])
        self.assertEqual(review["lint"]["total_findings"], 0)

    def test_opposed_predicates_are_not_semantic_lint(self):
        first = rule("corpus_equal")
        second = dict(first, rule_id="opposed", operator="ne")
        review, report = self.analyze([first, second])
        self.assertEqual(review["lint"]["total_findings"], 0)
        self.assertEqual(report["contract_status"], "HARD_FAILURE")

    def test_large_duplicate_groups_bind_first_rule_and_complete_counts(self):
        rules = [dict(rule("corpus_equal"), rule_id=f"rule-{i}") for i in range(1024)]
        review, _ = self.analyze(rules)
        lint = review["lint"]
        self.assertEqual(
            (
                lint["total_findings"],
                lint["displayed_findings"],
                lint["omitted_findings"],
            ),
            (1023, 100, 923),
        )
        for index, finding in enumerate(lint["findings"], start=1):
            self.assertEqual(finding["contract_pointer"], f"/rules/{index}")
            self.assertEqual(finding["first_rule_pointer"], "/rules/0")
            self.assertEqual(
                resolve_pointer(contract(*rules), finding["first_rule_pointer"]),
                rules[0],
            )
            self.assertEqual(
                resolve_pointer(contract(*rules), finding["contract_pointer"]),
                rules[index],
            )
        self.assertEqual(len({r["finding_id"] for r in lint["findings"]}), 100)
        self.assertLess(len(_review_text(review, Limits())), 150000)

    def test_lint_ids_and_output_bind_exact_source_and_are_deterministic(self):
        first = rule("corpus_equal")
        second = dict(first, rule_id="second")
        review, _ = self.analyze([first, second])
        again, _ = self.analyze([first, second])
        self.assertEqual(_review_text(review, Limits()), _review_text(again, Limits()))
        second["rationale"] = "Same operative fields, different artifact bytes."
        changed, _ = self.analyze([first, second])
        self.assertNotEqual(
            review["contract"]["source_sha256"], changed["contract"]["source_sha256"]
        )
        self.assertNotEqual(
            review["lint"]["findings"][0]["finding_id"],
            changed["lint"]["findings"][0]["finding_id"],
        )

    def test_categorical_numeric_mixed_and_all_missing_policies(self):
        for items in (
            clone_records(),
            pure_numeric_records(),
            clone_records(numeric=True),
        ):
            for missing in ("info", "review", "hard_fail"):
                with self.subTest(
                    kind=items[0]["judgment_spec"]["kind"], missing=missing
                ):
                    first = rule("score_delta", missing_evidence=missing)
                    second = dict(first, rule_id="second")
                    review, _ = self.analyze([first, second], deepcopy(items))
                    self.assertEqual(review["lint"]["total_findings"], 1)


if __name__ == "__main__":
    unittest.main()
