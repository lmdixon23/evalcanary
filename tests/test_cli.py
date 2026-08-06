from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evalcanary.cli import EXIT_OK, EXIT_POLICY_FAIL, main


class CliTests(unittest.TestCase):
    def test_diff_writes_three_report_formats(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "cases.jsonl"
            before = root / "before.py"
            after = root / "after.py"
            out = root / "report"
            data.write_text('{"id":"1","expected":"a","output":"A"}\n', encoding="utf-8")
            before.write_text('def verify(case):\n    return case["output"] == case["expected"]\n', encoding="utf-8")
            after.write_text('def verify(case):\n    return case["output"].casefold() == case["expected"].casefold()\n', encoding="utf-8")
            result = main([
                "diff", "--data", str(data), "--before", str(before),
                "--after", str(after), "--out", str(out),
                "--bootstrap-replicates", "200",
            ])
            self.assertEqual(result, EXIT_OK)
            self.assertTrue((out / "report.json").is_file())
            self.assertTrue((out / "report.md").is_file())
            self.assertTrue((out / "report.html").is_file())
            payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["transition_counts"]["fail_to_pass"], 1)

    def test_policy_failure_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "cases.jsonl"
            before = root / "before.py"
            after = root / "after.py"
            policy = root / "policy.toml"
            out = root / "report"
            data.write_text('{"id":"1","expected":"a","output":"A"}\n', encoding="utf-8")
            before.write_text('def verify(case):\n    return False\n', encoding="utf-8")
            after.write_text('def verify(case):\n    return True\n', encoding="utf-8")
            policy.write_text('[policy]\nmax_fail_to_pass = 0\n', encoding="utf-8")
            result = main([
                "diff", "--data", str(data), "--before", str(before),
                "--after", str(after), "--out", str(out),
                "--policy", str(policy), "--bootstrap-replicates", "200",
            ])
            self.assertEqual(result, EXIT_POLICY_FAIL)


if __name__ == "__main__":
    unittest.main()
