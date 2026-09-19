"""Public brand migration must preserve the existing machine contracts."""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import json
import re
import tempfile
import tomllib
import unittest
from pathlib import Path

from tests.assurance_helpers import contract, records, rule, write_json, write_records

from evalcanary import __version__
from evalcanary.assurance.engine import build_report
from evalcanary.assurance.numeric import canonical_json_bytes
from evalcanary.assurance.renderers import write_report_bundle
from evalcanary.assurance.review_queue import build_review_queue
from evalcanary.assurance.schema import Limits, load_artifact, load_contract
from evalcanary.cli import _build_parser, main

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads(
    (ROOT / "tests/fixtures/migration/identity-v1.json").read_text(encoding="utf-8")
)


class BrandMigrationTests(unittest.TestCase):
    def test_distribution_import_separation_and_no_runtime_dependencies(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]
        self.assertEqual(project["name"], "replaydocket")
        self.assertEqual(project["version"], __version__)
        self.assertEqual(project["dependencies"], [])
        self.assertEqual(importlib.import_module("evalcanary").__name__, "evalcanary")
        self.assertEqual(
            importlib.import_module("evalcanary.assurance").__name__,
            "evalcanary.assurance",
        )

    def test_console_aliases_use_one_maintained_entry_point(self) -> None:
        scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]["scripts"]
        self.assertEqual(
            scripts,
            {"replaydocket": "evalcanary.cli:main", "evalcanary": "evalcanary.cli:main"},
        )
        module_name, attribute = scripts["replaydocket"].split(":")
        self.assertIs(getattr(importlib.import_module(module_name), attribute), main)

    def test_help_version_and_legacy_default_paths(self) -> None:
        for option in ("--help", "--version"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as exc:
                main([option])
            self.assertEqual(exc.exception.code, 0)
            self.assertIn("ReplayDocket", output.getvalue())
        parser = _build_parser()
        self.assertEqual(parser.parse_args(["demo"]).out, Path("evalcanary-demo"))
        self.assertEqual(
            parser.parse_args(["migrate", "--input", "input.jsonl"]).out,
            Path("evalcanary-assurance-report"),
        )
        self.assertEqual(
            parser.parse_args(
                ["diff", "--data", "x", "--before", "a", "--after", "b"]
            ).out,
            Path("evalcanary-report"),
        )

    def test_versioned_schema_bytes_and_extension_keys_are_unchanged(self) -> None:
        for filename, expected in LOCK["schema_sha256"].items():
            data = (ROOT / "src/evalcanary/assurance/schemas" / filename).read_bytes()
            with self.subTest(schema=filename):
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected)
                schema = json.loads(data)
                self.assertTrue(schema["$id"].startswith("urn:evalcanary:schema:"))
                self.assertIn("x-evalcanary-validation-layers", schema)

    def test_canonical_reports_queues_and_machine_filenames_are_unchanged(self) -> None:
        for numeric in (False, True):
            with self.subTest(numeric=numeric), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source = write_records(root / "input.jsonl", records(numeric=numeric))
                policy = write_json(
                    root / "contract.json", contract(rule("corpus_equal"))
                )
                artifact = load_artifact(source)
                report = build_report(artifact, load_contract(policy, artifact))
                queue = build_review_queue(report)
                before = canonical_json_bytes(report)
                expected = LOCK["assurance_vectors"][str(numeric).lower()]
                self.assertEqual(hashlib.sha256(before).hexdigest(), expected["report_sha256"])
                self.assertEqual(
                    hashlib.sha256(canonical_json_bytes(queue)).hexdigest(),
                    expected["queue_sha256"],
                )
                self.assertEqual(report["report_id"], expected["report_id"])
                self.assertEqual(report["schema_version"], "evaluator-assurance-report-v1")
                self.assertEqual(queue["generated_by"]["name"], "evalcanary")
                output = root / "out"
                write_report_bundle(report, output, limits=Limits())
                self.assertEqual(canonical_json_bytes(report), before)
                self.assertEqual((output / "report.json").read_bytes(), before + b"\n")
                self.assertEqual(
                    {p.name for p in output.iterdir()},
                    {"report.json", "report.md", "report.html",
                     "review-queue.json", "review-queue.md"},
                )
                self.assertEqual(
                    (output / "review-queue.json").read_bytes(),
                    canonical_json_bytes(queue) + b"\n",
                )
                self.assertIn("ReplayDocket", (output / "report.md").read_text(encoding="utf-8"))
                self.assertIn("ReplayDocket", (output / "report.html").read_text(encoding="utf-8"))

    def test_action_environment_contract_and_historical_address(self) -> None:
        action = (ROOT / "action.yml").read_text(encoding="utf-8")
        expected = {
            "EVALCANARY_ACTION_PATH", "EVALCANARY_INPUT_DATA", "EVALCANARY_INPUT_BEFORE",
            "EVALCANARY_INPUT_AFTER", "EVALCANARY_INPUT_POLICY", "EVALCANARY_INPUT_SLICE",
            "EVALCANARY_INPUT_OUTPUT", "EVALCANARY_INPUT_TIMEOUT",
            "EVALCANARY_INPUT_BOOTSTRAP_REPLICATES", "EVALCANARY_INPUT_BOOTSTRAP_SEED",
            "EVALCANARY_INPUT_PYTHON", "EVALCANARY_INPUT_INCLUDE_CONTENT",
            "EVALCANARY_INPUT_INCLUDE_SOURCE_DIFF",
        }
        self.assertEqual(set(re.findall(r"EVALCANARY_[A-Z_]+", action)), expected)
        self.assertNotIn("REPLAYDOCKET_", action)
        self.assertIn(
            "lmdixon23/evalcanary@v0.1.1",
            (ROOT / "README.md").read_text(encoding="utf-8"),
        )

    def test_historical_changelog_is_not_rebranded(self) -> None:
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        tail = text[text.index("## 0.1.1 - "):]
        self.assertEqual(
            hashlib.sha256(tail.encode("utf-8")).hexdigest(),
            LOCK["historical_changelog_tail_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
