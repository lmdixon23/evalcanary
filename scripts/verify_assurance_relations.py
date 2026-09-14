"""Verify source/report relation semantics and the additive report/queue delta.

Run with PYTHONPATH=src: python scripts/verify_assurance_relations.py INPUT REPORT
Optional: --before-report OLD --before-queue OLD_QUEUE --queue QUEUE.
Only validated source declarations and canonical facts participate in the proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

from evalcanary.assurance.numeric import canonical_json_bytes, canonical_sha256
from evalcanary.assurance.review_queue import resolve_pointer
from evalcanary.assurance.schema import AssuranceArtifact, load_artifact


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify_semantics(artifact: AssuranceArtifact, report: dict[str, Any]) -> int:
    """Resolve references independently of the canonical construction function."""
    source_groups = artifact.invariance_groups
    report_groups = report["invariance_groups"]
    require(len(source_groups) == len(report_groups), "Group count differs.")
    indexed = {group["group_id"]: group for group in report_groups}
    require(len(indexed) == len(report_groups), "Duplicate report group identity.")
    labels = report["judgment_spec"]["label_space"]
    require(
        labels == artifact.header["judgment_spec"]["label_space"],
        "Label space differs.",
    )
    for source in source_groups:
        require(source["group_id"] in indexed, "Source group is missing.")
        group = indexed[source["group_id"]]
        for field in ("group_id", "expected_relation", "member_case_ids", "severity"):
            require(group[field] == source[field], f"Group {field} differs.")
        parameters = source["relation_parameters"]
        configuration = group["relation_configuration"]
        require(isinstance(configuration, dict), "Configuration must be an object.")
        relation = source["expected_relation"]
        if relation == "same_label":
            require(
                parameters == configuration == {},
                "Same-label parameters are not empty.",
            )
        elif relation == "same_score_within_tolerance":
            require(
                set(configuration) == {"absolute_tolerance"},
                "Unexpected tolerance fields.",
            )
            tolerance = configuration["absolute_tolerance"]
            require(
                type(tolerance) in (Decimal, int), "Tolerance is not an exact number."
            )
            require(tolerance == parameters["absolute_tolerance"], "Tolerance differs.")
        else:
            require(relation == "swapped_preference", "Unknown relation.")
            require(
                set(configuration)
                == {"first_label_index", "second_label_index", "tie_label_index"},
                "Unexpected preference fields.",
            )
            for field in ("first_label", "second_label", "tie_label"):
                index = configuration[field + "_index"]
                if field == "tie_label" and field not in parameters:
                    require(index is None, "Omitted tie must be null.")
                    continue
                require(
                    type(index) is int and 0 <= index < len(labels),
                    "Invalid label index.",
                )
                require(labels[index] == parameters[field], "Label reference differs.")
    return len(source_groups)


def verify_report_identity(report: dict[str, Any]) -> None:
    identity = {**report, "report_id": None}
    require(
        report["report_id"] == canonical_sha256(identity)[:24],
        "Report identity differs.",
    )


def verify_queue(report: dict[str, Any], queue: dict[str, Any]) -> int:
    """Recompute each documented item identity, binding, and RFC 6901 pointer."""
    require(
        queue["source_report_id"] == report["report_id"], "Queue report ID differs."
    )
    digest = hashlib.sha256(canonical_json_bytes(report) + b"\n").hexdigest()
    require(queue["source_report_sha256"] == digest, "Queue report hash differs.")
    require(queue["item_count"] == len(queue["items"]), "Queue count differs.")
    ids = set()
    pointers = 0
    for item in queue["items"]:
        identity = {
            field: item[field]
            for field in (
                "reason_code",
                "subject_type",
                "subject_id",
                "related_subject_ids",
                "role",
                "pairing_key",
                "rule_id",
            )
        }
        identity.update(
            schema_version=queue["schema_version"],
            source_report_id=report["report_id"],
            source_pointer=item["source_pointers"][0],
        )
        require(
            item["queue_item_id"] == canonical_sha256(identity),
            "Queue item identity differs.",
        )
        require(item["queue_item_id"] not in ids, "Duplicate queue item ID.")
        ids.add(item["queue_item_id"])
        for pointer in item["source_pointers"]:
            resolve_pointer(report, pointer)
            pointers += 1
    return pointers


def verify_delta(
    before: dict[str, Any],
    after: dict[str, Any],
    before_queue: dict[str, Any],
    after_queue: dict[str, Any],
) -> dict[str, int | str]:
    """Permit only configuration additions and mechanically recomputed bindings."""
    verify_report_identity(before)
    verify_report_identity(after)
    old = deepcopy(before)
    new = deepcopy(after)
    additions = 0
    require(
        len(old["invariance_groups"]) == len(new["invariance_groups"]),
        "Group count differs.",
    )
    for left, right in zip(
        old["invariance_groups"], new["invariance_groups"], strict=True
    ):
        require(
            "relation_configuration" not in left,
            "Predecessor already has configuration.",
        )
        require("relation_configuration" in right, "Configuration addition is missing.")
        right.pop("relation_configuration")
        additions += 1
    old.pop("report_id")
    new.pop("report_id")
    require(
        canonical_json_bytes(old) == canonical_json_bytes(new),
        "Unauthorized canonical delta.",
    )
    old_pointers = verify_queue(before, before_queue)
    pointers = verify_queue(after, after_queue)
    require(old_pointers == pointers, "Pointer count differs.")
    left_queue = deepcopy(before_queue)
    right_queue = deepcopy(after_queue)
    for queue in (left_queue, right_queue):
        queue.pop("source_report_id")
        queue.pop("source_report_sha256")
        for item in queue["items"]:
            item.pop("queue_item_id")
    require(
        canonical_json_bytes(left_queue) == canonical_json_bytes(right_queue),
        "Queue semantics or ordering differs.",
    )
    return {
        "canonical_delta": "PASS_ONLY_AUTHORIZED_RELATION_CONFIGURATION_PLUS_MECHANICAL_BINDINGS",
        "configuration_additions": additions,
        "queue_items": len(after_queue["items"]),
        "resolving_pointers": pointers,
    }


def read_report(path: Path) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(
        path.read_text(encoding="utf-8"), parse_float=Decimal
    )
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--before-report", type=Path)
    parser.add_argument("--before-queue", type=Path)
    parser.add_argument("--queue", type=Path)
    args = parser.parse_args()
    report = read_report(args.report)
    result: dict[str, Any] = {
        "semantic_groups_verified": verify_semantics(load_artifact(args.input), report)
    }
    if any((args.before_report, args.before_queue, args.queue)):
        if not all((args.before_report, args.before_queue, args.queue)):
            parser.error("Delta verification requires all three report/queue options.")
        result.update(
            verify_delta(
                read_report(args.before_report),
                report,
                read_report(args.before_queue),
                read_report(args.queue),
            )
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
