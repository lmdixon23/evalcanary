"""Three deterministic projections from one canonical assurance report model."""

from __future__ import annotations

import html
import os
import uuid
from collections import Counter
from contextlib import suppress
from pathlib import Path
from typing import Any

from ..errors import InputValidationError
from .numeric import canonical_json_bytes, canonical_json_text
from .schema import Limits


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


def _priority_facts(report: dict[str, Any]) -> dict[str, list[tuple[str, ...]]]:
    rules: list[tuple[str, ...]] = [
        (
            str(item["rule_id"]),
            str(item["severity"]),
            str(item["metric"]),
            str(item["result"]),
        )
        for item in report["rule_results"]
    ]
    critical: list[tuple[str, ...]] = []
    for item in report["critical_groups"]:
        transitions = item["transitions"]["label_transitions"]
        critical.append(
            (
                str(item["group_id"]),
                str(len(item["member_case_ids"])),
                str(item["pairing"]["valid_pair_count"]),
                str(sum(transitions.values())),
            )
        )
    invariance: list[tuple[str, ...]] = []
    for item in report["invariance_groups"]:
        for role in ("baseline", "candidate"):
            counts = Counter(instance["result"] for instance in item["roles"][role])
            invariance.append(
                (
                    str(item["group_id"]),
                    role,
                    str(counts["satisfied"]),
                    str(counts["violated"]),
                    str(counts["not_evaluable"]),
                )
            )
    anchors: list[tuple[str, ...]] = []
    for item in report["anchor_sets"]:
        for role in ("baseline", "candidate"):
            role_fact = item["roles"][role]
            anchors.append(
                (
                    str(item["anchor_set_id"]),
                    role,
                    _ratio(item["coverage"]),
                    str(item["raw_annotation_count"]),
                    str(role_fact["exact_label_agreements"]),
                    str(role_fact["exact_label_disagreements"]),
                )
            )
    repeat: list[tuple[str, ...]] = []
    for role in ("baseline", "candidate"):
        fact = report["repeat_diagnostics"][role]
        cases = fact["cases"]
        repeat.append(
            (
                role,
                str(fact["trial_count"]),
                _ratio(fact["determinate_coverage"]),
                str(sum(bool(item["status_instability"]) for item in cases)),
                str(sum(bool(item["label_instability"]) for item in cases)),
                str(sum(item["score_instability"] is True for item in cases)),
            )
        )
    deltas = list(report["provenance"]["evaluation_delta"].values()) + list(
        report["provenance"]["component_delta"].values()
    )
    provenance_counts = Counter(item["delta"] for item in deltas)
    provenance: list[tuple[str, ...]] = [
        (
            str(provenance_counts[name]),
            name,
        )
        for name in (
            "same",
            "changed",
            "missing_before",
            "missing_after",
            "missing_both",
            "omitted",
        )
    ]
    return {
        "rules": rules,
        "critical": critical,
        "invariance": invariance,
        "anchors": anchors,
        "repeat": repeat,
        "provenance": provenance,
    }


def _markdown_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> list[str]:
    if not rows:
        return ["No evidence was declared for this section.", ""]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(f"`{value}`" for value in row) + " |")
    lines.append("")
    return lines


def markdown_text(report: dict[str, Any]) -> str:
    canonical = canonical_json_text(report)
    facts = _priority_facts(report)
    lines = [
        "# EvalCanary evaluator-assurance report",
        "",
        f"- Report ID: `{report['report_id']}`",
        f"- Evidence status: **{report['evidence_status']}**",
        f"- Isolation status: **{report['isolation_status']}**",
        f"- Contract status: **{report['contract_status']}**",
        f"- Report status: **{report['report_status']}**",
        "",
        "## Priority findings",
        "",
    ]
    warnings = report.get("warnings", [])
    lines.extend(f"- {str(item).replace(chr(10), ' ')}" for item in warnings)
    if not warnings:
        lines.append("- No system review warning was emitted.")
    lines.extend(["", "## Contract findings", ""])
    lines.extend(
        _markdown_table(
            ("Rule", "Severity", "Metric", "Result"), facts["rules"]
        )
    )
    lines.extend(["## Critical groups", ""])
    lines.extend(
        _markdown_table(
            ("Group", "Cases", "Valid pairs", "Label transitions"),
            facts["critical"],
        )
    )
    lines.extend(["## Invariance results", ""])
    lines.extend(
        _markdown_table(
            ("Group", "Role", "Satisfied", "Violated", "Not evaluable"),
            facts["invariance"],
        )
    )
    lines.extend(["## Human-anchor diagnostics", ""])
    lines.extend(
        _markdown_table(
            ("Anchor set", "Role", "Coverage", "Raw", "Agree", "Disagree"),
            facts["anchors"],
        )
    )
    lines.extend(["## Repeat and pairing diagnostics", ""])
    lines.extend(
        _markdown_table(
            ("Role", "Trials", "Coverage", "Status unstable", "Label unstable", "Score unstable"),
            facts["repeat"],
        )
    )
    pairing = report["pairing"]
    lines.append(
        f"Overall valid pairing coverage is `{_ratio(pairing['pairing_coverage'])}`; "
        f"incomplete cases: `{len(pairing['incomplete_case_ids'])}`."
    )
    lines.extend(["", "## Provenance completeness", ""])
    lines.extend(_markdown_table(("Fields", "Delta"), facts["provenance"]))
    links = _safe_links(report)
    if links:
        lines.extend(["", "## Typed public references", ""])
        for label, target in links:
            if not any(character in target for character in '<>"'):
                lines.append(f"- [{label}](<{target}>)")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(
        [
            "",
            "## Canonical facts",
            "",
            "Every material fact in the canonical JSON report is reproduced below.",
            "",
        ]
    )
    lines.extend("    " + line for line in canonical.splitlines() or [canonical])
    lines.append("")
    return "\n".join(lines)


def _html_table(
    caption: str, headers: tuple[str, ...], rows: list[tuple[str, ...]]
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


def html_text(report: dict[str, Any]) -> str:
    canonical = html.escape(canonical_json_text(report))
    facts = _priority_facts(report)
    warnings = "".join(
        f"<li>{html.escape(str(item))}</li>" for item in report.get("warnings", [])
    )
    if not warnings:
        warnings = "<li>No system review warning was emitted.</li>"
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
    contract_table = _html_table(
        "Contract rule findings",
        ("Rule", "Severity", "Metric", "Result"),
        facts["rules"],
    )
    critical_table = _html_table(
        "Critical-group evidence",
        ("Group", "Cases", "Valid pairs", "Label transitions"),
        facts["critical"],
    )
    invariance_table = _html_table(
        "Declared invariance outcomes",
        ("Group", "Role", "Satisfied", "Violated", "Not evaluable"),
        facts["invariance"],
    )
    anchor_table = _html_table(
        "Human-anchor evidence",
        ("Anchor set", "Role", "Coverage", "Raw", "Agree", "Disagree"),
        facts["anchors"],
    )
    repeat_table = _html_table(
        "Repeat diagnostics",
        ("Role", "Trials", "Coverage", "Status unstable", "Label unstable", "Score unstable"),
        facts["repeat"],
    )
    provenance_table = _html_table(
        "Provenance delta states", ("Fields", "Delta"), facts["provenance"]
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
<section aria-labelledby="status-heading"><h2 id="status-heading">Status</h2>
<table><caption>Evidence and contract status</caption><thead><tr><th scope="col">Dimension</th><th scope="col">Value</th></tr></thead><tbody>
<tr><th scope="row">Evidence</th><td class="status">{html.escape(str(report["evidence_status"]))}</td></tr>
<tr><th scope="row">Isolation</th><td class="status">{html.escape(str(report["isolation_status"]))}</td></tr>
<tr><th scope="row">Contract</th><td class="status">{html.escape(str(report["contract_status"]))}</td></tr>
<tr><th scope="row">Overall report</th><td class="status">{html.escape(str(report["report_status"]))}</td></tr>
</tbody></table></section>
<section aria-labelledby="warning-heading"><h2 id="warning-heading">Priority findings</h2><ul>{warnings}</ul></section>
<section aria-labelledby="contract-heading"><h2 id="contract-heading">Contract findings</h2>{contract_table}</section>
<section aria-labelledby="critical-heading"><h2 id="critical-heading">Critical groups</h2>{critical_table}</section>
<section aria-labelledby="invariance-heading"><h2 id="invariance-heading">Invariance results</h2>{invariance_table}</section>
<section aria-labelledby="anchor-heading"><h2 id="anchor-heading">Human-anchor diagnostics</h2>{anchor_table}</section>
<section aria-labelledby="repeat-heading"><h2 id="repeat-heading">Repeat and pairing diagnostics</h2>{repeat_table}<p>{pairing_summary}</p></section>
<section aria-labelledby="provenance-heading"><h2 id="provenance-heading">Provenance completeness</h2>{provenance_table}</section>
<section aria-labelledby="reference-heading"><h2 id="reference-heading">Typed public references</h2><ul>{links}</ul></section>
<section aria-labelledby="limitations-heading"><h2 id="limitations-heading">Limitations</h2><ul>{limitations}</ul></section>
<section aria-labelledby="facts-heading"><h2 id="facts-heading">Canonical facts</h2><p>Every material fact in the canonical JSON report is reproduced below.</p><pre>{canonical}</pre></section>
</main></body></html>
"""


def _reject_symlink_path(path: Path) -> None:
    current = path.absolute()
    while True:
        if current.exists() and current.is_symlink():
            raise InputValidationError(
                "Report destination must not traverse a symbolic link."
            )
        if current.parent == current:
            break
        current = current.parent


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        with suppress(OSError):
            temporary.chmod(0o600)
        os.replace(temporary, path)
    except OSError as exc:
        raise InputValidationError("Report output could not be written safely.") from exc
    finally:
        with suppress(OSError):
            if temporary.exists():
                temporary.unlink()


def write_report_bundle(
    report: dict[str, Any],
    output_directory: Path,
    *,
    limits: Limits,
    source_paths: tuple[Path, ...] = (),
) -> tuple[Path, Path, Path]:
    """Preflight all formats, then write temporary siblings and atomically replace."""

    _reject_symlink_path(output_directory)
    if output_directory.exists() and not output_directory.is_dir():
        raise InputValidationError(
            "Report output destination exists and is not a directory."
        )
    json_data = json_bytes(report)
    markdown_data = markdown_text(report).encode("utf-8")
    html_data = html_text(report).encode("utf-8")
    sizes = {
        "json_report_bytes": len(json_data),
        "markdown_report_bytes": len(markdown_data),
        "html_report_bytes": len(html_data),
    }
    for name, size in sizes.items():
        limits.enforce(name, size, field_path="$report")
    limits.enforce(
        "combined_report_bytes", sum(sizes.values()), field_path="$report_bundle"
    )
    targets = (
        output_directory / "report.json",
        output_directory / "report.md",
        output_directory / "report.html",
    )
    for target in targets:
        _reject_symlink_path(target)
    source_resolved = {item.resolve() for item in source_paths}
    if any(target.resolve() in source_resolved for target in targets):
        raise InputValidationError(
            "A report destination must not overwrite a source input."
        )
    try:
        output_directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InputValidationError("Report output directory could not be created.") from exc
    _reject_symlink_path(output_directory)
    for target, data in zip(
        targets, (json_data, markdown_data, html_data), strict=True
    ):
        _atomic_write(target, data)
    return targets
