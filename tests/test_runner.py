from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from evalcanary.io import load_cases
from evalcanary.runner import run_verifier


class RunnerTests(unittest.TestCase):
    def test_bool_and_dict_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "cases.jsonl"
            verifier = root / "verifier.py"
            data.write_text('{"id":"1","value":1}\n{"id":"2","value":0}\n', encoding="utf-8")
            verifier.write_text(
                'def verify(case):\n'
                '    if case["id"] == "1":\n'
                '        return True\n'
                '    return {"passed": False, "reason": "zero"}\n',
                encoding="utf-8",
            )
            verdicts = run_verifier(verifier, load_cases(data), timeout_seconds=10)
            self.assertEqual([item.passed for item in verdicts], [True, False])
            self.assertEqual(verdicts[1].reason, "zero")

    def test_case_exception_becomes_error_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "cases.jsonl"
            verifier = root / "verifier.py"
            data.write_text('{"id":"1"}\n', encoding="utf-8")
            verifier.write_text('def verify(case):\n    raise ValueError("bad case")\n', encoding="utf-8")
            verdict = run_verifier(verifier, load_cases(data), timeout_seconds=10)[0]
            self.assertIsNone(verdict.passed)
            self.assertIn("ValueError", verdict.error or "")


if __name__ == "__main__":
    unittest.main()
