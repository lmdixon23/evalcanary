from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _load_module() -> ModuleType:
    path = ROOT / "scripts" / "run_action.py"
    spec = importlib.util.spec_from_file_location("evalcanary_action_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load scripts/run_action.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _load_module()


class ActionRunnerTests(unittest.TestCase):
    def test_build_command_preserves_multiple_slices_and_flags(self) -> None:
        environment = {
            "EVALCANARY_INPUT_DATA": "cases.jsonl",
            "EVALCANARY_INPUT_BEFORE": "before.py",
            "EVALCANARY_INPUT_AFTER": "after.py",
            "EVALCANARY_INPUT_OUTPUT": "report",
            "EVALCANARY_INPUT_POLICY": "policy.toml",
            "EVALCANARY_INPUT_SLICE": "metadata.domain\nmetadata.language",
            "EVALCANARY_INPUT_TIMEOUT": "45",
            "EVALCANARY_INPUT_BOOTSTRAP_REPLICATES": "500",
            "EVALCANARY_INPUT_BOOTSTRAP_SEED": "7",
            "EVALCANARY_INPUT_PYTHON": "python-alt",
            "EVALCANARY_INPUT_INCLUDE_CONTENT": "true",
            "EVALCANARY_INPUT_INCLUDE_SOURCE_DIFF": "yes",
        }
        command = RUNNER.build_command(environment)
        self.assertEqual(command.count("--slice"), 2)
        self.assertIn("metadata.domain", command)
        self.assertIn("metadata.language", command)
        self.assertIn("--include-content", command)
        self.assertIn("--include-source-diff", command)
        self.assertIn("python-alt", command)

    def test_required_input_rejects_whitespace(self) -> None:
        with self.assertRaisesRegex(ValueError, "EVALCANARY_INPUT_DATA"):
            RUNNER.build_command(
                {
                    "EVALCANARY_INPUT_DATA": " ",
                    "EVALCANARY_INPUT_BEFORE": "before.py",
                    "EVALCANARY_INPUT_AFTER": "after.py",
                    "EVALCANARY_INPUT_OUTPUT": "report",
                }
            )

    def test_write_outputs_reports_transition_and_policy_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "report"
            report.mkdir()
            for name in ("report.md", "report.html"):
                (report / name).write_text(name, encoding="utf-8")
            (report / "report.json").write_text(
                json.dumps(
                    {
                        "run_id": "abc123",
                        "transition_counts": {
                            "stable_pass": 4,
                            "pass_to_fail": 2,
                            "fail_to_pass": 3,
                            "stable_fail": 1,
                        },
                        "policy": {"configured": True, "passed": False},
                    }
                ),
                encoding="utf-8",
            )
            output = root / "github-output.txt"
            RUNNER.write_outputs(report, output)
            text = output.read_text(encoding="utf-8")
            self.assertIn("run_id<<", text)
            self.assertIn("abc123", text)
            self.assertIn("changed_cases<<", text)
            self.assertIn("\n5\n", text)
            self.assertIn("policy_passed<<", text)
            self.assertIn("\nfalse\n", text)
            self.assertIn(str(report.resolve()), text)


if __name__ == "__main__":
    unittest.main()
