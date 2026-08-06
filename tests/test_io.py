from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from evalcanary.errors import InputValidationError
from evalcanary.io import load_cases


class LoadCasesTests(unittest.TestCase):
    def test_loads_unique_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cases.jsonl"
            path.write_text('{"id":1,"output":"x"}\n{"id":"2","output":"y"}\n', encoding="utf-8")
            cases = load_cases(path)
            self.assertEqual([case.case_id for case in cases], ["1", "2"])

    def test_rejects_duplicate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cases.jsonl"
            path.write_text('{"id":"a"}\n{"id":"a"}\n', encoding="utf-8")
            with self.assertRaises(InputValidationError):
                load_cases(path)

    def test_rejects_empty_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cases.jsonl"
            path.write_text("\n", encoding="utf-8")
            with self.assertRaises(InputValidationError):
                load_cases(path)


if __name__ == "__main__":
    unittest.main()
