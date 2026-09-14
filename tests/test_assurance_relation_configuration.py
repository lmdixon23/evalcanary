from __future__ import annotations

import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.verify_assurance_relations import verify_delta, verify_semantics
from tests.assurance_helpers import clone_records, refresh_manifest, write_records

from evalcanary.assurance.engine import build_report
from evalcanary.assurance.numeric import canonical_json_text, canonical_sha256
from evalcanary.assurance.review_queue import build_review_queue
from evalcanary.assurance.schema import load_artifact
from evalcanary.assurance.security import redact_structured
from evalcanary.assurance.structural import generate_schemas, verify_checked_in_schemas


class RelationConfigurationTests(unittest.TestCase):
    def build(self, items):
        refresh_manifest(items)
        with TemporaryDirectory() as temp:
            artifact = load_artifact(write_records(Path(temp) / "input.jsonl", items))
        return artifact, build_report(artifact)

    def test_empty_and_exact_tolerance_configurations(self):
        for relation in ("same_label", "same_score_within_tolerance"):
            with self.subTest(relation=relation):
                items = clone_records(
                    relation=relation, numeric=relation != "same_label"
                )
                if relation != "same_label":
                    group = next(
                        x for x in items if x["record_type"] == "invariance_group"
                    )
                    group["relation_parameters"]["absolute_tolerance"] = Decimal(
                        "0.050000000000000000000000000001"
                    )
                artifact, report = self.build(items)
                self.assertEqual(
                    report["invariance_groups"][0]["relation_configuration"],
                    artifact.invariance_groups[0]["relation_parameters"],
                )
                self.assertEqual(verify_semantics(artifact, report), 1)

    def test_nine_accepted_privacy_canaries_are_only_references(self):
        for canary in (
            "sk-" + "SYNTHETIC_ONLY_" * 2,
            "C:\\synthetic-only\\private.txt",
            "/synthetic-only/private.txt",
        ):
            for field in ("first_label", "second_label", "tie_label"):
                with self.subTest(canary=canary, field=field):
                    items = clone_records(relation="swapped_preference")
                    items[0]["judgment_spec"]["label_space"].append(canary)
                    group = next(
                        x for x in items if x["record_type"] == "invariance_group"
                    )
                    group["relation_parameters"][field] = canary
                    artifact, report = self.build(items)
                    config = report["invariance_groups"][0]["relation_configuration"]
                    self.assertEqual(
                        report["judgment_spec"], artifact.header["judgment_spec"]
                    )
                    self.assertEqual(
                        report["judgment_spec"]["label_space"][
                            config[field + "_index"]
                        ],
                        canary,
                    )
                    self.assertTrue(
                        all(
                            type(value) is int or value is None
                            for value in config.values()
                        )
                    )
                    self.assertEqual(redact_structured(config), config)
                    self.assertNotIn(canary, canonical_json_text(config))
                    self.assertNotIn(
                        redact_structured(group["relation_parameters"])[field],
                        canonical_json_text(config),
                    )
                    self.assertEqual(verify_semantics(artifact, report), 1)

    def test_order_nonadjacent_labels_and_optional_tie(self):
        for labels, first, second, tie in (
            (["pass", "fail"], "fail", "pass", None),
            (["tie", "fail", "other", "pass"], "pass", "fail", None),
            (["tie", "fail", "other", "pass"], "pass", "fail", "tie"),
        ):
            with self.subTest(labels=labels, tie=tie):
                items = clone_records(relation="swapped_preference")
                items[0]["judgment_spec"]["label_space"] = labels
                group = next(x for x in items if x["record_type"] == "invariance_group")
                group["relation_parameters"] = {
                    "first_label": first,
                    "second_label": second,
                }
                if tie is not None:
                    group["relation_parameters"]["tie_label"] = tie
                artifact, report = self.build(items)
                self.assertEqual(
                    report["invariance_groups"][0]["relation_configuration"],
                    {
                        "first_label_index": labels.index(first),
                        "second_label_index": labels.index(second),
                        "tie_label_index": None if tie is None else labels.index(tie),
                    },
                )
                verify_semantics(artifact, report)

    def test_comparator_rejects_mutated_references_and_identity(self):
        artifact, report = self.build(clone_records(relation="swapped_preference"))
        mutations = [
            ("group_id", "wrong"),
            ("expected_relation", "same_label"),
            ("member_case_ids", ["case-2", "case-1"]),
            ("severity", "info"),
        ]
        for key, value in mutations:
            with self.subTest(key=key):
                changed = deepcopy(report)
                changed["invariance_groups"][0][key] = value
                with self.assertRaises(ValueError):
                    verify_semantics(artifact, changed)
        for value in (-1, 2, True, Decimal(0), "pass", None, 1):
            with self.subTest(index=value):
                changed = deepcopy(report)
                changed["invariance_groups"][0]["relation_configuration"][
                    "first_label_index"
                ] = value
                with self.assertRaises(ValueError):
                    verify_semantics(artifact, changed)
        for relation in ("same_label", "same_score_within_tolerance"):
            artifact, report = self.build(
                clone_records(relation=relation, numeric=True)
            )
            report["invariance_groups"][0]["relation_configuration"] = {
                "absolute_tolerance": Decimal("0.5")
            }
            with self.assertRaises(ValueError):
                verify_semantics(artifact, report)

    def test_delta_checks_all_semantics_and_mechanical_queue_ids(self):
        _, report = self.build(clone_records(numeric=True))
        before = deepcopy(report)
        for group in before["invariance_groups"]:
            group.pop("relation_configuration")
        before["report_id"] = None
        before["report_id"] = canonical_sha256(before)[:24]
        before_queue, after_queue = (
            build_review_queue(before),
            build_review_queue(report),
        )
        result = verify_delta(before, report, before_queue, after_queue)
        self.assertEqual(result["configuration_additions"], 1)
        for field, value in (
            ("warnings", ["changed"]),
            ("report_status", "PASS"),
            ("pairing", {}),
        ):
            changed = deepcopy(report)
            changed[field] = value
            changed["report_id"] = None
            changed["report_id"] = canonical_sha256(changed)[:24]
            with self.assertRaises(ValueError):
                verify_delta(before, changed, before_queue, after_queue)
        changed_queue = deepcopy(after_queue)
        changed_queue["items"][0]["review_rank"] = 1
        with self.assertRaises(ValueError):
            verify_delta(before, report, before_queue, changed_queue)

    def test_report_v1_extension_contract_requires_no_schema_change(self):
        schema = generate_schemas()["report"]
        self.assertEqual(
            schema["properties"]["invariance_groups"], {"$ref": "#/$defs/object_array"}
        )
        self.assertEqual(schema["$defs"]["object_array"]["items"], {"type": "object"})
        verify_checked_in_schemas()
