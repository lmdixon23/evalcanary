from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_verifier_prints_do_not_corrupt_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "cases.jsonl"
            verifier = root / "verifier.py"
            data.write_text('{"id":"1"}\n', encoding="utf-8")
            verifier.write_text(
                'print("module log")\n'
                'def verify(case):\n'
                '    print("case log")\n'
                '    return True\n',
                encoding="utf-8",
            )
            verdict = run_verifier(verifier, load_cases(data), timeout_seconds=10)[0]
            self.assertTrue(verdict.passed)

    def test_non_finite_score_becomes_error_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "cases.jsonl"
            verifier = root / "verifier.py"
            data.write_text('{"id":"1"}\n', encoding="utf-8")
            verifier.write_text(
                'def verify(case):\n'
                '    return {"passed": True, "score": float("nan")}\n',
                encoding="utf-8",
            )
            verdict = run_verifier(verifier, load_cases(data), timeout_seconds=10)[0]
            self.assertIsNone(verdict.passed)
            self.assertIn("finite", verdict.error or "")

    def test_alternative_python_executes_worker_by_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "cases.jsonl"
            verifier = root / "verifier.py"
            data.write_text('{"id":"1"}\n', encoding="utf-8")
            verifier.write_text('def verify(case): return True\n', encoding="utf-8")
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=(
                    '{"case_id":"1","passed":true,"score":1.0,'
                    '"reason":null,"details":null,"error":null,'
                    '"duration_ms":0.1}\n'
                ),
                stderr="",
            )
            with patch("evalcanary.runner.subprocess.run", return_value=completed) as mocked:
                verdict = run_verifier(
                    verifier,
                    load_cases(data),
                    timeout_seconds=10,
                    python_executable="custom-python",
                )[0]
            command = mocked.call_args.args[0]
            environment = mocked.call_args.kwargs["env"]
            self.assertEqual(command[0], "custom-python")
            self.assertEqual(Path(command[1]).name, "worker.py")
            self.assertNotIn("-m", command)
            self.assertEqual(environment["PYTHONHASHSEED"], "0")
            self.assertTrue(verdict.passed)


if __name__ == "__main__":
    unittest.main()
