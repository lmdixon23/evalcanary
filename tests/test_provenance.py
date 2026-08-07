from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evalcanary.provenance import build_provenance, make_run_id, sanitize_command


class ProvenanceTests(unittest.TestCase):
    def test_run_id_depends_on_both_verifiers_and_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "cases.jsonl"
            before = root / "before.py"
            after_a = root / "after_a.py"
            after_b = root / "after_b.py"
            data.write_text('{"id":"1"}\n', encoding="utf-8")
            before.write_text("def verify(case): return False\n", encoding="utf-8")
            after_a.write_text("def verify(case): return True\n", encoding="utf-8")
            after_b.write_text("def verify(case): return False\n", encoding="utf-8")

            first = make_run_id(data, before, after_a)
            second = make_run_id(data, before, after_b)
            self.assertNotEqual(first, second)

    def test_provenance_redacts_parent_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "private" / "cases.jsonl"
            before = root / "private" / "before.py"
            after = root / "private" / "after.py"
            data.parent.mkdir()
            data.write_text('{"id":"1"}\n', encoding="utf-8")
            before.write_text("# before\n", encoding="utf-8")
            after.write_text("# after\n", encoding="utf-8")

            provenance = build_provenance(
                data,
                before,
                after,
                command=[
                    "evalcanary",
                    "diff",
                    "--data",
                    str(data),
                    "--before",
                    str(before),
                    "--after",
                    str(after),
                    "--out",
                    str(root / "private" / "report"),
                ],
            )
            serialized = json.dumps(provenance, sort_keys=True)
            self.assertNotIn(str(root), serialized)
            self.assertEqual(provenance["data"]["path"], "cases.jsonl")
            self.assertEqual(provenance["path_policy"], "basename-only")
            self.assertEqual(
                provenance["command"][-1],
                "report",
            )

    def test_windows_command_paths_are_sanitized_cross_platform(self) -> None:
        sanitized = sanitize_command(
            [
                "evalcanary",
                "diff",
                "--data",
                r"C:\\Users\\Alice\\private\\cases.jsonl",
                "--python",
                r"D:\\venvs\\eval\\python.exe",
            ]
        )
        self.assertEqual(sanitized[-3], "cases.jsonl")
        self.assertEqual(sanitized[-1], "python.exe")


if __name__ == "__main__":
    unittest.main()
