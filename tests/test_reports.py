from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from evalcanary.compare import compare_verdicts
from evalcanary.io import load_cases
from evalcanary.models import Verdict
from evalcanary.policy import evaluate_policy
from evalcanary.reports import html_text, markdown_text


class ReportTests(unittest.TestCase):
    def test_report_escapes_content_and_has_accessible_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "cases.jsonl"
            before_file = root / "before.py"
            after_file = root / "after.py"
            data.write_text('{"id":"<case>","output":"secret"}\n', encoding="utf-8")
            before_file.write_text("# before\n", encoding="utf-8")
            after_file.write_text("# after\n", encoding="utf-8")
            summary = compare_verdicts(
                load_cases(data),
                [Verdict("<case>", True, reason="<old>")],
                [Verdict("<case>", False, reason="<new>")],
                data_path=data,
                before_path=before_file,
                after_path=after_file,
                bootstrap_replicates=200,
            )
            summary = evaluate_policy(summary, {})
            html_report = html_text(summary)
            self.assertIn("&lt;case&gt;", html_report)
            self.assertNotIn("secret", html_report)
            self.assertIn('aria-labelledby="transition-heading"', html_report)
            self.assertIn('table class="responsive"', html_report)
            self.assertIn('data-label="Transition"', html_report)
            self.assertIn("@media (max-width:620px)", html_report)
            self.assertIn("Source diff omitted by default", html_report)
            self.assertNotIn("# before", html_report)
            self.assertIn("EvalCanary evaluator migration report", markdown_text(summary))


if __name__ == "__main__":
    unittest.main()
