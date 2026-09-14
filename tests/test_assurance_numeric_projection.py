from __future__ import annotations

import unittest
from copy import deepcopy
from decimal import Decimal, localcontext
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests.assurance_helpers import (
    clone_records,
    refresh_manifest,
    trial,
    write_records,
)

from evalcanary.assurance.engine import build_report
from evalcanary.assurance.numeric import canonical_json_bytes
from evalcanary.assurance.numeric_projection import NUMERIC_NOTE, numeric_projection
from evalcanary.assurance.renderers import _projection_facts, html_text, markdown_text
from evalcanary.assurance.schema import load_artifact


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = {}
        self.caption = ""
        self.cell = None
        self.row = []
        self.in_caption = False

    def handle_starttag(self, tag, attrs):
        if tag == "caption":
            self.caption = ""
            self.in_caption = True
        elif tag == "tr":
            self.row = []
        elif tag in ("th", "td"):
            self.cell = ""

    def handle_data(self, data):
        if self.in_caption:
            self.caption += data
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag == "caption":
            self.in_caption = False
            self.tables[self.caption] = []
        elif tag in ("th", "td"):
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr":
            self.tables[self.caption].append(tuple(self.row))


class NumericProjectionTests(unittest.TestCase):
    def build(self, items):
        refresh_manifest(items)
        with TemporaryDirectory() as temp:
            return build_report(
                load_artifact(write_records(Path(temp) / "input.jsonl", items))
            )

    def pairs(self, values, *, relation=None):
        items = clone_records(numeric=True, relation=relation)
        items = [item for item in items if item["record_type"] != "trial"]
        for index, (first, second) in enumerate(values):
            for role, score in (("baseline", first), ("candidate", second)):
                items.append(
                    trial(
                        "case-1",
                        role,
                        score=None if score is None else Decimal(score),
                        source_order=index,
                        pairing_key=f"p{index:03}",
                    )
                )
        items.extend(
            [
                trial("case-2", role, score=Decimal("1"), pairing_key=None)
                for role in ("baseline", "candidate")
            ]
        )
        return self.build(items)

    def tables(self, report):
        return {
            caption: rows
            for caption, _, rows in _projection_facts(report)["numeric_tables"]
        }

    def test_signed_deltas_missingness_exact_sum_and_denominator(self):
        report = self.pairs(
            [
                ("0.60", "0.62"),
                ("0.61", "0.70"),
                ("0.90", "0.86"),
                ("0.91", "0.72"),
                ("0.80", "0.79"),
                ("0.75", None),
            ]
        )
        report["cases"][0]["trials"]["candidate"][-1]["status"] = "error"
        tables = self.tables(report)
        rows = tables["Paired score evidence"]
        self.assertEqual(
            [row[4] for row in rows],
            ["+0.02", "+0.09", "-0.04", "-0.19", "-0.01", "unavailable"],
        )
        self.assertEqual(
            rows[-1][2:],
            (
                "0.75",
                "unavailable",
                "unavailable",
                "determinate",
                "error",
                "incomplete",
            ),
        )
        self.assertEqual(
            tables["Complete-pair numeric summary"],
            [("6", "5", "1", "-0.13", "-0.026", "5")],
        )
        before = canonical_json_bytes(report)
        with (
            patch("builtins.open", side_effect=AssertionError("no input side channel")),
            patch(
                "evalcanary.assurance.schema.load_artifact",
                side_effect=AssertionError("no input side channel"),
            ),
        ):
            markdown_text(report)
            html_text(report)
        self.assertEqual(canonical_json_bytes(report), before)

    def test_missing_baseline_candidate_both_zero_and_empty_summary(self):
        for pairs, expected in (
            (
                [(None, "0"), ("0", None), (None, None)],
                ("3", "0", "3", "0", "unavailable", "0"),
            ),
            ([("-0.0", "0.00")], ("1", "1", "0", "0", "0", "1")),
            ([], ("0", "0", "0", "0", "unavailable", "0")),
        ):
            with self.subTest(pairs=pairs):
                tables = self.tables(self.pairs(pairs))
                self.assertEqual(tables["Complete-pair numeric summary"], [expected])
                self.assertNotIn("-0", str(tables))
                for row in tables["Paired score evidence"]:
                    if row[-1] == "incomplete":
                        self.assertEqual(row[4], "unavailable")

    def test_exact_rational_mean_and_decimal_context_independence(self):
        report = self.pairs([("0", "1"), ("0", "0"), ("0", "0")])
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(
                self.tables(report)["Complete-pair numeric summary"][0],
                ("3", "3", "0", "1", "1/3", "3"),
            )
        report = self.pairs(
            [("0.123456789012345678901234567890", "0.123456789012345678901234567891")]
        )
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(
                self.tables(report)["Paired score evidence"][0][4],
                "+0.000000000000000000000000000001",
            )

    def test_numeric_invariance_spread_and_repeat_ranges(self):
        items = clone_records(numeric=True, relation="same_score_within_tolerance")
        items[0]["judgment_spec"]["repeat_score_tolerance"] = Decimal("0.05")
        group = next(
            item for item in items if item["record_type"] == "invariance_group"
        )
        group["relation_parameters"]["absolute_tolerance"] = Decimal("0.05")
        values = iter(("0.60", "0.62", "0.61", "0.70"))
        for item in items:
            if item["record_type"] == "trial":
                item["score"] = Decimal(next(values))
        report = self.build(items)
        rows = self.tables(report)["Numeric invariance evidence"]
        self.assertEqual(
            [row[3:7] for row in rows],
            [("2", "0.01", "0.05", "satisfied"), ("2", "0.08", "0.05", "violated")],
        )
        report = self.pairs([("0.90", "0.86"), ("0.91", "0.72")])
        rows = self.tables(report)["Repeated score ranges"]
        self.assertEqual(
            [row[2:7] for row in rows],
            [("2", "2", "0.9", "0.91", "0.01"), ("2", "2", "0.72", "0.86", "0.14")],
        )
        # The projection prints an existing state even if it differs from what a
        # fresh tolerance comparison might suggest. It must not decide again.
        report["repeat_diagnostics"]["candidate"]["cases"][0]["score_instability"] = (
            "not_configured"
        )
        self.assertEqual(
            self.tables(report)["Repeated score ranges"][1][-1], "not_configured"
        )

    def test_insufficient_invariance_and_old_report_never_infer_tolerance(self):
        report = self.build(
            clone_records(numeric=True, relation="same_score_within_tolerance")
        )
        report["cases"][0]["trials"]["candidate"][0]["score"] = None
        report["invariance_groups"][0]["roles"]["candidate"][0]["result"] = (
            "not_evaluable"
        )
        report["invariance_groups"][0].pop("relation_configuration")
        rows = self.tables(report)["Numeric invariance evidence"]
        self.assertEqual(
            rows[1][3:],
            (
                "1",
                "unavailable",
                "unavailable",
                "not_evaluable",
                "insufficient numeric members",
            ),
        )
        # Unkeyed repeated trials have no numeric instance selection by position.
        report["cases"][1]["trials"]["baseline"] *= 2
        rows = self.tables(report)["Numeric invariance evidence"]
        self.assertEqual(rows[0][3:5], ("1", "unavailable"))

    def test_caps_determinism_and_summary_includes_omitted_pairs(self):
        report = self.pairs([("0", "1")] * 31)
        facts = _projection_facts(report)
        self.assertIn(("paired numeric trials", "31", "25", "6"), facts["projection"])
        self.assertEqual(
            self.tables(report)["Complete-pair numeric summary"],
            [("31", "31", "0", "31", "1", "31")],
        )
        expected = numeric_projection(
            report,
            case_cap=1,
            invariance_caps={"satisfied": 1, "violated": 1, "not_evaluable": 1},
        )
        self.assertIn(
            ("repeated numeric case roles", "2", "1", "1"), expected["projection"]
        )
        reversed_report = deepcopy(report)
        reversed_report["cases"].reverse()
        self.assertEqual(
            expected,
            numeric_projection(
                reversed_report,
                case_cap=1,
                invariance_caps={"satisfied": 1, "violated": 1, "not_evaluable": 1},
            ),
        )
        invariant = self.build(
            clone_records(numeric=True, relation="same_score_within_tolerance")
        )
        group = invariant["invariance_groups"][0]
        invariant["invariance_groups"] = [
            {**deepcopy(group), "group_id": f"g{i:03}"} for i in range(13)
        ]
        self.assertIn(
            ("numeric invariance baseline satisfied", "13", "10", "3"),
            _projection_facts(invariant)["projection"],
        )

    def test_html_markdown_numeric_fact_parity_and_noninference(self):
        report = self.pairs(
            [("0", "1"), ("1", "0"), ("0", "0")], relation="same_score_within_tolerance"
        )
        md, markup = markdown_text(report), html_text(report)
        parsed = TableParser()
        parsed.feed(markup)
        for caption, headers, rows in _projection_facts(report)["numeric_tables"]:
            self.assertEqual(parsed.tables[caption], [headers, *rows])
            section = (
                md.split(f"### {caption}\n", 1)[1]
                .split("\n###", 1)[0]
                .split("\n## ", 1)[0]
            )
            actual = [
                tuple(cell.strip() for cell in line.strip("| ").split("|"))
                for line in section.splitlines()
                if line.startswith("| ")
            ][2:]
            self.assertEqual(actual, rows)
        self.assertIn(NUMERIC_NOTE, md)
        self.assertIn("Delta signs do not establish improvement", markup)
        for forbidden in (
            "<script",
            "fetch(",
            "positive = improvement",
            "negative = regression",
        ):
            self.assertNotIn(forbidden, markup)

    def test_categorical_reports_have_no_numeric_projection(self):
        report = self.build(clone_records())
        self.assertEqual(_projection_facts(report)["numeric_tables"], [])
        for text in (markdown_text(report), html_text(report)):
            self.assertNotIn("Paired score evidence", text)
            self.assertNotIn(NUMERIC_NOTE, text)
