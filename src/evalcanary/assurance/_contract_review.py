"""Internal, read-only contract review over normatively validated evidence."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from .. import __version__
from .constants import METRICS, ROLES, STATUSES
from .numeric import canonical_json_bytes, canonical_sha256
from .preflight import MAX_PREFLIGHT_DIAGNOSTICS
from .review_queue import _pointer, report_file_sha256
from .schema import AssuranceContract, Limits
from .structural import METRIC_SIGNATURES

_SCHEMA = "evaluator-assurance-contract-review-v1"
_DETAIL_LIMIT = MAX_PREFLIGHT_DIAGNOSTICS
_BOUNDARY = (
    "Covered means at least one explicit rule, not sufficient policy. "
    "Not covered does not mean bad, a defect, or a recommendation. "
    "More rules or all metrics covered do not establish safety. "
    "Not evaluable does not mean failed; existing missing-evidence policy remains authoritative. "
    "Not observed describes only this input, not absence in reality. "
    "Unknown and untested remain unknown and untested."
)


def _bounded(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total_findings": len(rows),
        "displayed_findings": min(len(rows), _DETAIL_LIMIT),
        "omitted_findings": max(0, len(rows) - _DETAIL_LIMIT),
        "detail_limit": _DETAIL_LIMIT,
        "findings": rows[:_DETAIL_LIMIT],
    }


def _observation(
    contract: AssuranceContract, kind: str, **content: Any
) -> dict[str, Any]:
    core = {"kind": kind, **content}
    return {
        "finding_id": canonical_sha256(
            {
                "schema_version": _SCHEMA,
                "contract_sha256": contract.source_sha256,
                **core,
            }
        ),
        **core,
    }


def _coverage(contract: AssuranceContract, report: dict[str, Any]) -> dict[str, Any]:
    rules = contract.document["rules"]
    metric_counts: Counter[str] = Counter()
    signatures: Counter[tuple[str, str, str | None]] = Counter()
    status_selectors: Counter[tuple[str, str]] = Counter()
    first_metric: dict[str, str] = {}
    first_signature: dict[tuple[str, str, str | None], str] = {}
    first_status: dict[tuple[str, str], str] = {}
    results = {item["rule_id"]: item for item in report["rule_results"]}
    availability: Counter[str] = Counter()
    selected = []
    for index, rule in enumerate(rules):
        pointer = _pointer("rules", index)
        metric = rule["metric"]
        role = rule["parameters"].get("role")
        signature = (metric, rule["scope"], role)
        metric_counts[metric] += 1
        signatures[signature] += 1
        first_metric.setdefault(metric, pointer)
        first_signature.setdefault(signature, pointer)
        if metric == "status_count" and rule["scope"] == "all_cases":
            status_key = (role, rule["parameters"]["status"])
            status_selectors[status_key] += 1
            first_status.setdefault(status_key, pointer)
        result = results.get(rule["rule_id"])
        state = (
            "unknown"
            if result is None
            else {
                "missing": "not evaluable",
                "not_applicable": "not applicable",
                "satisfied": "observed",
                "violated": "observed",
            }[result["result"]]
        )
        availability[state] += 1
        selected.append(
            _observation(
                contract,
                "rule_evidence",
                contract_pointer=pointer,
                rule_id=rule["rule_id"],
                metric=metric,
                scope=rule["scope"],
                scope_id=rule["scope_id"],
                explicit_role=role,
                availability=state,
                reason="contract_not_evaluated"
                if result is None
                else result["evidence"].get("reason"),
            )
        )

    metric_rows = [
        _observation(
            contract,
            "metric",
            metric=metric,
            coverage="covered" if metric_counts[metric] else "not covered",
            rule_count=metric_counts[metric],
            contract_pointer=first_metric.get(metric, ""),
        )
        for metric in sorted(METRICS)
    ]
    signature_rows = []
    for metric, (scopes, parameters) in sorted(METRIC_SIGNATURES.items()):
        roles: list[str | None] = (
            list(sorted(ROLES)) if "role" in parameters else [None]
        )
        for scope in sorted(scopes):
            for role in roles:
                key = (metric, scope, role)
                signature_rows.append(
                    _observation(
                        contract,
                        "metric_scope_role",
                        metric=metric,
                        scope=scope,
                        explicit_role=role,
                        coverage="covered" if signatures[key] else "not covered",
                        rule_count=signatures[key],
                        contract_pointer=first_signature.get(key, ""),
                    )
                )

    observed: Counter[tuple[str, str]] = Counter(
        (role, trial["status"])
        for case in report["cases"]
        for role in sorted(ROLES)
        for trial in case["trials"][role]
    )
    status_rows = [
        _observation(
            contract,
            "trial_status",
            role=role,
            status=status,
            observation="observed" if observed[(role, status)] else "not observed",
            observed_trial_count=observed[(role, status)],
            coverage="covered" if status_selectors[(role, status)] else "not covered",
            rule_count=status_selectors[(role, status)],
            contract_pointer=first_status.get((role, status), ""),
        )
        for role in sorted(ROLES)
        for status in sorted(STATUSES)
    ]
    return {
        "metrics": {
            "denominator": "All supported locked metric names; any explicit rule for a name counts once.",
            "denominator_count": len(METRICS),
            "covered_count": len(metric_counts),
            "not_covered_count": len(METRICS) - len(metric_counts),
            **_bounded(metric_rows),
        },
        "metric_scope_roles": {
            "denominator": "All METRIC_SIGNATURES scope types, crossed with ROLES only when a role parameter is defined; null means no explicit role parameter. Scope IDs and other parameter values are not enumerated.",
            "denominator_count": len(signature_rows),
            "covered_count": len(signatures),
            "not_covered_count": len(signature_rows) - len(signatures),
            **_bounded(signature_rows),
        },
        "trial_status_evidence": {
            "denominator": "The two registered roles crossed with the four registered trial statuses in the supplied evidence.",
            "denominator_count": len(ROLES) * len(STATUSES),
            "correspondence": "Only an all_cases status_count rule with exactly this role and status counts here. Other metrics and subset rules are not inferred to address this selector.",
            **_bounded(status_rows),
        },
        "rules": {
            "availability_counts": {
                state: availability[state]
                for state in ("observed", "not evaluable", "not applicable", "unknown")
            },
            "availability_source": "Existing report rule_results; no result means unknown, not evaluated. Observed includes satisfied and violated; this is not a policy disposition.",
            **_bounded(selected),
        },
    }


def _lint(contract: AssuranceContract) -> dict[str, Any]:
    fields = (
        "metric",
        "scope",
        "scope_id",
        "parameters",
        "operator",
        "threshold",
        "severity",
        "missing_evidence",
    )
    first: dict[bytes, int] = {}
    findings = []
    for index, rule in enumerate(contract.document["rules"]):
        key = canonical_json_bytes({field: rule[field] for field in fields})
        if key not in first:
            first[key] = index
            continue
        findings.append(
            _observation(
                contract,
                "contract_lint",
                code="REPEATED_EVALUATION_FIELDS",
                level="WARNING",
                contract_pointer=_pointer("rules", index),
                first_rule_pointer=_pointer("rules", first[key]),
                message="These rules have identical evaluation fields. Their identities, rationales and metadata may serve different human purposes.",
            )
        )
    return {
        "stage": "NORMATIVELY_VALID_CONTRACT_ONLY",
        "level_definitions": {
            "WARNING": "A valid contract contains provably repeated evaluation fields; no policy concern or intent is inferred."
        },
        "operative_fields": list(fields),
        "boundary": "No recommendation, contradiction inference, policy rating or automatic fix. Rule identities, rationales and extensions remain unchanged.",
        **_bounded(findings),
    }


def _review_contract(
    contract: AssuranceContract, report: dict[str, Any]
) -> dict[str, Any]:
    """Project a validated contract and its freshly built canonical report."""

    return {
        "schema_version": _SCHEMA,
        "tool_version": __version__,
        "mode": "ADVISORY_MECHANICAL_REVIEW",
        "contract": report["contract"],
        "input": report["input"],
        "report": {
            "schema_version": report["schema_version"],
            "assurance_engine_version": report["assurance_engine_version"],
            "report_id": report["report_id"],
            "source_sha256": report_file_sha256(report),
            "evidence_status": report["evidence_status"],
            "isolation_status": report["isolation_status"],
        },
        "boundary": _BOUNDARY,
        "pointer_convention": "RFC 6901 against the exact contract; empty string is the contract root. Aggregate covered rows point to the first matching rule; absence rows point to root.",
        "ordering": "Metric, scope and role vocabulary is lexical; rule details follow contract array order. Counts include omitted rows.",
        "coverage": _coverage(contract, report),
        "lint": _lint(contract),
    }


def _review_text(review: dict[str, Any], limits: Limits) -> str:
    text = json.dumps(review, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    limits.enforce(
        "json_report_bytes", len(text.encode("utf-8")), field_path="contract_review"
    )
    return text
