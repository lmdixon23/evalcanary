from __future__ import annotations

import hashlib
import json
import socket
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from scripts.prepare_assurance_cases import (
    _contract,
    build_artifact,
    build_case_c_artifact,
    judge_case_a,
    judge_case_b,
    load_case_lock,
    normalize_case_c_winner,
    synthetic_case_c_rows,
    verify_case_c_synthetic_vectors,
    verify_fixture_vectors,
)
from scripts.validate_mt_bench_case import analyze_rows
from tests.assurance_helpers import write_json, write_records

from evalcanary.assurance.engine import build_report
from evalcanary.assurance.schema import load_artifact, load_contract

_LOCK_PATH = Path(__file__).parent / "fixtures" / "assurance" / "case_locks.json"


class LockedCaseFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.locks = load_case_lock(_LOCK_PATH)

    def test_all_inert_fixture_bytes_and_final_newlines_are_exact(self) -> None:
        for case_name in ("case_a", "case_b"):
            verify_fixture_vectors(case_name, self.locks[case_name])
            for index, fixture in enumerate(self.locks[case_name]["fixtures"]):
                data = fixture["text"].encode("utf-8")
                with self.subTest(case=case_name, fixture=fixture["case_id"]):
                    self.assertEqual(len(data), fixture["bytes"])
                    self.assertEqual(
                        hashlib.sha256(data).hexdigest(), fixture["sha256"]
                    )
                    expected_lf = case_name == "case_a" or index == 3
                    self.assertEqual(data.endswith(b"\n"), expected_lf)

    def test_case_a_matrix_exposes_denominator_and_instrument_errors(self) -> None:
        fixtures = self.locks["case_a"]["fixtures"]
        self.assertEqual(
            [judge_case_a(item["text"], "baseline") for item in fixtures],
            [tuple(item["baseline"]) for item in fixtures],
        )
        self.assertEqual(
            [judge_case_a(item["text"], "candidate") for item in fixtures],
            [tuple(item["candidate"]) for item in fixtures],
        )
        report = self._report("case_a")
        self.assertEqual(report["report_status"], "PASS")
        self.assertEqual(
            report["repeat_diagnostics"]["baseline"]["status_distribution"][
                "determinate"
            ],
            5,
        )
        self.assertEqual(
            report["repeat_diagnostics"]["candidate"]["status_distribution"]["error"],
            2,
        )
        self.assertEqual(
            report["repeat_diagnostics"]["candidate"]["determinate_coverage"][
                "numerator"
            ],
            3,
        )
        self.assertEqual(
            report["repeat_diagnostics"]["candidate"]["determinate_coverage"][
                "denominator"
            ],
            5,
        )

    def test_case_b_matrix_closes_spoof_and_preserves_controls(self) -> None:
        fixtures = self.locks["case_b"]["fixtures"]
        self.assertEqual(
            [judge_case_b(item["text"], "baseline") for item in fixtures],
            [tuple(item["baseline"]) for item in fixtures],
        )
        self.assertEqual(
            [judge_case_b(item["text"], "candidate") for item in fixtures],
            [tuple(item["candidate"]) for item in fixtures],
        )
        report = self._report("case_b")
        self.assertEqual(report["report_status"], "PASS")
        self.assertEqual(report["transitions"]["label_transitions"]["pass->fail"], 1)
        reset_case = next(
            item
            for item in report["cases"]
            if item["case_id"] == "b-reset-fail-control"
        )
        for role in ("baseline", "candidate"):
            provenance = reset_case["trials"][role][0]["provenance"]
            self.assertEqual(provenance["test_command_status"]["identity"], "0")
            self.assertEqual(provenance["reset_status"]["identity"], "failed")

    def test_case_builders_attempt_no_network_or_process_execution(self) -> None:
        with patch.object(
            socket.socket, "connect", side_effect=AssertionError("network forbidden")
        ):
            for case_name in ("case_a", "case_b", "case_c"):
                build_artifact(case_name, self.locks[case_name])
                if case_name == "case_c":
                    verify_case_c_synthetic_vectors(self.locks[case_name])
                else:
                    verify_fixture_vectors(case_name, self.locks[case_name])

    def test_source_pin_inventory_is_closed(self) -> None:
        self.assertEqual(len(self.locks["case_a"]["source_files"]), 7)
        self.assertEqual(len(self.locks["case_b"]["source_files"]), 8)
        self.assertEqual(len(self.locks["case_c"]["source_files"]), 2)
        for case_name in ("case_a", "case_b", "case_c"):
            for digest in self.locks[case_name]["source_files"].values():
                self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertRegex(
            self.locks["case_c"]["raw_source"]["sha256"], r"^[0-9a-f]{64}$"
        )
        for digest in self.locks["case_c"]["pair_semantics"]["source_files"].values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_case_c_aggregate_metadata_remains_distinct_from_raw_games(self) -> None:
        singleton = {
            "question_id": 81,
            "turn": 1,
            "model_a": "model-one",
            "model_b": "model-two",
            "winner": "tie (inconsistent)",
            "judge": "frozen-judge",
        }
        analysis = analyze_rows([singleton])
        self.assertEqual(analysis["eligible_two_order_groups"], 0)
        self.assertEqual(analysis["rows_with_reverse_order"], 0)
        self.assertEqual(
            analysis["unsupported_winner_counts"], {"tie (inconsistent)": 1}
        )

        reverse = dict(
            singleton,
            model_a="model-two",
            model_b="model-one",
            winner="model_b",
        )
        singleton["winner"] = "model_a"
        analysis = analyze_rows([singleton, reverse])
        self.assertEqual(analysis["eligible_two_order_groups"], 1)
        self.assertEqual(analysis["rows_with_reverse_order"], 2)
        self.assertEqual(analysis["unsupported_winner_counts"], {})

    def test_case_c_normalizes_model_relative_winners_by_display_order(self) -> None:
        expected = {
            ("model_1", 1): ("determinate", "a"),
            ("model_2", 1): ("determinate", "b"),
            ("model_1", 2): ("determinate", "b"),
            ("model_2", 2): ("determinate", "a"),
            ("tie", 1): ("determinate", "tie"),
            ("tie", 2): ("determinate", "tie"),
            ("error", 1): ("error", None),
            ("error", 2): ("error", None),
        }
        for arguments, result in expected.items():
            with self.subTest(winner=arguments[0], game=arguments[1]):
                self.assertEqual(normalize_case_c_winner(*arguments), result)
        with self.assertRaises(ValueError):
            normalize_case_c_winner("tie (inconsistent)", 1)

    def test_case_c_synthetic_policy_and_invariance_mechanics(self) -> None:
        lock = self.locks["case_c"]
        verify_case_c_synthetic_vectors(lock)
        report = self._report("case_c")
        self.assertEqual(report["report_status"], "PASS")
        counts: dict[str, Counter[str]] = {}
        for role in ("baseline", "candidate"):
            counts[role] = Counter(
                group["roles"][role][0]["result"]
                for group in report["invariance_groups"]
            )
        self.assertEqual(counts["baseline"], {"not_evaluable": 5})
        self.assertEqual(
            counts["candidate"],
            {"satisfied": 2, "violated": 2, "not_evaluable": 1},
        )

        items = build_artifact("case_c", lock)
        trials = [item for item in items if item["record_type"] == "trial"]
        exclusions = [
            item
            for item in trials
            if item["evaluation_id"] == "case-c-baseline"
            and item["provenance"]["evidence_policy"]["identity"]
            == "single_order_policy_exclusion"
        ]
        self.assertEqual(len(exclusions), 5)
        self.assertTrue(all(item["status"] == "abstain" for item in exclusions))
        source_errors = [
            item
            for item in trials
            if item["evaluation_id"] == "case-c-candidate" and item["status"] == "error"
        ]
        self.assertEqual(len(source_errors), 1)
        self.assertIsNone(source_errors[0]["label"])

    def test_case_c_synthetic_human_anchors_are_one_order_and_clustered(self) -> None:
        lock = self.locks["case_c"]
        selected, human = synthetic_case_c_rows(lock)
        records = build_case_c_artifact(lock, selected, human)
        anchors = [item for item in records if item["record_type"] == "anchor"]
        self.assertEqual(len(anchors), 4)
        self.assertEqual(len({item["anchor_id"] for item in anchors}), 4)
        self.assertEqual(len({item["case_id"] for item in anchors}), 3)
        self.assertEqual(len({item["cluster_id"] for item in anchors}), 2)
        self.assertTrue(all(item["kind"] == "raw_annotation" for item in anchors))

        anchor_report = self._report("case_c")["anchor_sets"][0]
        self.assertEqual(anchor_report["aggregation_method"], "none")
        self.assertEqual(anchor_report["raw_annotation_count"], 4)
        self.assertEqual(anchor_report["covered_case_count"], 3)
        self.assertEqual(anchor_report["cluster_count"], 2)
        self.assertEqual(
            anchor_report["roles"]["candidate"]["exact_label_agreements"], 2
        )
        self.assertEqual(
            anchor_report["roles"]["candidate"]["exact_label_disagreements"], 2
        )

    def test_case_c_tracked_vectors_are_original_and_synthetic(self) -> None:
        lock = self.locks["case_c"]
        fixtures = lock["synthetic_fixtures"]
        self.assertEqual(len(fixtures), 5)
        self.assertTrue(
            all(
                fixture["fixture_id"].startswith("synthetic-")
                and fixture["model_1"].startswith("synthetic-")
                and fixture["model_2"].startswith("synthetic-")
                for fixture in fixtures
            )
        )
        fixture_text = json.dumps(fixtures, sort_keys=True)
        for protected_field in (
            "g1_user_prompt",
            "g2_user_prompt",
            "g1_judgment",
            "g2_judgment",
        ):
            self.assertNotIn(protected_field, fixture_text)
        self.assertEqual(
            lock["publication_status"],
            "BLOCKED_PENDING_SOURCE_LICENSE_CLARIFICATION",
        )

    def _report(self, case_name: str) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            items = build_artifact(case_name, self.locks[case_name])
            artifact = load_artifact(write_records(root / "input.jsonl", items))
            contract = load_contract(
                write_json(root / "contract.json", _contract(case_name)), artifact
            )
            return build_report(artifact, contract)


if __name__ == "__main__":
    unittest.main()
