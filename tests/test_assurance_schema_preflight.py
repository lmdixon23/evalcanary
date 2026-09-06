from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests.assurance_helpers import (
    clone_records,
    contract,
    rule,
    write_json,
    write_records,
)

from evalcanary.assurance.engine import build_report
from evalcanary.assurance.preflight import (
    MAX_PREFLIGHT_DIAGNOSTICS,
    preflight_paths,
)
from evalcanary.assurance.review_queue import build_review_queue
from evalcanary.assurance.schema import load_artifact, load_contract
from evalcanary.assurance.structural import (
    FIELD_REGISTRY,
    SCHEMA_FILENAMES,
    canonical_schema_bytes,
    generate_schemas,
    verify_checked_in_schemas,
)
from evalcanary.cli import main


class AssuranceSchemaPreflightTests(unittest.TestCase):
    def test_schema_bytes_ids_layers_registry_and_drift(self) -> None:
        schemas = generate_schemas()
        self.assertEqual(set(schemas), set(SCHEMA_FILENAMES))
        for selector, document in schemas.items():
            with self.subTest(selector=selector):
                self.assertEqual(
                    json.loads(canonical_schema_bytes(selector)), document
                )
                self.assertEqual(
                    document["$schema"],
                    "https://json-schema.org/draft/2020-12/schema",
                )
                self.assertTrue(document["$id"].startswith("urn:evalcanary:schema:"))
                self.assertEqual(
                    set(document["x-evalcanary-validation-layers"]),
                    {"STRUCTURAL_SCHEMA", "RUNTIME_SEMANTICS"},
                )
        input_defs = schemas["input-record"]["$defs"]
        for record_type in (
            "header",
            "case",
            "trial",
            "critical_group",
            "invariance_group",
            "anchor_set",
            "anchor",
        ):
            self.assertEqual(
                set(input_defs[record_type]["required"]),
                set(FIELD_REGISTRY[record_type]),
            )
            self.assertFalse(input_defs[record_type]["additionalProperties"])
        verify_checked_in_schemas()

    def test_runtime_outputs_conform_to_closed_top_level_schema_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = write_records(root / "input.jsonl", clone_records())
            contract_value = contract(
                rule(
                    "determinate_coverage",
                    parameters={"role": "candidate"},
                    operator="gte",
                    threshold=0,
                )
            )
            contract_path = write_json(root / "contract.json", contract_value)
            artifact = load_artifact(input_path)
            loaded_contract = load_contract(contract_path, artifact)
            report = build_report(artifact, loaded_contract)
            queue = build_review_queue(report)
        schemas = generate_schemas()
        self.assertEqual(
            set(contract_value), set(schemas["contract"]["required"])
        )
        self.assertEqual(set(report), set(schemas["report"]["required"]))
        self.assertEqual(
            set(queue), set(schemas["review-queue"]["required"])
        )
        for record in clone_records():
            definition = schemas["input-record"]["$defs"][record["record_type"]]
            self.assertEqual(set(record), set(definition["required"]))

    def test_schema_command_is_exact_and_unknown_selector_exits_three(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["schema", "contract"]), 0)
        self.assertEqual(stdout.getvalue().encode(), canonical_schema_bytes("contract"))
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(main(["schema", "unknown"]), 3)
        self.assertIn("Unknown schema selector", stderr.getvalue())

    def test_preflight_valid_hard_failure_contract_returns_zero_without_packet(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = write_records(root / "input.jsonl", clone_records())
            contract_path = write_json(
                root / "contract.json",
                contract(
                    rule(
                        "determinate_coverage",
                        parameters={"role": "candidate"},
                        operator="eq",
                        threshold=0,
                    )
                ),
            )
            output = root / "must-not-exist"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "migrate",
                        "--preflight",
                        "--input",
                        str(input_path),
                        "--contract",
                        str(contract_path),
                        "--out",
                        str(output),
                    ]
                )
            document = json.loads(stdout.getvalue())
            self.assertEqual(result, 0)
            self.assertTrue(document["valid"])
            self.assertEqual(document["mode"], "VALIDATION_ONLY")
            self.assertNotIn("report_status", document)
            self.assertFalse(output.exists())

    def test_preflight_aggregates_independent_safe_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            items = clone_records()
            items[0]["corpus"] = []
            trial = next(item for item in items if item["record_type"] == "trial")
            trial["status"] = "PRIVATE_STATUS_CANARY"
            input_path = write_records(root / "input.jsonl", items)
            bad_rule = rule(
                "determinate_coverage",
                parameters={"PRIVATE_PARAMETER_CANARY": "PRIVATE_VALUE_CANARY"},
                severity="review",
                missing_evidence="hard_fail",
            )
            contract_path = write_json(root / "contract.json", contract(bad_rule))
            result = preflight_paths(input_path, contract_path=contract_path)
        document = result.document()
        codes = {item["code"] for item in document["diagnostics"]}
        self.assertFalse(result.valid)
        self.assertGreaterEqual(document["diagnostic_count"], 5)
        self.assertIn("EXPECTED_OBJECT", codes)
        self.assertIn("UNKNOWN_ENUM_VALUE", codes)
        self.assertIn("MISSING_METRIC_PARAMETER", codes)
        self.assertIn("UNSUPPORTED_METRIC_PARAMETER", codes)
        self.assertIn("INCOMPATIBLE_MISSING_EVIDENCE", codes)
        rendered = json.dumps(document, sort_keys=True)
        for private in (
            "PRIVATE_STATUS_CANARY",
            "PRIVATE_PARAMETER_CANARY",
            "PRIVATE_VALUE_CANARY",
        ):
            self.assertNotIn(private, rendered)

    def test_preflight_caps_diagnostics_and_reports_omission(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            items = clone_records()
            for index in range(MAX_PREFLIGHT_DIAGNOSTICS + 10):
                items[0][f"private.unknown-{index}"] = index
            result = preflight_paths(write_records(root / "input.jsonl", items))
        self.assertEqual(len(result.diagnostics), MAX_PREFLIGHT_DIAGNOSTICS)
        self.assertEqual(result.diagnostics_omitted, 10)
        rendered = json.dumps(result.document(), sort_keys=True)
        self.assertNotIn("private.unknown", rendered)

    def test_preflight_rejects_invalid_numeric_token_with_exit_three(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = write_records(root / "input.jsonl", clone_records())
            data = path.read_bytes().replace(b'"source_order":0', b'"source_order":1e1001', 1)
            path.write_bytes(data)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["migrate", "--preflight", "--input", str(path)])
        self.assertEqual(code, 3)
        self.assertIn("INVALID_JSON", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
