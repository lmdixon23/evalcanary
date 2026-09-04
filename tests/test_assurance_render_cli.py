from __future__ import annotations

import html
import os
import re
import socket
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from tests.assurance_helpers import (
    clone_records,
    component,
    contract,
    rule,
    write_json,
    write_records,
)

from evalcanary.assurance.engine import build_report
from evalcanary.assurance.numeric import canonical_json_text
from evalcanary.assurance.renderers import (
    html_text,
    json_bytes,
    markdown_text,
    write_report_bundle,
)
from evalcanary.assurance.schema import Limits, load_artifact
from evalcanary.cli import main
from evalcanary.errors import InputValidationError


class AssuranceRendererTests(unittest.TestCase):
    def _report(self, root: Path, *, sensitive: bool = False) -> dict[str, object]:
        items = clone_records(with_anchors=True)
        if sensitive:
            trial = next(item for item in items if item.get("record_type") == "trial")
            trial.update(
                {
                    "status": "error",
                    "label": None,
                    "reason": "Authorization: Bearer PRIVATE_REASON_123",
                    "details": {
                        "provider_request_id": "PRIVATE_REQUEST_456",
                        "path": "C:\\Users\\PrivatePerson\\payload.txt",
                    },
                    "error": {
                        "error_class": "ParserError",
                        "message": "sk-PRIVATE_ERROR_789",
                    },
                }
            )
        artifact = load_artifact(write_records(root / "input.jsonl", items))
        return build_report(artifact)

    def test_cross_format_fact_parity_and_accessible_scriptless_html(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._report(Path(temp))
        canonical = canonical_json_text(report)
        markdown = markdown_text(report)
        rendered_html = html_text(report)
        markdown_fact = next(
            line[4:] for line in markdown.splitlines() if line.startswith("    {")
        )
        html_match = re.search(r"<pre>(.*?)</pre>", rendered_html, flags=re.DOTALL)
        self.assertIsNotNone(html_match)
        self.assertEqual(markdown_fact, canonical)
        assert html_match is not None
        self.assertEqual(html.unescape(html_match.group(1)), canonical)
        self.assertEqual(json_bytes(report), canonical.encode("utf-8") + b"\n")
        self.assertNotIn("<script", rendered_html.lower())
        self.assertIsNone(re.search(r"\son[a-z]+\s*=", rendered_html.lower()))
        self.assertIn("Content-Security-Policy", rendered_html)
        self.assertIn("<caption>", rendered_html)
        self.assertIn('scope="col"', rendered_html)
        self.assertIn(":focus-visible", rendered_html)
        for heading in (
            "Contract findings",
            "Critical groups",
            "Invariance results",
            "Human-anchor diagnostics",
            "Repeat and pairing diagnostics",
            "Provenance completeness",
            "Limitations",
            "Canonical facts",
        ):
            self.assertIn(f"## {heading}", markdown)
            self.assertIn(f">{heading}</h2>", rendered_html)
        self.assertLess(markdown.index("## Contract findings"), markdown.index("## Canonical facts"))
        self.assertLess(rendered_html.index("Contract findings"), rendered_html.index("Canonical facts"))

    def test_metadata_only_output_omits_content_secrets_paths_and_annotators(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self._report(root, sensitive=True)
            rendered = "\n".join(
                (canonical_json_text(report), markdown_text(report), html_text(report))
            )
            for canary in (
                "PRIVATE_REASON_123",
                "PRIVATE_REQUEST_456",
                "PrivatePerson",
                "payload.txt",
                "PRIVATE_ERROR_789",
                "person-0",
                str(root),
            ):
                self.assertNotIn(canary, rendered)
            self.assertIn('"mode":"metadata_only"', rendered)
            trial = report["cases"][0]["trials"]["baseline"][0]  # type: ignore[index]
            self.assertEqual(trial["error_class"], "ParserError")
            self.assertTrue(trial["reason"]["omitted"])
            self.assertTrue(trial["details"]["omitted"])
            self.assertTrue(trial["error_message"]["omitted"])

    def test_dangerous_links_never_become_clickable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            items = clone_records()
            items[0]["provenance"]["source_url"] = component(
                "https://127.0.0.1/private?token=secret"
            )
            report = build_report(load_artifact(write_records(root / "input.jsonl", items)))
        self.assertNotIn("127.0.0.1", markdown_text(report))
        self.assertNotIn("127.0.0.1", html_text(report))
        source = report["provenance"]["artifact"]["source_url"]
        self.assertIsNone(source["identity"])
        self.assertTrue(source["identity_omitted"])

    def test_output_size_preflight_leaves_no_report_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self._report(root)
            output = root / "too-large"
            values = dict(Limits().values)
            values["json_report_bytes"] = 1
            with self.assertRaisesRegex(InputValidationError, "json_report_bytes"):
                write_report_bundle(report, output, limits=Limits(values=values))
            self.assertFalse(output.exists())

    def test_source_conflict_file_destination_and_symlink_targets_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self._report(root)
            with self.assertRaisesRegex(InputValidationError, "source input"):
                write_report_bundle(
                    report,
                    root,
                    limits=Limits(),
                    source_paths=(root / "report.json",),
                )
            destination_file = root / "not-a-directory"
            destination_file.write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(InputValidationError, "not a directory"):
                write_report_bundle(report, destination_file, limits=Limits())
            with patch(
                "pathlib.Path.is_symlink", return_value=True
            ), self.assertRaisesRegex(InputValidationError, "symbolic link"):
                write_report_bundle(report, root / "linked", limits=Limits())

    def test_write_failure_removes_temporary_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self._report(root)
            output = root / "report"
            with patch.object(
                os, "replace", side_effect=OSError("blocked")
            ), self.assertRaisesRegex(InputValidationError, "written safely"):
                write_report_bundle(report, output, limits=Limits())
            self.assertEqual(list(output.glob(".*.tmp")), [])
            self.assertEqual(list(output.glob("report.*")), [])

    def test_core_pipeline_attempts_no_network_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = write_records(root / "input.jsonl", clone_records())
            with (
                patch.object(socket.socket, "connect", side_effect=AssertionError("network")),
                patch.object(socket, "create_connection", side_effect=AssertionError("network")),
                patch.object(urllib.request, "urlopen", side_effect=AssertionError("network")),
            ):
                artifact = load_artifact(input_path)
                report = build_report(artifact)
                write_report_bundle(report, root / "out", limits=artifact.limits)


class AssuranceCliTests(unittest.TestCase):
    def test_migrate_exit_code_mapping_and_report_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            valid = write_records(root / "valid.jsonl", clone_records())
            no_contract_out = root / "no-contract"
            self.assertEqual(
                main(["migrate", "--input", str(valid), "--out", str(no_contract_out)]),
                0,
            )
            self.assertTrue((no_contract_out / "report.json").is_file())

            hard_contract = write_json(
                root / "hard.json", contract(rule("corpus_equal", operator="ne"))
            )
            self.assertEqual(
                main(
                    [
                        "migrate",
                        "--input",
                        str(valid),
                        "--contract",
                        str(hard_contract),
                        "--out",
                        str(root / "hard"),
                    ]
                ),
                2,
            )

            review_items = clone_records()
            before = review_items[0]["evaluations"][0]["context_components"]["runtime"]
            after = component("python-3.14")
            review_items[0]["evaluations"][1]["context_components"]["runtime"] = after
            review_items[0]["allowed_context_differences"] = [
                {
                    "component": "runtime",
                    "expected_baseline_component_value": before,
                    "expected_candidate_component_value": after,
                    "rationale": "Exact reviewed difference.",
                    "reviewer_id": "reviewer-1",
                    "disposition": "not_isolated_review_required",
                }
            ]
            review = write_records(root / "review.jsonl", review_items)
            self.assertEqual(
                main(["migrate", "--input", str(review), "--out", str(root / "review")]),
                4,
            )

            missing_items = clone_records()
            missing_items[:] = [
                item
                for item in missing_items
                if item.get("trial_id") != "case-2-candidate-0"
            ]
            missing = write_records(root / "missing.jsonl", missing_items)
            self.assertEqual(
                main(["migrate", "--input", str(missing), "--out", str(root / "missing")]),
                3,
            )

            invalid = root / "invalid.jsonl"
            invalid.write_bytes(b"not-json\n")
            self.assertEqual(
                main(["migrate", "--input", str(invalid), "--out", str(root / "invalid")]),
                3,
            )

    def test_invalid_contract_configuration_exits_three(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            valid = write_records(root / "valid.jsonl", clone_records())
            bad_rule = rule("determinate_coverage", parameters={"role": "candidate"})
            bad_rule["parameters"]["extra"] = True
            bad_contract = write_json(root / "bad.json", contract(bad_rule))
            self.assertEqual(
                main(
                    [
                        "migrate",
                        "--input",
                        str(valid),
                        "--contract",
                        str(bad_contract),
                        "--out",
                        str(root / "bad"),
                    ]
                ),
                3,
            )
            self.assertEqual(
                main(
                    [
                        "migrate",
                        "--input",
                        str(valid),
                        "--contract",
                        str(root / "missing-contract.json"),
                        "--out",
                        str(root / "missing-contract"),
                    ]
                ),
                3,
            )
            self.assertEqual(
                main(
                    [
                        "migrate",
                        "--input",
                        str(valid),
                        "--limits",
                        str(root / "missing-limits.json"),
                        "--out",
                        str(root / "missing-limits"),
                    ]
                ),
                3,
            )


if __name__ == "__main__":
    unittest.main()
