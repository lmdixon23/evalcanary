from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from evalcanary.compare import compare_verdicts
from evalcanary.io import load_cases
from evalcanary.models import Verdict
from evalcanary.policy import evaluate_policy


class ComparisonTests(unittest.TestCase):
    def test_transition_counts_and_slice(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "cases.jsonl"
            before_file = root / "before.py"
            after_file = root / "after.py"
            data.write_text(
                '{"id":"1","metadata":{"domain":"a"}}\n'
                '{"id":"2","metadata":{"domain":"a"}}\n'
                '{"id":"3","metadata":{"domain":"b"}}\n'
                '{"id":"4","metadata":{"domain":"b"}}\n',
                encoding="utf-8",
            )
            before_file.write_text("# before\n", encoding="utf-8")
            after_file.write_text("# after\n", encoding="utf-8")
            cases = load_cases(data)
            before = [
                Verdict("1", True),
                Verdict("2", True),
                Verdict("3", False),
                Verdict("4", False),
            ]
            after = [
                Verdict("1", True),
                Verdict("2", False),
                Verdict("3", True),
                Verdict("4", False),
            ]
            summary = compare_verdicts(
                cases,
                before,
                after,
                data_path=data,
                before_path=before_file,
                after_path=after_file,
                slices=["metadata.domain"],
                bootstrap_replicates=200,
            )
            self.assertEqual(summary.stable_pass, 1)
            self.assertEqual(summary.pass_to_fail, 1)
            self.assertEqual(summary.fail_to_pass, 1)
            self.assertEqual(summary.stable_fail, 1)
            self.assertEqual(len(summary.changed_cases), 2)
            self.assertEqual(len(summary.slices), 2)

    def test_policy_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "cases.jsonl"
            before_file = root / "before.py"
            after_file = root / "after.py"
            data.write_text('{"id":"1"}\n', encoding="utf-8")
            before_file.write_text("# before\n", encoding="utf-8")
            after_file.write_text("# after\n", encoding="utf-8")
            summary = compare_verdicts(
                load_cases(data),
                [Verdict("1", True)],
                [Verdict("1", False)],
                data_path=data,
                before_path=before_file,
                after_path=after_file,
                bootstrap_replicates=200,
            )
            gated = evaluate_policy(summary, {"max_pass_to_fail": 0})
            self.assertFalse(gated.policy["passed"])


if __name__ == "__main__":
    unittest.main()
