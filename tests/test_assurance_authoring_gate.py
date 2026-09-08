from __future__ import annotations

import csv
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import r4qg_compact_authoring as compact
from evalcanary.assurance.schema import load_artifact, load_contract

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTHORING_SURFACE = PROJECT_ROOT / "tests" / "r4qg_compact_authoring.py"
FIELDS = ("case_id", "role", "trial_key", "status", "label", "score")


def _write_rows(path: Path, rows: list[tuple[str, ...]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(FIELDS)
        writer.writerows(rows)
    return path


def _u_rows(*, repaired: bool) -> list[tuple[str, ...]]:
    outcomes = {
        "u-error": (
            ("determinate", "pass"),
            ("determinate", "pass") if repaired else ("error", ""),
        ),
        "u-route": (
            ("determinate", "pass"),
            ("determinate", "pass") if repaired else ("determinate", "fail"),
        ),
        "u-abstain": (("abstain", ""), ("abstain", "")),
        "u-steady": (("determinate", "pass"), ("determinate", "pass")),
    }
    return [
        (case_id, role, "pair-0", status, label, "")
        for case_id, role_outcomes in outcomes.items()
        for role, (status, label) in zip(
            ("baseline", "candidate"), role_outcomes, strict=True
        )
    ]


def _v_rows() -> list[tuple[str, ...]]:
    return [
        (case_id, role, pairing, "determinate", label, score)
        for case_id, label, scores in (
            ("v-rel-a", "pass", ("0.70", "0.75")),
            ("v-rel-b", "pass", ("0.72", "0.77")),
            ("v-repeat", "pass", ("0.80", "0.82")),
        )
        for role, score in zip(("baseline", "candidate"), scores, strict=True)
        for pairing in ("pair-0",)
    ]


class AssuranceAuthoringGateTests(unittest.TestCase):
    def test_project_formatted_maintained_surface_meets_280_line_target(self) -> None:
        source = AUTHORING_SURFACE.read_text(encoding="utf-8")
        maintained = [
            line
            for line in source.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(len(maintained), 280)
        self.assertLessEqual(len(maintained), 280)
        self.assertNotIn("# fmt:", source)
        self.assertNotIn(";", source)

    def test_u_u2_v_builders_validate_with_no_u2_mapping_fork(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            u_rows = _write_rows(root / "u.csv", _u_rows(repaired=False))
            u2_rows = _write_rows(root / "u2.csv", _u_rows(repaired=True))
            v_rows = _write_rows(root / "v.csv", _v_rows())

            u_packet, u_contract = compact.build_u(u_rows, "2.0")
            u2_packet, u2_contract = compact.build_u(u2_rows, "2.1")
            v_packet, v_contract = compact.build_v(v_rows)
            artifacts = {}
            for name, packet, contract in (
                ("u", u_packet, u_contract),
                ("u2", u2_packet, u2_contract),
                ("v", v_packet, v_contract),
            ):
                input_path = packet.write(root / f"{name}.jsonl")
                contract_path = contract.write(
                    root / f"{name}.json", artifact=input_path
                )
                artifacts[name] = load_artifact(input_path)
                load_contract(contract_path, artifacts[name])

        self.assertEqual(u_contract.canonical_bytes(), u2_contract.canonical_bytes())
        source = AUTHORING_SURFACE.read_text(encoding="utf-8")
        self.assertEqual(source.count("def build_u("), 1)
        self.assertNotIn("def build_u2(", source)

        evaluations = {
            name: {item["role"]: item for item in artifact.header["evaluations"]}
            for name, artifact in artifacts.items()
        }
        self.assertEqual(evaluations["u"]["baseline"], evaluations["u2"]["baseline"])
        before = deepcopy(evaluations["u"]["candidate"])
        after = deepcopy(evaluations["u2"]["candidate"])
        for field in (
            "evaluation_id",
            "evaluator_version",
            "evaluator_fingerprint_sha256",
        ):
            before.pop(field)
            after.pop(field)
        self.assertEqual(before, after)
        self.assertEqual(
            evaluations["u2"]["candidate"]["evaluator_components"]["parser"][
                "identity"
            ],
            "route-parser@2.0",
        )
        self.assertEqual(
            evaluations["u2"]["candidate"]["evaluator_components"][
                "aggregation_policy"
            ]["identity"],
            "route-aggregation@2.0",
        )


if __name__ == "__main__":
    unittest.main()
