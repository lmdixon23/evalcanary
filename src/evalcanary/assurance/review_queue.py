"""Deterministic, privacy-bounded review worklists derived from canonical reports."""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from ..errors import InputValidationError
from .numeric import canonical_json_bytes

REVIEW_QUEUE_SCHEMA = "evaluator-assurance-review-queue-v1"
REASON_RANKS: dict[str, int] = {
    "EVIDENCE_INVALID": 1,
    "EVIDENCE_NOT_COMPARABLE": 1,
    "CONTEXT_NOT_ISOLATED": 1,
    "MISSING_EVALUATOR_SIDE": 1,
    "HARD_RULE_VIOLATED": 2,
    "HARD_RULE_MISSING": 2,
    "REVIEW_RULE_VIOLATED": 3,
    "REVIEW_RULE_MISSING": 3,
    "CRITICAL_LABEL_REGRESSION": 4,
    "NEW_ERROR": 5,
    "STATUS_TO_ERROR": 6,
    "STATUS_TO_ABSTAIN": 6,
    "STATUS_TO_INDETERMINATE": 6,
    "INVARIANCE_VIOLATED": 7,
    "INVARIANCE_NOT_EVALUABLE": 7,
    "ANCHOR_DISAGREEMENT": 8,
    "ANCHOR_NOT_COMPARABLE": 8,
    "REPEAT_STATUS_UNSTABLE": 9,
    "REPEAT_LABEL_UNSTABLE": 9,
    "REPEAT_SCORE_UNSTABLE": 9,
    "LABEL_CHANGED": 10,
    "SCORE_CHANGED": 10,
    "INFO_RULE_FINDING": 10,
    "OTHER_OBSERVED_CHANGE": 10,
}
DISPOSITION_SOURCES = frozenset(
    {
        "contract_hard",
        "contract_review",
        "contract_info",
        "engine_comparability",
        "observed_only",
    }
)
_ROLE_ORDER = {None: -1, "baseline": 0, "candidate": 1}


def report_file_sha256(report: dict[str, Any]) -> str:
    """Hash the exact canonical report.json bytes, including its final LF."""

    return hashlib.sha256(canonical_json_bytes(report) + b"\n").hexdigest()


def _pointer(*tokens: str | int) -> str:
    def escape(token: str | int) -> str:
        return str(token).replace("~", "~0").replace("/", "~1")

    return "" if not tokens else "/" + "/".join(escape(token) for token in tokens)


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve one RFC 6901 pointer or fail with a safe diagnostic."""

    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise InputValidationError("Review queue contains an invalid JSON Pointer.")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(current, list):
                if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                    raise KeyError(token)
                current = current[int(token)]
            elif isinstance(current, dict):
                current = current[token]
            else:
                raise KeyError(token)
        except (IndexError, KeyError) as exc:
            raise InputValidationError(
                "Review queue contains a JSON Pointer that does not resolve."
            ) from exc
    return current


def _queue_item_id(
    *,
    source_report_id: str,
    reason_code: str,
    subject_type: str,
    subject_id: str,
    related_subject_ids: list[str],
    role: str | None,
    pairing_key: str | None,
    rule_id: str | None,
    source_pointer: str,
) -> str:
    identity = {
        "schema_version": REVIEW_QUEUE_SCHEMA,
        "source_report_id": source_report_id,
        "reason_code": reason_code,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "related_subject_ids": related_subject_ids,
        "role": role,
        "pairing_key": pairing_key,
        "rule_id": rule_id,
        "source_pointer": source_pointer,
    }
    return hashlib.sha256(canonical_json_bytes(identity)).hexdigest()


def _add_item(
    items: list[dict[str, Any]],
    *,
    report_id: str,
    reason_code: str,
    subject_type: str,
    subject_id: str,
    pointers: list[str],
    order: tuple[int, int] = (-1, -1),
    related_subject_ids: list[str] | None = None,
    role: str | None = None,
    pairing_key: str | None = None,
    rule_id: str | None = None,
    disposition_source: str = "observed_only",
    contract_severity: str | None = None,
    contract_result: str | None = None,
    facts: dict[str, Any] | None = None,
) -> None:
    if reason_code not in REASON_RANKS:
        raise InputValidationError("Review queue reason code is not registered.")
    if disposition_source not in DISPOSITION_SOURCES:
        raise InputValidationError("Review queue disposition source is not registered.")
    if not pointers:
        raise InputValidationError("Review queue items require a source JSON Pointer.")
    related = sorted(related_subject_ids or [])
    items.append(
        {
            "queue_item_id": _queue_item_id(
                source_report_id=report_id,
                reason_code=reason_code,
                subject_type=subject_type,
                subject_id=subject_id,
                related_subject_ids=related,
                role=role,
                pairing_key=pairing_key,
                rule_id=rule_id,
                source_pointer=pointers[0],
            ),
            "review_rank": REASON_RANKS[reason_code],
            "reason_code": reason_code,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "related_subject_ids": related,
            "role": role,
            "pairing_key": pairing_key,
            "rule_id": rule_id,
            "disposition_source": disposition_source,
            "contract_severity": contract_severity,
            "contract_result": contract_result,
            "facts": facts or {},
            "source_pointers": pointers,
            "_order": order,
        }
    )


def _contract_source(severity: str) -> str:
    return f"contract_{severity}"


def _paired_trials(
    case: dict[str, Any],
) -> list[tuple[int, int, dict[str, Any], dict[str, Any]]]:
    by_role: list[dict[str, list[tuple[int, dict[str, Any]]]]] = []
    for role in ("baseline", "candidate"):
        keyed: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for index, trial in enumerate(case["trials"][role]):
            key = trial["pairing_key"]
            if key is not None:
                keyed.setdefault(key, []).append((index, trial))
        by_role.append(keyed)
    result = []
    for key in sorted(set(by_role[0]) & set(by_role[1])):
        if len(by_role[0][key]) == len(by_role[1][key]) == 1:
            before_index, before = by_role[0][key][0]
            after_index, after = by_role[1][key][0]
            result.append((before_index, after_index, before, after))
    return result


def _add_rule_items(report: dict[str, Any], items: list[dict[str, Any]]) -> None:
    report_id = report["report_id"]
    case_order = {
        case["case_id"]: case["manifest_position"] for case in report["cases"]
    }
    for rule_index, rule in enumerate(report["rule_results"]):
        severity = rule["severity"]
        result = rule["result"]
        rule_pointer = _pointer("rule_results", rule_index)
        if result != "satisfied":
            if severity == "hard":
                reason = (
                    "HARD_RULE_MISSING"
                    if result in {"missing", "not_applicable"}
                    else "HARD_RULE_VIOLATED"
                )
            elif severity == "review":
                reason = (
                    "REVIEW_RULE_MISSING"
                    if result in {"missing", "not_applicable"}
                    else "REVIEW_RULE_VIOLATED"
                )
            else:
                reason = "INFO_RULE_FINDING"
            _add_item(
                items,
                report_id=report_id,
                reason_code=reason,
                subject_type="rule",
                subject_id=rule["rule_id"],
                pointers=[rule_pointer],
                order=(-1, rule_index),
                rule_id=rule["rule_id"],
                disposition_source=_contract_source(severity),
                contract_severity=severity,
                contract_result=result,
                facts={
                    "metric": rule["metric"],
                    "scope": rule["scope"],
                    "scope_id": rule["scope_id"],
                },
            )

        parameters = rule.get("parameters", {})
        matching = rule.get("evidence", {}).get("matching_case_ids", [])
        if (
            rule["metric"] != "critical_regression_count"
            or not isinstance(parameters.get("from_label"), str)
            or not isinstance(parameters.get("to_label"), str)
        ):
            continue
        for match_index, case_id in enumerate(matching):
            pointer = _pointer(
                "rule_results", rule_index, "evidence", "matching_case_ids", match_index
            )
            related = [rule["scope_id"]] if rule["scope_id"] is not None else []
            _add_item(
                items,
                report_id=report_id,
                reason_code="CRITICAL_LABEL_REGRESSION",
                subject_type="case",
                subject_id=case_id,
                related_subject_ids=related,
                pointers=[pointer, rule_pointer],
                order=(case_order.get(case_id, -1), rule_index),
                rule_id=rule["rule_id"],
                disposition_source=_contract_source(severity),
                contract_severity=severity,
                contract_result=result,
                facts={
                    "critical_group_id": rule["scope_id"],
                    "from_label": parameters["from_label"],
                    "to_label": parameters["to_label"],
                },
            )


def _add_case_items(report: dict[str, Any], items: list[dict[str, Any]]) -> None:
    report_id = report["report_id"]
    for case_index, case in enumerate(report["cases"]):
        case_id = case["case_id"]
        position = case["manifest_position"]
        critical_ids = case["critical_group_ids"]
        for before_index, after_index, before, after in _paired_trials(case):
            base = _pointer("cases", case_index, "trials", "baseline", before_index)
            candidate = _pointer(
                "cases", case_index, "trials", "candidate", after_index
            )
            pairing_key = after["pairing_key"]
            if before["status"] != after["status"]:
                reason = {
                    "error": "NEW_ERROR",
                    "abstain": "STATUS_TO_ABSTAIN",
                    "indeterminate": "STATUS_TO_INDETERMINATE",
                }.get(after["status"], "OTHER_OBSERVED_CHANGE")
                _add_item(
                    items,
                    report_id=report_id,
                    reason_code=reason,
                    subject_type="trial",
                    subject_id=after["trial_id"],
                    related_subject_ids=[case_id, before["trial_id"]],
                    pointers=[candidate + "/status", base + "/status"],
                    order=(position, after_index),
                    role="candidate",
                    pairing_key=pairing_key,
                    facts={
                        "case_id": case_id,
                        "from_status": before["status"],
                        "to_status": after["status"],
                        "critical_group_ids": critical_ids,
                    },
                )
            if (
                before["status"] == after["status"] == "determinate"
                and before["label"] != after["label"]
            ):
                pointers = [candidate + "/label", base + "/label"]
                if critical_ids:
                    pointers.append(_pointer("cases", case_index, "critical_group_ids"))
                _add_item(
                    items,
                    report_id=report_id,
                    reason_code="LABEL_CHANGED",
                    subject_type="trial",
                    subject_id=after["trial_id"],
                    related_subject_ids=[case_id, before["trial_id"], *critical_ids],
                    pointers=pointers,
                    order=(position, after_index),
                    role="candidate",
                    pairing_key=pairing_key,
                    facts={
                        "case_id": case_id,
                        "from_label": before["label"],
                        "to_label": after["label"],
                        "critical_group_ids": critical_ids,
                    },
                )
            if (
                before["score"] is not None
                and after["score"] is not None
                and before["score"] != after["score"]
            ):
                _add_item(
                    items,
                    report_id=report_id,
                    reason_code="SCORE_CHANGED",
                    subject_type="trial",
                    subject_id=after["trial_id"],
                    related_subject_ids=[case_id, before["trial_id"]],
                    pointers=[candidate + "/score", base + "/score"],
                    order=(position, after_index),
                    role="candidate",
                    pairing_key=pairing_key,
                    facts={"case_id": case_id, "score_changed": True},
                )


def _add_repeat_items(report: dict[str, Any], items: list[dict[str, Any]]) -> None:
    report_id = report["report_id"]
    case_order = {
        case["case_id"]: case["manifest_position"] for case in report["cases"]
    }
    fields = (
        ("status_instability", "REPEAT_STATUS_UNSTABLE"),
        ("label_instability", "REPEAT_LABEL_UNSTABLE"),
        ("score_instability", "REPEAT_SCORE_UNSTABLE"),
    )
    for role in ("baseline", "candidate"):
        cases = report["repeat_diagnostics"][role]["cases"]
        for index, case in enumerate(cases):
            for field, reason in fields:
                if case[field] is not True:
                    continue
                _add_item(
                    items,
                    report_id=report_id,
                    reason_code=reason,
                    subject_type="case",
                    subject_id=case["case_id"],
                    pointers=[
                        _pointer("repeat_diagnostics", role, "cases", index, field)
                    ],
                    order=(case_order.get(case["case_id"], -1), index),
                    role=role,
                    facts={"trial_count": case["trial_count"]},
                )


def _add_invariance_items(report: dict[str, Any], items: list[dict[str, Any]]) -> None:
    report_id = report["report_id"]
    for group_index, group in enumerate(report["invariance_groups"]):
        for role in ("baseline", "candidate"):
            for instance_index, instance in enumerate(group["roles"][role]):
                result = instance["result"]
                if result not in {"violated", "not_evaluable"}:
                    continue
                reason = (
                    "INVARIANCE_VIOLATED"
                    if result == "violated"
                    else "INVARIANCE_NOT_EVALUABLE"
                )
                pointer = _pointer(
                    "invariance_groups",
                    group_index,
                    "roles",
                    role,
                    instance_index,
                    "result",
                )
                _add_item(
                    items,
                    report_id=report_id,
                    reason_code=reason,
                    subject_type="invariance_group",
                    subject_id=group["group_id"],
                    related_subject_ids=group["member_case_ids"],
                    pointers=[pointer, _pointer("invariance_groups", group_index)],
                    order=(group_index, instance_index),
                    role=role,
                    pairing_key=instance["pairing_key"],
                    facts={
                        "expected_relation": group["expected_relation"],
                        "declared_severity": group["severity"],
                        "result": result,
                    },
                )


def _add_anchor_items(report: dict[str, Any], items: list[dict[str, Any]]) -> None:
    report_id = report["report_id"]
    for set_index, anchor_set in enumerate(report["anchor_sets"]):
        for role in ("baseline", "candidate"):
            role_facts = anchor_set["roles"][role]
            disagreement = role_facts["exact_label_disagreements"]
            if disagreement:
                _add_item(
                    items,
                    report_id=report_id,
                    reason_code="ANCHOR_DISAGREEMENT",
                    subject_type="anchor",
                    subject_id=anchor_set["anchor_set_id"],
                    pointers=[
                        _pointer(
                            "anchor_sets",
                            set_index,
                            "roles",
                            role,
                            "exact_label_disagreements",
                        )
                    ],
                    order=(set_index, 0),
                    role=role,
                    facts={"exact_label_disagreement_count": disagreement},
                )
            not_comparable = role_facts["non_comparable_raw_annotations"]
            if not_comparable:
                _add_item(
                    items,
                    report_id=report_id,
                    reason_code="ANCHOR_NOT_COMPARABLE",
                    subject_type="anchor",
                    subject_id=anchor_set["anchor_set_id"],
                    pointers=[
                        _pointer(
                            "anchor_sets",
                            set_index,
                            "roles",
                            role,
                            "non_comparable_raw_annotations",
                        )
                    ],
                    order=(set_index, 1),
                    role=role,
                    facts={"non_comparable_raw_annotation_count": not_comparable},
                )


def _add_comparability_items(report: dict[str, Any], items: list[dict[str, Any]]) -> None:
    report_id = report["report_id"]
    evidence = report["evidence_status"]
    if evidence in {"INVALID", "NOT_COMPARABLE"}:
        reason = (
            "EVIDENCE_INVALID" if evidence == "INVALID" else "EVIDENCE_NOT_COMPARABLE"
        )
        _add_item(
            items,
            report_id=report_id,
            reason_code=reason,
            subject_type="report",
            subject_id=report_id,
            pointers=[_pointer("evidence_status")],
            disposition_source="engine_comparability",
            facts={"evidence_status": evidence},
        )
    if report["isolation_status"] != "ISOLATED":
        _add_item(
            items,
            report_id=report_id,
            reason_code="CONTEXT_NOT_ISOLATED",
            subject_type="report",
            subject_id=report_id,
            pointers=[_pointer("isolation_status"), _pointer("isolation_findings")],
            disposition_source="engine_comparability",
            facts={"isolation_status": report["isolation_status"]},
        )
    case_order = {
        case["case_id"]: case["manifest_position"] for case in report["cases"]
    }
    for index, case_id in enumerate(report["missing_evaluator_side_case_ids"]):
        _add_item(
            items,
            report_id=report_id,
            reason_code="MISSING_EVALUATOR_SIDE",
            subject_type="case",
            subject_id=case_id,
            pointers=[_pointer("missing_evaluator_side_case_ids", index)],
            order=(case_order.get(case_id, -1), index),
            disposition_source="engine_comparability",
        )


def build_review_queue(report: dict[str, Any]) -> dict[str, Any]:
    """Build the exhaustive queue solely from facts in one canonical report."""

    report_id = report.get("report_id")
    if not isinstance(report_id, str):
        raise InputValidationError("Canonical report identity is unavailable.")
    source_sha256 = report_file_sha256(report)
    items: list[dict[str, Any]] = []
    _add_comparability_items(report, items)
    _add_rule_items(report, items)
    _add_case_items(report, items)
    _add_repeat_items(report, items)
    _add_invariance_items(report, items)
    _add_anchor_items(report, items)

    items.sort(
        key=lambda item: (
            item["review_rank"],
            item["_order"],
            item["subject_id"],
            _ROLE_ORDER[item["role"]],
            item["pairing_key"] or "",
            item["reason_code"],
            item["rule_id"] or "",
            item["source_pointers"][0],
        )
    )
    identities = [item["queue_item_id"] for item in items]
    if len(identities) != len(set(identities)):
        raise InputValidationError("Review queue contains duplicate canonical tuples.")
    for item in items:
        item.pop("_order")
        for pointer in item["source_pointers"]:
            resolve_pointer(report, pointer)

    ranks = Counter(str(item["review_rank"]) for item in items)
    reasons = Counter(item["reason_code"] for item in items)
    dispositions = Counter(item["disposition_source"] for item in items)
    return {
        "schema_version": REVIEW_QUEUE_SCHEMA,
        "source_report_id": report_id,
        "source_report_sha256": source_sha256,
        "generated_by": {
            "name": "evalcanary",
            "assurance_engine_version": report["assurance_engine_version"],
        },
        "item_count": len(items),
        "counts_by_review_rank": dict(
            sorted(ranks.items(), key=lambda item: int(item[0]))
        ),
        "counts_by_reason": dict(
            sorted(reasons.items(), key=lambda item: (REASON_RANKS[item[0]], item[0]))
        ),
        "counts_by_disposition_source": dict(sorted(dispositions.items())),
        "items": items,
    }


def verify_review_queue_binding(report: dict[str, Any], queue: dict[str, Any]) -> None:
    """Verify report identity/hash and every pointer before consuming a queue."""

    if queue.get("schema_version") != REVIEW_QUEUE_SCHEMA:
        raise InputValidationError("Review queue schema is not supported.")
    if queue.get("source_report_id") != report.get("report_id"):
        raise InputValidationError("Review queue source report identity does not match.")
    if queue.get("source_report_sha256") != report_file_sha256(report):
        raise InputValidationError("Review queue source report hash does not match.")
    for item in queue.get("items", []):
        for pointer in item.get("source_pointers", []):
            resolve_pointer(report, pointer)


def queue_view_model(
    queue: dict[str, Any], *, per_reason_limit: int = 20
) -> dict[str, Any]:
    """Create the one bounded view model used by the Markdown projection."""

    if per_reason_limit < 1:
        raise ValueError("per_reason_limit must be positive")
    groups: list[dict[str, Any]] = []
    for reason in sorted(
        queue["counts_by_reason"], key=lambda value: (REASON_RANKS[value], value)
    ):
        matching = [item for item in queue["items"] if item["reason_code"] == reason]
        displayed = matching[:per_reason_limit]
        groups.append(
            {
                "reason_code": reason,
                "review_rank": REASON_RANKS[reason],
                "total_count": len(matching),
                "displayed_count": len(displayed),
                "omitted_count": len(matching) - len(displayed),
                "items": displayed,
            }
        )
    return {
        "source_report_id": queue["source_report_id"],
        "source_report_sha256": queue["source_report_sha256"],
        "item_count": queue["item_count"],
        "counts_by_review_rank": queue["counts_by_review_rank"],
        "counts_by_reason": queue["counts_by_reason"],
        "counts_by_disposition_source": queue["counts_by_disposition_source"],
        "groups": groups,
    }


def review_queue_markdown(queue: dict[str, Any], *, per_reason_limit: int = 20) -> str:
    """Render a bounded, content-free human projection of the queue."""

    view = queue_view_model(queue, per_reason_limit=per_reason_limit)
    lines = [
        "# Evaluator-assurance review queue",
        "",
        f"- Total attention items: **{view['item_count']}**",
        f"- Source report ID: `{view['source_report_id']}`",
        f"- Source report SHA-256: `{view['source_report_sha256']}`",
        "- Priority is review ordering only; it is not correctness or semantic severity.",
        "",
        "## Counts by review rank",
        "",
        "| Rank | Count |",
        "| ---: | ---: |",
    ]
    lines.extend(
        f"| {rank} | {count} |"
        for rank, count in view["counts_by_review_rank"].items()
    )
    lines.extend(
        [
            "",
            "## Counts by reason",
            "",
            "| Reason | Count |",
            "| --- | ---: |",
        ]
    )
    lines.extend(
        f"| `{reason}` | {count} |"
        for reason, count in view["counts_by_reason"].items()
    )
    lines.extend(
        [
            "",
            "## Counts by disposition source",
            "",
            "| Disposition source | Count |",
            "| --- | ---: |",
        ]
    )
    lines.extend(
        f"| `{source}` | {count} |"
        for source, count in view["counts_by_disposition_source"].items()
    )
    lines.extend(["", "## Ordered worklist", ""])
    for group in view["groups"]:
        lines.extend(
            [
                f"### Rank {group['review_rank']}: {group['reason_code']}",
                "",
                (
                    f"Total: {group['total_count']}; displayed: "
                    f"{group['displayed_count']}; omitted: {group['omitted_count']}."
                ),
                "",
            ]
        )
        for item in group["items"]:
            qualifiers = [item["subject_type"], item["subject_id"]]
            if item["role"] is not None:
                qualifiers.append(item["role"])
            if item["pairing_key"] is not None:
                qualifiers.append(item["pairing_key"])
            lines.append(
                f"- `{' / '.join(qualifiers)}` -> `{item['source_pointers'][0]}`"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
