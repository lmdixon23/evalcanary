"""Three deterministic projections from one canonical assurance report model."""

from __future__ import annotations

import hashlib
import heapq
import html
import os
import stat
import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from ..errors import InputValidationError
from .numeric import canonical_json_bytes, canonical_json_text, iter_canonical_json
from .review_queue import (
    build_review_queue,
    review_queue_markdown,
    verify_review_queue_binding,
)
from .schema import Limits

_DETAIL_CAPS = {"violated": 50, "not_evaluable": 25, "satisfied": 10}
_CASE_DETAIL_CAP = 25
_CRITICAL_DETAIL_CAP = 50


def json_bytes(report: dict[str, Any]) -> bytes:
    return canonical_json_bytes(report) + b"\n"


def _safe_links(report: dict[str, Any]) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    sources: list[dict[str, Any]] = [report.get("provenance", {}).get("artifact", {})]
    for evaluation in report.get("evaluations", {}).values():
        sources.append(evaluation.get("provenance", {}))
    for source in sources:
        for name in ("source_url", "license_url"):
            item = source.get(name)
            if isinstance(item, dict) and isinstance(item.get("identity"), str):
                links.append((name.replace("_", " ").title(), item["identity"]))
    return sorted(set(links))


def _ratio(value: dict[str, Any] | None) -> str:
    if value is None:
        return "not available"
    return f"{value['numerator']}/{value['denominator']}"


def _canonical_size_hash(report: dict[str, Any]) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    for chunk in iter_canonical_json(report):
        encoded = chunk.encode("utf-8")
        digest.update(encoded)
        size += len(encoded)
    digest.update(b"\n")
    return size + 1, digest.hexdigest()


def _bounded_value(value: Any, *, cap: int = 8) -> str:
    if isinstance(value, dict):
        keys = heapq.nsmallest(cap, value)
        pieces = [
            f"{key}={_bounded_value(value[key], cap=cap)}" for key in keys
        ]
        if len(value) > cap:
            pieces.append(f"... {len(value) - cap} omitted")
        return "{" + ", ".join(pieces) + "}"
    if isinstance(value, list | tuple):
        shown = [_bounded_value(item, cap=cap) for item in value[:cap]]
        if len(value) > cap:
            shown.append(f"... {len(value) - cap} omitted")
        return "[" + ", ".join(shown) + "]"
    if value is None:
        return "null"
    if isinstance(value, str):
        return " ".join(value.splitlines())
    return canonical_json_text(value)


def _display_actual(value: Any) -> str:
    if isinstance(value, dict) and {"numerator", "denominator"} <= set(value):
        decimal = value.get("decimal")
        suffix = "" if decimal is None else f" ({decimal})"
        return f"{value['numerator']}/{value['denominator']}{suffix}"
    return _bounded_value(value)


def _identity(value: dict[str, Any] | None) -> str:
    if not isinstance(value, dict):
        return "not supplied"
    identity = value.get("identity")
    if isinstance(identity, str):
        return identity
    digest = value.get("identity_sha256") or value.get("declared_sha256")
    if isinstance(digest, str):
        return f"omitted; sha256={digest}"
    return str(value.get("presence", "not supplied"))


def _trial_summary(case: dict[str, Any], role: str) -> str:
    trials = case["trials"][role]
    statuses = Counter(item["status"] for item in trials)
    labels = Counter(
        item["label"]
        for item in trials
        if item["status"] == "determinate" and item["label"] is not None
    )
    status_text = ", ".join(
        f"{name}={statuses[name]}"
        for name in ("determinate", "abstain", "indeterminate", "error")
    )
    label_text = ", ".join(f"{name}={count}" for name, count in sorted(labels.items()))
    return f"total={len(trials)}; {status_text}; labels={label_text or 'n/a'}"


def _rule_is_priority(item: dict[str, Any]) -> bool:
    if item["result"] == "violated":
        return item["severity"] in {"hard", "review"}
    if item["result"] in {"missing", "not_applicable"}:
        return item["missing_evidence"] in {"hard_fail", "review"}
    return False


def _projection_facts(
    report: dict[str, Any],
) -> dict[str, Any]:
    rules = sorted(report["rule_results"], key=lambda item: str(item["rule_id"]))
    rule_rows = [
        (
            str(item["rule_id"]),
            str(item["severity"]),
            str(item["scope"])
            + ("" if item["scope_id"] is None else f":{item['scope_id']}"),
            str(item["metric"]),
            str(item["operator"]),
            _display_actual(item["threshold"]),
            _display_actual(item["value"]),
            str(item["result"]),
            str(item["missing_evidence"]),
            str(item["rationale"]),
            _bounded_value(item["evidence"]),
        )
        for item in rules
    ]

    priority_rows: list[tuple[str, ...]] = []
    for item in rules:
        if _rule_is_priority(item):
            policy = (
                item["severity"]
                if item["result"] == "violated"
                else item["missing_evidence"]
            )
            priority_rows.append(
                (
                    str(policy),
                    f"contract:{item['rule_id']}",
                    f"{item['metric']} is {item['result']}",
                    f"actual={_display_actual(item['value'])}; "
                    f"{item['operator']} {_display_actual(item['threshold'])}; "
                    f"evidence={_bounded_value(item['evidence'])}",
                )
            )
    for index, warning in enumerate(report.get("warnings", []), start=1):
        priority_rows.append(
            ("review", f"system:{index}", "mandatory system review", str(warning))
        )

    critical_items = report["critical_groups"]

    def transition_changed(transitions: dict[str, Any]) -> bool:
        for name, count in transitions.items():
            before, separator, after = name.partition("->")
            if separator and before != after and int(count) > 0:
                return True
        return False

    def critical_finding(item: dict[str, Any]) -> bool:
        transitions = item["transitions"]
        return bool(
            transition_changed(transitions["status_transitions"])
            or transition_changed(transitions["label_transitions"])
            or item["repeat"]["baseline"]["status_distribution"]["error"]
            or item["repeat"]["candidate"]["status_distribution"]["error"]
        )

    critical_ranked = sorted(
        critical_items,
        key=lambda item: (not critical_finding(item), str(item["group_id"])),
    )
    selected_critical = critical_ranked[:_CRITICAL_DETAIL_CAP]
    finding_count = sum(critical_finding(item) for item in critical_items)
    selected_finding_count = sum(critical_finding(item) for item in selected_critical)
    critical_summary = [
        (
            str(len(critical_items)),
            str(
                sum(
                    transition_changed(item["transitions"]["status_transitions"])
                    for item in critical_items
                )
            ),
            str(
                sum(
                    transition_changed(item["transitions"]["label_transitions"])
                    for item in critical_items
                )
            ),
            str(
                sum(
                    int(item["repeat"]["baseline"]["status_distribution"]["error"])
                    for item in critical_items
                )
            ),
            str(
                sum(
                    int(item["repeat"]["candidate"]["status_distribution"]["error"])
                    for item in critical_items
                )
            ),
            str(finding_count),
            str(len(selected_critical)),
            str(finding_count - selected_finding_count),
        )
    ]
    critical_rows: list[tuple[str, ...]] = []
    for item in selected_critical:
        status_transitions = item["transitions"]["status_transitions"]
        label_transitions = item["transitions"]["label_transitions"]
        baseline_errors = item["repeat"]["baseline"]["status_distribution"]["error"]
        candidate_errors = item["repeat"]["candidate"]["status_distribution"]["error"]
        critical_rows.append(
            (
                str(item["group_id"]),
                str(len(item["member_case_ids"])),
                str(item["pairing"]["valid_pair_count"]),
                _bounded_value(status_transitions),
                _bounded_value(label_transitions),
                str(baseline_errors),
                str(candidate_errors),
            )
        )
        if critical_finding(item):
            priority_rows.append(
                (
                    "critical",
                    f"critical_group:{item['group_id']}",
                    "declared critical-group transition evidence",
                    f"status={_bounded_value(status_transitions)}; "
                    f"labels={_bounded_value(label_transitions)}; "
                    f"baseline_errors={baseline_errors}; "
                    f"candidate_errors={candidate_errors}",
                )
            )
    if finding_count > selected_finding_count:
        priority_rows.append(
            (
                "critical",
                "critical_group:bounded_omission",
                f"{finding_count - selected_finding_count} additional critical finding groups are omitted from detail",
                "Aggregate counts remain in Critical findings; exhaustive identities are in report.json.",
            )
        )

    status_rows: list[tuple[str, ...]] = []
    for role in ("baseline", "candidate"):
        fact = report["repeat_diagnostics"][role]
        status = fact["status_distribution"]
        labels = ", ".join(
            f"{name}={count}"
            for name, count in sorted(fact["label_distribution"].items())
        )
        status_rows.append(
            (
                role,
                str(fact["trial_count"]),
                str(fact["determinate_trials"]),
                str(status["abstain"]),
                str(status["indeterminate"]),
                str(status["error"]),
                _ratio(fact["determinate_coverage"]),
                labels or "not applicable",
            )
        )

    evaluation_rows = []
    for role in ("baseline", "candidate"):
        item = report["evaluations"][role]
        evaluation_rows.append(
            (
                role,
                str(item["evaluation_id"]),
                str(item["evaluator_id"]),
                _identity(item["evaluator_version"]),
                str(item["evaluator_fingerprint_sha256"]),
                str(item["context_id"]),
                str(item["context_fingerprint_sha256"]),
            )
        )

    invariance_counts = {
        role: Counter({"satisfied": 0, "violated": 0, "not_evaluable": 0})
        for role in ("baseline", "candidate")
    }
    detail_by_key: dict[tuple[str, str], list[tuple[str, ...]]] = {
        (role, result): []
        for role in ("baseline", "candidate")
        for result in ("violated", "not_evaluable", "satisfied")
    }
    for item in sorted(
        report["invariance_groups"], key=lambda value: str(value["group_id"])
    ):
        for role in ("baseline", "candidate"):
            instances = sorted(
                item["roles"][role],
                key=lambda value: ""
                if value["pairing_key"] is None
                else str(value["pairing_key"]),
            )
            for instance in instances:
                result = str(instance["result"])
                invariance_counts[role][result] += 1
                rows = detail_by_key[(role, result)]
                if len(rows) < _DETAIL_CAPS[result]:
                    rows.append(
                        (
                            role,
                            str(item["group_id"]),
                            result,
                            str(item["expected_relation"]),
                            "unkeyed"
                            if instance["pairing_key"] is None
                            else str(instance["pairing_key"]),
                            str(item["severity"]),
                            _bounded_value(item["member_case_ids"]),
                        )
                    )
    invariance_summary = [
        (
            role,
            str(invariance_counts[role]["satisfied"]),
            str(invariance_counts[role]["violated"]),
            str(invariance_counts[role]["not_evaluable"]),
            str(sum(invariance_counts[role].values())),
        )
        for role in ("baseline", "candidate")
    ]
    invariance_detail: list[tuple[str, ...]] = []
    projection_rows: list[tuple[str, ...]] = []
    for role in ("baseline", "candidate"):
        for result in ("violated", "not_evaluable", "satisfied"):
            rows = detail_by_key[(role, result)]
            invariance_detail.extend(rows)
            total = invariance_counts[role][result]
            projection_rows.append(
                (
                    f"invariance {role} {result}",
                    str(total),
                    str(len(rows)),
                    str(total - len(rows)),
                )
            )

    anchor_rows: list[tuple[str, ...]] = []
    for item in sorted(report["anchor_sets"], key=lambda value: value["anchor_set_id"]):
        for role in ("baseline", "candidate"):
            role_fact = item["roles"][role]
            anchor_rows.append(
                (
                    str(item["anchor_set_id"]),
                    role,
                    str(item["raw_annotation_count"]),
                    str(item["covered_case_count"]),
                    str(item["cluster_count"]),
                    str(role_fact["comparable_raw_annotations"]),
                    str(role_fact["non_comparable_raw_annotations"]),
                    str(role_fact["selected_role_error_annotations"]),
                    str(role_fact["selected_role_non_determinate_annotations"]),
                    str(role_fact["anchor_non_determinate_annotations"]),
                    str(role_fact["non_unique_selected_role_annotations"]),
                    str(role_fact["incompatible_label_space_annotations"]),
                    str(role_fact["exact_label_agreements"]),
                    str(role_fact["exact_label_disagreements"]),
                )
            )

    deltas = {
        **{
            f"evaluation.{name}": item
            for name, item in report["provenance"]["evaluation_delta"].items()
        },
        **report["provenance"]["component_delta"],
    }
    provenance_counts = Counter(item["delta"] for item in deltas.values())
    provenance_summary = [
        (name, str(provenance_counts[name]))
        for name in (
            "same",
            "changed",
            "missing_before",
            "missing_after",
            "missing_both",
            "omitted",
        )
    ]
    provenance_rows = [
        (
            name,
            str(item["delta"]),
            str(item["baseline_presence"]),
            str(item["candidate_presence"]),
        )
        for name, item in sorted(deltas.items())
        if item["delta"] != "same"
    ]
    context_rows = [
        (str(item["component"]), str(item["finding"]))
        for item in report["isolation_findings"]
    ]

    all_cases = report["cases"]
    cases = heapq.nsmallest(
        _CASE_DETAIL_CAP, all_cases, key=lambda item: str(item["case_id"])
    )
    case_rows = [
        (
            str(item["case_id"]),
            _bounded_value(item["critical_group_ids"]),
            _bounded_value(item["invariance_group_ids"]),
            _trial_summary(item, "baseline"),
            _trial_summary(item, "candidate"),
        )
        for item in cases
    ]
    projection_rows.extend(
        (
            (
                "critical groups",
                str(len(critical_items)),
                str(len(critical_rows)),
                str(len(critical_items) - len(critical_rows)),
            ),
            (
                "case summaries",
                str(len(all_cases)),
                str(len(case_rows)),
                str(len(all_cases) - len(case_rows)),
            ),
        )
    )
    displayed = sum(int(item[2]) for item in projection_rows)
    omitted = sum(int(item[3]) for item in projection_rows)
    return {
        "rules": rule_rows,
        "priority": priority_rows,
        "critical_summary": critical_summary,
        "critical": critical_rows,
        "status": status_rows,
        "evaluations": evaluation_rows,
        "invariance_summary": invariance_summary,
        "invariance_detail": invariance_detail,
        "anchors": anchor_rows,
        "provenance_summary": provenance_summary,
        "provenance_detail": provenance_rows,
        "context": context_rows,
        "cases": case_rows,
        "projection": projection_rows,
        "displayed_detail_rows": displayed,
        "omitted_detail_rows": omitted,
    }


def _markdown_cell(value: Any) -> str:
    text = " ".join(str(value).splitlines())
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _markdown_table(
    headers: tuple[str, ...], rows: Sequence[tuple[str, ...]]
) -> list[str]:
    if not rows:
        return ["No evidence was declared for this section.", ""]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_markdown_cell(value) for value in row) + " |")
    lines.append("")
    return lines


def _resource_rows(
    report: dict[str, Any], report_sizes: dict[str, int] | None
) -> list[tuple[str, str]]:
    usage = report.get("resource_usage", {})
    limits = report.get("resource_limits", {})
    sizes = report_sizes or {}
    return [
        ("Input bytes", str(usage.get("input_bytes", "not recorded"))),
        ("Input records", str(usage.get("record_count", "not recorded"))),
        ("Cases", str(usage.get("case_count", len(report.get("cases", []))))),
        ("Trials", str(usage.get("trial_count", "not recorded"))),
        ("Anchors", str(usage.get("anchor_count", "not recorded"))),
        ("Canonical JSON bytes", str(sizes.get("json_report_bytes", "not measured"))),
        ("Markdown bytes", str(sizes.get("markdown_report_bytes", "not measured"))),
        ("HTML bytes", str(sizes.get("html_report_bytes", "not measured"))),
        ("Non-default limits", "yes" if limits.get("nondefault") else "no"),
        ("Limit overrides", _bounded_value(limits.get("overrides", {}))),
    ]


def markdown_text(
    report: dict[str, Any],
    *,
    canonical_json_sha256: str | None = None,
    report_sizes: dict[str, int] | None = None,
) -> str:
    if canonical_json_sha256 is None:
        _, canonical_json_sha256 = _canonical_size_hash(report)
    facts = _projection_facts(report)
    status_rows = [
        ("Evidence", str(report["evidence_status"])),
        ("Isolation", str(report["isolation_status"])),
        ("Contract", str(report["contract_status"])),
        ("Overall report", str(report["report_status"])),
    ]
    input_fact = report["input"]
    corpus = report["corpus"]
    identity_rows = [
        ("Report ID", str(report["report_id"])),
        ("Artifact ID", str(input_fact["artifact_id"])),
        ("Input SHA-256", str(input_fact["source_sha256"])),
        ("Corpus ID", str(corpus["corpus_id"])),
        ("Corpus identity level", str(corpus["identity_level"])),
        ("Declared case count", str(corpus["case_count"])),
        ("Manifest SHA-256", str(corpus["computed_manifest_sha256"])),
    ]
    contract = report.get("contract")
    if contract is not None:
        identity_rows.extend(
            [
                ("Contract ID", str(contract["contract_id"])),
                ("Contract version", str(contract["contract_version"])),
                ("Contract SHA-256", str(contract["source_sha256"])),
            ]
        )
    lines = [
        "# EvalCanary evaluator-assurance report",
        "",
        "Contract-bound evidence for a frozen evaluator migration. This report does not decide which evaluator is correct.",
        "",
        "## A. Evidence, isolation, contract, and report status",
        "",
    ]
    lines.extend(_markdown_table(("Dimension", "Value"), status_rows))
    lines.extend(["## B. Decision summary", ""])
    if facts["priority"]:
        lines.extend(
            _markdown_table(
                ("Policy", "Finding", "Summary", "Decision evidence"),
                facts["priority"],
            )
        )
    else:
        lines.extend(
            [
                "No hard contract, mandatory system-review, or critical-group finding was emitted.",
                "",
            ]
        )
    lines.extend(
        _markdown_table(
            (
                "Role",
                "Trials",
                "Determinate",
                "Abstain",
                "Indeterminate",
                "Error",
                "Determinate coverage",
                "Determinate labels",
            ),
            facts["status"],
        )
    )
    lines.extend(_markdown_table(("Resource", "Observed"), _resource_rows(report, report_sizes)))
    pairing = report["pairing"]
    lines.extend(
        [
            f"Overall valid pairing coverage is `{_ratio(pairing['pairing_coverage'])}`; incomplete cases: `{len(pairing['incomplete_case_ids'])}`.",
            "",
            "## C. Contract findings",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            (
                "Rule",
                "Severity",
                "Scope",
                "Metric",
                "Operator",
                "Threshold",
                "Actual",
                "Result",
                "Missing-evidence policy",
                "Rationale",
                "Bounded evidence",
            ),
            facts["rules"],
        )
    )
    lines.extend(["## D. Critical findings", ""])
    lines.extend(
        _markdown_table(
            (
                "Groups",
                "With status transitions",
                "With label transitions",
                "Baseline errors",
                "Candidate errors",
                "Finding groups",
                "Detail displayed",
                "Finding groups omitted",
            ),
            facts["critical_summary"],
        )
    )
    lines.extend(
        _markdown_table(
            (
                "Group",
                "Members",
                "Valid pairs",
                "Status transitions",
                "Label transitions",
                "Baseline errors",
                "Candidate errors",
            ),
            facts["critical"],
        )
    )
    lines.extend(["## E. Invariance summary", ""])
    lines.extend(
        _markdown_table(
            ("Role", "Satisfied", "Violated", "Not evaluable", "Total"),
            facts["invariance_summary"],
        )
    )
    lines.extend(
        [
            "Bounded detail caps per role are: violated 50, not evaluable 25, satisfied 10.",
            "",
            "## F. Human-anchor summary",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            (
                "Anchor set",
                "Role",
                "Raw annotations",
                "Covered cases",
                "Clusters",
                "Comparable raw",
                "Non-comparable raw",
                "Role errors excluded",
                "Role non-determinate excluded",
                "Anchor non-determinate excluded",
                "Non-unique role selections excluded",
                "Incompatible label spaces excluded",
                "Agreements",
                "Disagreements",
            ),
            facts["anchors"],
        )
    )
    lines.extend(["## G. Provenance and context changes", ""])
    lines.extend(_markdown_table(("Identity", "Value"), identity_rows))
    lines.extend(
        _markdown_table(
            (
                "Role",
                "Evaluation",
                "Evaluator",
                "Evaluator version",
                "Evaluator fingerprint",
                "Context",
                "Context fingerprint",
            ),
            facts["evaluations"],
        )
    )
    lines.extend(
        _markdown_table(
            ("Delta state", "Count"), facts["provenance_summary"]
        )
    )
    lines.extend(
        _markdown_table(
            ("Field", "Delta", "Baseline presence", "Candidate presence"),
            facts["provenance_detail"],
        )
    )
    lines.extend(_markdown_table(("Component", "Isolation finding"), facts["context"]))
    links = _safe_links(report)
    if links:
        lines.extend(["Typed public references:", ""])
        for label, target in links:
            if not any(character in target for character in '<>"'):
                lines.append(f"- [{label}](<{target}>)")
    lines.extend(
        [
            "",
            "## H. Bounded detail",
            "",
            "The companion `report.json` is the exhaustive canonical record. Human projections deliberately omit repetitive rows.",
            f"Canonical JSON SHA-256: `{canonical_json_sha256}`.",
            f"Bounded detail rows displayed: `{facts['displayed_detail_rows']}`; omitted: `{facts['omitted_detail_rows']}`.",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            ("Detail population", "Total", "Displayed", "Omitted"),
            facts["projection"],
        )
    )
    lines.extend(
        _markdown_table(
            (
                "Role",
                "Group",
                "Result",
                "Expected relation",
                "Pairing key",
                "Severity",
                "Member cases",
            ),
            facts["invariance_detail"],
        )
    )
    lines.extend(
        _markdown_table(
            ("Case", "Critical groups", "Invariance groups", "Baseline", "Candidate"),
            facts["cases"],
        )
    )
    lines.extend(["## I. Limitations", ""])
    lines.extend(f"- {_markdown_cell(item)}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def _html_table(
    caption: str, headers: tuple[str, ...], rows: Sequence[tuple[str, ...]]
) -> str:
    head = "".join(f'<th scope="col">{html.escape(item)}</th>' for item in headers)
    if rows:
        body = "".join(
            "<tr>"
            + "".join(
                (
                    f'<th scope="row">{html.escape(value)}</th>'
                    if index == 0
                    else f"<td>{html.escape(value)}</td>"
                )
                for index, value in enumerate(row)
            )
            + "</tr>"
            for row in rows
        )
    else:
        body = (
            f'<tr><td colspan="{len(headers)}">'
            "No evidence was declared for this section.</td></tr>"
        )
    return (
        f"<table><caption>{html.escape(caption)}</caption><thead><tr>{head}</tr>"
        f"</thead><tbody>{body}</tbody></table>"
    )


def html_text(
    report: dict[str, Any],
    *,
    canonical_json_sha256: str | None = None,
    report_sizes: dict[str, int] | None = None,
) -> str:
    if canonical_json_sha256 is None:
        _, canonical_json_sha256 = _canonical_size_hash(report)
    facts = _projection_facts(report)
    limitations = "".join(
        f"<li>{html.escape(str(item))}</li>" for item in report["limitations"]
    )
    links = (
        "".join(
            f'<li><a href="{html.escape(target, quote=True)}">{html.escape(label)}</a></li>'
            for label, target in _safe_links(report)
        )
        or "<li>No reportable public reference was supplied.</li>"
    )
    status_table = _html_table(
        "Status",
        ("Dimension", "Value"),
        [
            ("Evidence", str(report["evidence_status"])),
            ("Isolation", str(report["isolation_status"])),
            ("Contract", str(report["contract_status"])),
            ("Overall report", str(report["report_status"])),
        ],
    )
    input_fact = report["input"]
    corpus = report["corpus"]
    identity_rows = [
        ("Report ID", str(report["report_id"])),
        ("Artifact ID", str(input_fact["artifact_id"])),
        ("Input SHA-256", str(input_fact["source_sha256"])),
        ("Corpus ID", str(corpus["corpus_id"])),
        ("Corpus identity level", str(corpus["identity_level"])),
        ("Declared case count", str(corpus["case_count"])),
        ("Manifest SHA-256", str(corpus["computed_manifest_sha256"])),
    ]
    contract = report.get("contract")
    if contract is not None:
        identity_rows.extend(
            [
                ("Contract ID", str(contract["contract_id"])),
                ("Contract version", str(contract["contract_version"])),
                ("Contract SHA-256", str(contract["source_sha256"])),
            ]
        )
    identity_table = _html_table("Report identity", ("Identity", "Value"), identity_rows)
    evaluation_table = _html_table(
        "Evaluator identities",
        (
            "Role",
            "Evaluation",
            "Evaluator",
            "Evaluator version",
            "Evaluator fingerprint",
            "Context",
            "Context fingerprint",
        ),
        facts["evaluations"],
    )
    if facts["priority"]:
        priority = _html_table(
            "Decision-priority findings",
            ("Policy", "Finding", "Summary", "Decision evidence"),
            facts["priority"],
        )
    else:
        priority = (
            "<p>No hard contract, mandatory system-review, or critical-group "
            "finding was emitted.</p>"
        )
    status_counts = _html_table(
        "Trial status and label counts",
        (
            "Role",
            "Trials",
            "Determinate",
            "Abstain",
            "Indeterminate",
            "Error",
            "Determinate coverage",
            "Determinate labels",
        ),
        facts["status"],
    )
    resources = _html_table(
        "Resource disclosure",
        ("Resource", "Observed"),
        _resource_rows(report, report_sizes),
    )
    contract_table = _html_table(
        "Complete contract rule findings",
        (
            "Rule",
            "Severity",
            "Scope",
            "Metric",
            "Operator",
            "Threshold",
            "Actual",
            "Result",
            "Missing-evidence policy",
            "Rationale",
            "Bounded evidence",
        ),
        facts["rules"],
    )
    critical_table = _html_table(
        "Critical-group evidence",
        (
            "Group",
            "Members",
            "Valid pairs",
            "Status transitions",
            "Label transitions",
            "Baseline errors",
            "Candidate errors",
        ),
        facts["critical"],
    )
    critical_summary = _html_table(
        "Critical-group aggregate",
        (
            "Groups",
            "With status transitions",
            "With label transitions",
            "Baseline errors",
            "Candidate errors",
            "Finding groups",
            "Detail displayed",
            "Finding groups omitted",
        ),
        facts["critical_summary"],
    )
    invariance_table = _html_table(
        "Aggregate invariance outcomes",
        ("Role", "Satisfied", "Violated", "Not evaluable", "Total"),
        facts["invariance_summary"],
    )
    anchor_table = _html_table(
        "Human-anchor evidence",
        (
            "Anchor set",
            "Role",
            "Raw annotations",
            "Covered cases",
            "Clusters",
            "Comparable raw",
            "Non-comparable raw",
            "Role errors excluded",
            "Role non-determinate excluded",
            "Anchor non-determinate excluded",
            "Non-unique role selections excluded",
            "Incompatible label spaces excluded",
            "Agreements",
            "Disagreements",
        ),
        facts["anchors"],
    )
    provenance_summary = _html_table(
        "Provenance delta summary",
        ("Delta state", "Count"),
        facts["provenance_summary"],
    )
    provenance_detail = _html_table(
        "Non-same provenance fields",
        ("Field", "Delta", "Baseline presence", "Candidate presence"),
        facts["provenance_detail"],
    )
    context_table = _html_table(
        "Isolation findings", ("Component", "Finding"), facts["context"]
    )
    projection_table = _html_table(
        "Bounded projection inventory",
        ("Detail population", "Total", "Displayed", "Omitted"),
        facts["projection"],
    )
    invariance_detail = _html_table(
        "Bounded invariance detail",
        (
            "Role",
            "Group",
            "Result",
            "Expected relation",
            "Pairing key",
            "Severity",
            "Member cases",
        ),
        facts["invariance_detail"],
    )
    case_detail = _html_table(
        "Bounded case summaries",
        ("Case", "Critical groups", "Invariance groups", "Baseline", "Candidate"),
        facts["cases"],
    )
    pairing = report["pairing"]
    pairing_summary = html.escape(
        f"Overall valid pairing coverage: {_ratio(pairing['pairing_coverage'])}; "
        f"incomplete cases: {len(pairing['incomplete_case_ids'])}."
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'">
<title>EvalCanary assurance report {html.escape(str(report["report_id"]))}</title>
<style>
:root {{ color-scheme:light dark; --bg:#f5f7fa; --panel:#fff; --text:#172b4d; --muted:#526177; --line:#cbd3df; --focus:#a86800; }}
@media (prefers-color-scheme:dark) {{ :root {{ --bg:#101722; --panel:#182231; --text:#edf2fa; --muted:#b6c1d2; --line:#43516a; --focus:#ffd166; }} }}
* {{ box-sizing:border-box }} body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.5 system-ui,sans-serif }}
main {{ max-width:1120px; margin:auto; padding:clamp(1rem,3vw,2.5rem) }} section {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; margin:1rem 0; padding:1rem; overflow:auto }}
table {{ width:100%; border-collapse:collapse }} caption {{ text-align:left; font-weight:700; margin-bottom:.5rem }} th,td {{ text-align:left; border-bottom:1px solid var(--line); padding:.6rem }}
pre {{ white-space:pre-wrap; overflow-wrap:anywhere }} a:focus-visible {{ outline:3px solid var(--focus); outline-offset:3px }} .status {{ font-weight:800 }}
</style>
</head>
<body><main>
<header><h1>EvalCanary evaluator-assurance report</h1><p>Contract-bound evidence for a frozen evaluator migration. This report does not decide which evaluator is correct.</p></header>
<section aria-labelledby="a-heading"><h2 id="a-heading">A. Evidence, isolation, contract, and report status</h2>{status_table}</section>
<section aria-labelledby="b-heading"><h2 id="b-heading">B. Decision summary</h2>{priority}{status_counts}{resources}<p>{pairing_summary}</p></section>
<section aria-labelledby="c-heading"><h2 id="c-heading">C. Contract findings</h2>{contract_table}</section>
<section aria-labelledby="d-heading"><h2 id="d-heading">D. Critical findings</h2>{critical_summary}{critical_table}</section>
<section aria-labelledby="e-heading"><h2 id="e-heading">E. Invariance summary</h2>{invariance_table}<p>Bounded detail caps per role are: violated 50, not evaluable 25, satisfied 10.</p></section>
<section aria-labelledby="f-heading"><h2 id="f-heading">F. Human-anchor summary</h2>{anchor_table}</section>
<section aria-labelledby="g-heading"><h2 id="g-heading">G. Provenance and context changes</h2>{identity_table}{evaluation_table}{provenance_summary}{provenance_detail}{context_table}<h3>Typed public references</h3><ul>{links}</ul></section>
<section aria-labelledby="h-heading"><h2 id="h-heading">H. Bounded detail</h2><p>The companion <code>report.json</code> is the exhaustive canonical record. Human projections deliberately omit repetitive rows.</p><p>Canonical JSON SHA-256: <code>{html.escape(canonical_json_sha256)}</code>. Bounded detail rows displayed: <code>{facts['displayed_detail_rows']}</code>; omitted: <code>{facts['omitted_detail_rows']}</code>.</p>{projection_table}{invariance_detail}{case_detail}</section>
<section aria-labelledby="i-heading"><h2 id="i-heading">I. Limitations</h2><ul>{limitations}</ul></section>
</main></body></html>
"""


_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_Topology = tuple[tuple[str, int, int, int], ...]


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _components(path: Path) -> list[Path]:
    current = _absolute(path)
    parts = []
    while True:
        parts.append(current)
        if current.parent == current:
            return list(reversed(parts))
        current = current.parent


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InputValidationError(
            "Report output path could not be inspected safely."
        ) from exc


def _is_reparse_point(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _validate_path_chain(path: Path, *, leaf_kind: str) -> Path:
    absolute = _absolute(path)
    components = _components(absolute)
    missing_seen = False
    for index, component in enumerate(components):
        info = _lstat(component)
        is_leaf = index == len(components) - 1
        if info is None:
            missing_seen = True
            continue
        if missing_seen:
            raise InputValidationError(
                "Report output topology changed during validation."
            )
        if _is_reparse_point(info):
            raise InputValidationError(
                "Report destination must not traverse a reparse point or symbolic link."
            )
        if not is_leaf or leaf_kind == "directory_or_missing":
            if not stat.S_ISDIR(info.st_mode):
                if is_leaf:
                    raise InputValidationError(
                        "Report output destination exists and is not a directory."
                    )
                raise InputValidationError(
                    "Report output path has a non-directory ancestor."
                )
        elif leaf_kind == "file_or_missing" and not stat.S_ISREG(info.st_mode):
            raise InputValidationError(
                "Report output target exists and is not a regular file."
            )
    return absolute


def _directory_topology(path: Path) -> _Topology:
    absolute = _validate_path_chain(path, leaf_kind="directory_or_missing")
    topology: list[tuple[str, int, int, int]] = []
    for component in _components(absolute):
        info = _lstat(component)
        if info is None:
            raise InputValidationError(
                "Report output topology changed during validation."
            )
        if _is_reparse_point(info) or not stat.S_ISDIR(info.st_mode):
            raise InputValidationError(
                "Report destination topology is no longer safe."
            )
        topology.append(
            (
                os.path.normcase(os.fspath(component)),
                int(info.st_dev),
                int(info.st_ino),
                int(stat.S_IFMT(info.st_mode)),
            )
        )
    return tuple(topology)


def _capture_directory_topology(path: Path) -> _Topology:
    first = _directory_topology(path)
    second = _directory_topology(path)
    if first != second:
        raise InputValidationError("Report output topology changed during validation.")
    return first


def _assert_directory_topology(path: Path, expected: _Topology) -> None:
    if _capture_directory_topology(path) != expected:
        raise InputValidationError("Report output topology changed during validation.")


def _paths_alias(left: Path, right: Path) -> bool:
    left_absolute = _absolute(left)
    right_absolute = _absolute(right)
    if os.path.normcase(os.fspath(left_absolute)) == os.path.normcase(
        os.fspath(right_absolute)
    ):
        return True
    if os.path.normcase(os.path.realpath(left_absolute)) == os.path.normcase(
        os.path.realpath(right_absolute)
    ):
        return True
    try:
        return os.path.samefile(left_absolute, right_absolute)
    except (FileNotFoundError, OSError):
        return False


def _reject_source_aliases(
    output_directory: Path,
    targets: tuple[Path, ...],
    source_paths: tuple[Path, ...],
) -> None:
    for destination in (output_directory, *targets):
        for source in source_paths:
            if _paths_alias(destination, source):
                raise InputValidationError(
                    "A report destination must not overwrite or alias a source input."
                )


def _write_temporary(
    target: Path,
    chunks: Iterable[bytes],
    *,
    output_directory: Path,
    topology: _Topology,
    expected_size: int,
    expected_sha256: str | None = None,
) -> Path:
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    descriptor: int | None = None
    completed = False
    try:
        _assert_directory_topology(output_directory, topology)
        _validate_path_chain(temporary, leaf_kind="file_or_missing")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            for chunk in chunks:
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if size != expected_size or (
            expected_sha256 is not None and digest.hexdigest() != expected_sha256
        ):
            raise InputValidationError(
                "Report output changed between preflight and temporary write."
            )
        _validate_path_chain(temporary, leaf_kind="file_or_missing")
        _assert_directory_topology(output_directory, topology)
        completed = True
        return temporary
    except OSError as exc:
        raise InputValidationError("Report output could not be written safely.") from exc
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        if not completed:
            with suppress(OSError):
                os.unlink(temporary)


def _json_chunks(report: dict[str, Any]) -> Iterable[bytes]:
    for chunk in iter_canonical_json(report):
        yield chunk.encode("utf-8")
    yield b"\n"


def _file_size_sha256(path: Path) -> tuple[int, str]:
    """Hash one validated ordinary file without buffering it in memory."""

    _validate_path_chain(path, leaf_kind="file_or_missing")
    before = _lstat(path)
    if before is None or not stat.S_ISREG(before.st_mode):
        raise InputValidationError(
            "Report recovery source is not an ordinary local file."
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (before.st_dev, before.st_ino)
        ):
            raise InputValidationError(
                "Report recovery source changed during validation."
            )
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
        if (
            (after.st_dev, after.st_ino, after.st_size)
            != (opened.st_dev, opened.st_ino, opened.st_size)
            or size != opened.st_size
        ):
            raise InputValidationError(
                "Report recovery source changed while it was read."
            )
        return size, digest.hexdigest()
    except OSError as exc:
        raise InputValidationError(
            "Report recovery source could not be read safely."
        ) from exc
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)


def _file_chunks(path: Path) -> Iterable[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            yield chunk


def _verify_file_bytes(path: Path, *, expected_size: int, expected_sha256: str) -> None:
    actual_size, actual_sha256 = _file_size_sha256(path)
    if actual_size != expected_size or actual_sha256 != expected_sha256:
        raise InputValidationError(
            "Report recovery output does not contain the expected bytes."
        )


def _publish_recovery_copy(
    target: Path,
    backup: Path,
    *,
    output_directory: Path,
    topology: _Topology,
    expected_size: int,
    expected_sha256: str,
) -> None:
    """Copy a backup through a fresh sibling while leaving the backup intact."""

    _assert_directory_topology(output_directory, topology)
    _validate_path_chain(target, leaf_kind="file_or_missing")
    _validate_path_chain(backup, leaf_kind="file_or_missing")
    _verify_file_bytes(
        backup, expected_size=expected_size, expected_sha256=expected_sha256
    )
    temporary = _write_temporary(
        target,
        _file_chunks(backup),
        output_directory=output_directory,
        topology=topology,
        expected_size=expected_size,
        expected_sha256=expected_sha256,
    )
    try:
        _assert_directory_topology(output_directory, topology)
        _validate_path_chain(backup, leaf_kind="file_or_missing")
        _verify_file_bytes(
            backup, expected_size=expected_size, expected_sha256=expected_sha256
        )
        _validate_path_chain(temporary, leaf_kind="file_or_missing")
        _validate_path_chain(target, leaf_kind="file_or_missing")
        os.replace(temporary, target)
        _assert_directory_topology(output_directory, topology)
        _validate_path_chain(target, leaf_kind="file_or_missing")
        _verify_file_bytes(
            target, expected_size=expected_size, expected_sha256=expected_sha256
        )
    finally:
        with suppress(OSError):
            os.unlink(temporary)


def _restore_report_member(
    target: Path,
    backup: Path,
    *,
    output_directory: Path,
    topology: _Topology,
    expected_size: int,
    expected_sha256: str,
) -> None:
    """Attempt primary and one fallback recovery without consuming the backup."""

    recovery_error: OSError | InputValidationError | None = None
    for _ in range(2):
        try:
            _publish_recovery_copy(
                target,
                backup,
                output_directory=output_directory,
                topology=topology,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
            )
            return
        except (OSError, InputValidationError) as exc:
            recovery_error = exc
    raise InputValidationError(
        "Report member recovery failed after primary and secondary attempts."
    ) from recovery_error


def _stabilized_human_reports(
    report: dict[str, Any], *, json_size: int, json_sha256: str, limits: Limits
) -> tuple[bytes, bytes, dict[str, int]]:
    sizes = {
        "json_report_bytes": json_size,
        "markdown_report_bytes": 0,
        "html_report_bytes": 0,
    }
    for _ in range(16):
        markdown_data = markdown_text(
            report,
            canonical_json_sha256=json_sha256,
            report_sizes=sizes,
        ).encode("utf-8")
        limits.enforce(
            "markdown_report_bytes", len(markdown_data), field_path="$report"
        )
        html_data = html_text(
            report,
            canonical_json_sha256=json_sha256,
            report_sizes=sizes,
        ).encode("utf-8")
        limits.enforce("html_report_bytes", len(html_data), field_path="$report")
        actual = {
            "json_report_bytes": json_size,
            "markdown_report_bytes": len(markdown_data),
            "html_report_bytes": len(html_data),
        }
        limits.enforce(
            "combined_report_bytes", sum(actual.values()), field_path="$report_bundle"
        )
        if actual == sizes:
            return markdown_data, html_data, actual
        sizes = actual
    raise InputValidationError("Human report size disclosure did not stabilize.")


def write_report_bundle(
    report: dict[str, Any],
    output_directory: Path,
    *,
    limits: Limits,
    source_paths: tuple[Path, ...] = (),
) -> tuple[Path, Path, Path]:
    """Preflight and atomically publish the five-member migrate packet."""

    output_directory = _absolute(output_directory)
    report_targets = (
        output_directory / "report.json",
        output_directory / "report.md",
        output_directory / "report.html",
    )
    targets = (
        *report_targets,
        output_directory / "review-queue.json",
        output_directory / "review-queue.md",
    )
    _reject_source_aliases(output_directory, targets, source_paths)
    _validate_path_chain(output_directory, leaf_kind="directory_or_missing")
    for target in targets:
        _validate_path_chain(target, leaf_kind="file_or_missing")
    json_size, json_sha256 = _canonical_size_hash(report)
    limits.enforce("json_report_bytes", json_size, field_path="$report")
    markdown_data, html_data, sizes = _stabilized_human_reports(
        report, json_size=json_size, json_sha256=json_sha256, limits=limits
    )
    queue = build_review_queue(report)
    verify_review_queue_binding(report, queue)
    queue_json_size, queue_json_sha256 = _canonical_size_hash(queue)
    queue_markdown_data = review_queue_markdown(queue).encode("utf-8")
    limits.enforce(
        "json_report_bytes", queue_json_size, field_path="$review_queue"
    )
    limits.enforce(
        "markdown_report_bytes",
        len(queue_markdown_data),
        field_path="$review_queue",
    )
    for name, size in sizes.items():
        limits.enforce(name, size, field_path="$report")
    limits.enforce(
        "combined_report_bytes",
        sum(sizes.values()) + queue_json_size + len(queue_markdown_data),
        field_path="$report_bundle",
    )
    try:
        output_directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InputValidationError("Report output directory could not be created.") from exc
    _validate_path_chain(output_directory, leaf_kind="directory_or_missing")
    topology = _capture_directory_topology(output_directory)
    _reject_source_aliases(output_directory, targets, source_paths)
    prepared: list[Path] = []
    backups: list[tuple[Path, Path, int, str]] = []
    published: list[Path] = []
    preserve_backups = False
    try:
        prepared.append(
            _write_temporary(
                targets[0],
                _json_chunks(report),
                output_directory=output_directory,
                topology=topology,
                expected_size=sizes["json_report_bytes"],
                expected_sha256=json_sha256,
            )
        )
        for target, data, size_name in (
            (targets[1], markdown_data, "markdown_report_bytes"),
            (targets[2], html_data, "html_report_bytes"),
        ):
            prepared.append(
                _write_temporary(
                    target,
                    (data,),
                    output_directory=output_directory,
                    topology=topology,
                    expected_size=(
                        sizes[size_name] if target in report_targets else len(data)
                    ),
                )
            )
        prepared.append(
            _write_temporary(
                targets[3],
                _json_chunks(queue),
                output_directory=output_directory,
                topology=topology,
                expected_size=queue_json_size,
                expected_sha256=queue_json_sha256,
            )
        )
        del queue
        prepared.append(
            _write_temporary(
                targets[4],
                (queue_markdown_data,),
                output_directory=output_directory,
                topology=topology,
                expected_size=len(queue_markdown_data),
            )
        )
        for target in targets:
            _assert_directory_topology(output_directory, topology)
            _validate_path_chain(target, leaf_kind="file_or_missing")
            if _lstat(target) is None:
                continue
            backup = target.with_name(f".{target.name}.{uuid.uuid4().hex}.backup")
            _validate_path_chain(backup, leaf_kind="file_or_missing")
            if _lstat(backup) is not None:
                raise InputValidationError(
                    "Report backup destination changed during validation."
                )
            _reject_source_aliases(output_directory, targets, source_paths)
            expected_size, expected_sha256 = _file_size_sha256(target)
            try:
                os.replace(target, backup)
            except OSError as exc:
                raise InputValidationError(
                    "Existing report bundle could not be staged safely."
                ) from exc
            backups.append((target, backup, expected_size, expected_sha256))
            _assert_directory_topology(output_directory, topology)
            _validate_path_chain(backup, leaf_kind="file_or_missing")
            _verify_file_bytes(
                backup,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
            )
        for target, temporary in zip(targets, prepared, strict=True):
            _assert_directory_topology(output_directory, topology)
            _validate_path_chain(target, leaf_kind="file_or_missing")
            _validate_path_chain(temporary, leaf_kind="file_or_missing")
            _reject_source_aliases(output_directory, targets, source_paths)
            try:
                os.replace(temporary, target)
            except OSError as exc:
                raise InputValidationError(
                    "Report output could not be replaced safely."
                ) from exc
            published.append(target)
            _assert_directory_topology(output_directory, topology)
            _validate_path_chain(target, leaf_kind="file_or_missing")
    except InputValidationError as exc:
        rollback_error: OSError | InputValidationError | None = None
        backed_up_targets = {target for target, _, _, _ in backups}
        for target in reversed(published):
            if target in backed_up_targets:
                continue
            try:
                _validate_path_chain(target, leaf_kind="file_or_missing")
                os.unlink(target)
            except (OSError, InputValidationError) as rollback_exc:
                rollback_error = rollback_error or rollback_exc
        failed_members: list[tuple[Path, Path, str]] = []
        for target, backup, expected_size, expected_sha256 in reversed(backups):
            try:
                _restore_report_member(
                    target,
                    backup,
                    output_directory=output_directory,
                    topology=topology,
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                )
            except (OSError, InputValidationError) as rollback_exc:
                rollback_error = rollback_error or rollback_exc
                failed_members.append((target, backup, expected_sha256))
        if rollback_error is not None:
            preserve_backups = True
            recovery_details = ", ".join(
                f"{target.name} (backup={backup.name}, sha256={expected_sha256})"
                for target, backup, expected_sha256 in failed_members
            )
            raise InputValidationError(
                "Report publication failed and report-bundle recovery is incomplete; "
                f"preserved recovery material: {recovery_details or 'see report backups'}."
            ) from exc
        raise
    finally:
        for temporary in prepared:
            with suppress(OSError):
                os.unlink(temporary)
        if not preserve_backups:
            for _, backup, _, _ in backups:
                with suppress(OSError):
                    os.unlink(backup)
    return report_targets
