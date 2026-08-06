"""JSON, Markdown, and self-contained accessible HTML reports."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .models import ComparisonSummary


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def _number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.6g}"


def write_json(summary: ComparisonSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            summary.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def markdown_text(summary: ComparisonSummary) -> str:
    policy_label = "NOT CONFIGURED"
    if summary.policy.get("configured"):
        policy_label = "PASS" if summary.policy.get("passed") else "FAIL"
    lines = [
        "# EvalCanary evaluator migration report",
        "",
        f"- Run ID: `{summary.run_id}`",
        f"- Created: `{summary.created_at}`",
        f"- Fixed cases: **{summary.total_cases}**",
        f"- Comparable cases: **{summary.comparable_cases}**",
        f"- Error cases: **{summary.error_cases}**",
        f"- Policy: **{policy_label}**",
        "",
        "## Result",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Before pass rate | {_pct(summary.before_rate)} |",
        f"| After pass rate | {_pct(summary.after_rate)} |",
        f"| Delta | {_pct(summary.delta)} |",
        (
            "| Paired bootstrap 95% interval | "
            f"{_pct(summary.bootstrap_ci_low)} to "
            f"{_pct(summary.bootstrap_ci_high)} |"
        ),
        f"| Exact McNemar p-value | {_number(summary.mcnemar_p_value)} |",
        "",
        "## Transition matrix",
        "",
        "| | After pass | After fail |",
        "|---|---:|---:|",
        f"| Before pass | {summary.stable_pass} | {summary.pass_to_fail} |",
        f"| Before fail | {summary.fail_to_pass} | {summary.stable_fail} |",
        "",
    ]
    if summary.policy.get("checks"):
        lines.extend(
            [
                "## Policy checks",
                "",
                "| Check | Result | Actual | Limit |",
                "|---|---|---:|---:|",
            ]
        )
        for item in summary.policy["checks"]:
            result = "PASS" if item["passed"] else "FAIL"
            lines.append(
                f"| `{item['name']}` | {result} | "
                f"{item['actual']} | {item['limit']} |"
            )
        lines.append("")
    if summary.slices:
        lines.extend(
            [
                "## Slice analysis",
                "",
                "| Slice | Value | Cases | Before | After | Delta | Changed |",
                "|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for item in summary.slices:
            changed = item.pass_to_fail + item.fail_to_pass
            lines.append(
                f"| `{item.slice_name}` | {item.slice_value} | "
                f"{item.total_cases} | {_pct(item.before_rate)} | "
                f"{_pct(item.after_rate)} | {_pct(item.delta)} | {changed} |"
            )
        lines.append("")
    lines.extend(["## Changed cases", ""])
    if not summary.changed_cases:
        lines.append("No comparable pass/fail verdicts changed.")
    else:
        lines.extend(
            [
                "| Case | Transition | Before reason | After reason |",
                "|---|---|---|---|",
            ]
        )
        for item in summary.changed_cases:
            before_reason = (item.before.reason or "").replace(
                "|", "\\|"
            ).replace("\n", " ")
            after_reason = (item.after.reason or "").replace(
                "|", "\\|"
            ).replace("\n", " ")
            lines.append(
                f"| `{item.case_id}` | `{item.transition}` | "
                f"{before_reason} | {after_reason} |"
            )
    lines.extend(
        [
            "",
            "## Verifier source diff",
            "",
            "```diff",
            summary.verifier_diff or "No textual source difference.",
            "```",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in summary.limitations)
    lines.append("")
    return "\n".join(lines)


def write_markdown(summary: ComparisonSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text(summary), encoding="utf-8")


def _escaped_json(value: Any) -> str:
    return html.escape(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    )


def html_text(summary: ComparisonSummary) -> str:
    policy_configured = bool(summary.policy.get("configured"))
    policy_passed = (
        bool(summary.policy.get("passed")) if policy_configured else True
    )
    policy_label = (
        "Not configured"
        if not policy_configured
        else ("Pass" if policy_passed else "Fail")
    )
    policy_class = (
        "neutral"
        if not policy_configured
        else ("pass" if policy_passed else "fail")
    )

    changed_rows = "".join(
        "<tr>"
        f"<td data-label=\"Case\"><code>{html.escape(item.case_id)}</code></td>"
        f"<td data-label=\"Transition\">{html.escape(item.transition)}</td>"
        f"<td data-label=\"Before reason\">{html.escape(item.before.reason or '')}</td>"
        f"<td data-label=\"After reason\">{html.escape(item.after.reason or '')}</td>"
        "</tr>"
        for item in summary.changed_cases
    ) or '<tr><td colspan="4">No comparable verdicts changed.</td></tr>'

    slice_rows = "".join(
        "<tr>"
        f"<td data-label=\"Slice\"><code>{html.escape(item.slice_name)}</code></td>"
        f"<td data-label=\"Value\">{html.escape(item.slice_value)}</td>"
        f"<td data-label=\"Cases\">{item.total_cases}</td>"
        f"<td data-label=\"Before\">{_pct(item.before_rate)}</td>"
        f"<td data-label=\"After\">{_pct(item.after_rate)}</td>"
        f"<td data-label=\"Delta\">{_pct(item.delta)}</td>"
        f"<td data-label=\"Changed\">{item.pass_to_fail + item.fail_to_pass}</td>"
        "</tr>"
        for item in summary.slices
    ) or '<tr><td colspan="7">No slice paths were requested.</td></tr>'

    policy_rows = "".join(
        "<tr>"
        f"<td data-label=\"Check\"><code>{html.escape(str(item['name']))}</code></td>"
        f"<td data-label=\"Result\"><span class=\"badge "
        f"{'pass' if item['passed'] else 'fail'}\">"
        f"{'PASS' if item['passed'] else 'FAIL'}</span></td>"
        f"<td data-label=\"Actual\">{html.escape(str(item['actual']))}</td>"
        f"<td data-label=\"Limit\">{html.escape(str(item['limit']))}</td>"
        "</tr>"
        for item in summary.policy.get("checks", [])
    ) or '<tr><td colspan="4">No policy checks were configured.</td></tr>'

    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in summary.limitations
    )
    source_diff = html.escape(
        summary.verifier_diff or "No textual source difference."
    )
    provenance = _escaped_json(summary.provenance)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EvalCanary report {html.escape(summary.run_id)}</title>
<style>
:root {{ color-scheme: light dark; --bg:#f6f8fb; --panel:#fff; --text:#172b4d; --muted:#5d6b82; --line:#d8dee8; --accent:#d39b16; --pass:#137333; --fail:#b42318; --neutral:#5d6b82; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#101722; --panel:#182231; --text:#e9eef7; --muted:#aeb9ca; --line:#344258; --accent:#f0bd3d; --pass:#56c271; --fail:#ff8179; --neutral:#aeb9ca; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif; }}
main {{ max-width:1180px; margin:auto; padding:clamp(1rem,3vw,2.5rem); }}
h1 {{ margin-bottom:.25rem; }} .lede {{ color:var(--muted); max-width:75ch; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:1rem; margin:1.5rem 0; }}
.card, section {{ background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:1rem; box-shadow:0 4px 18px rgb(0 0 0 / .05); }}
.card strong {{ display:block; font-size:1.5rem; margin-top:.2rem; }}
section {{ margin:1rem 0; overflow:auto; }}
table {{ width:100%; border-collapse:collapse; min-width:620px; }}
table.compact {{ min-width:0; }}
th,td {{ text-align:left; padding:.65rem; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ color:var(--muted); font-size:.9rem; }}
code,pre {{ font-family:ui-monospace,SFMono-Regular,Consolas,monospace; }}
pre {{ white-space:pre-wrap; overflow-wrap:anywhere; padding:1rem; background:var(--bg); border-radius:10px; border:1px solid var(--line); }}
.badge {{ display:inline-block; padding:.15rem .55rem; border-radius:999px; font-weight:700; }}
.badge.pass {{ color:var(--pass); border:1px solid currentColor; }}
.badge.fail {{ color:var(--fail); border:1px solid currentColor; }}
.badge.neutral {{ color:var(--neutral); border:1px solid currentColor; }}
a:focus-visible, summary:focus-visible {{ outline:3px solid var(--accent); outline-offset:3px; }}
@media (max-width:620px) {{
  main {{ padding:.8rem; }} section {{ border-radius:10px; }}
  table.responsive {{ min-width:0; }}
  table.responsive thead {{ position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }}
  table.responsive tbody, table.responsive tr, table.responsive td {{ display:block; width:100%; }}
  table.responsive tr {{ padding:.55rem 0; border-bottom:1px solid var(--line); }}
  table.responsive td {{ display:grid; grid-template-columns:minmax(7.5rem,40%) 1fr; gap:.6rem; border:0; padding:.3rem 0; overflow-wrap:anywhere; }}
  table.responsive td::before {{ content:attr(data-label); color:var(--muted); font-weight:700; }}
}}
@media print {{ body {{ background:white; color:black; }} .card,section {{ box-shadow:none; break-inside:avoid; }} }}
</style>
</head>
<body>
<main>
<header>
<h1>EvalCanary evaluator migration report</h1>
<p class="lede">A fixed-corpus comparison of two evaluator versions. Changed verdicts establish evaluator sensitivity; they do not establish which evaluator is correct.</p>
<p><code>Run {html.escape(summary.run_id)}</code> - {html.escape(summary.created_at)}</p>
</header>
<div class="grid" aria-label="Comparison summary">
<div class="card"><span>Before pass rate</span><strong>{_pct(summary.before_rate)}</strong></div>
<div class="card"><span>After pass rate</span><strong>{_pct(summary.after_rate)}</strong></div>
<div class="card"><span>Rate change</span><strong>{_pct(summary.delta)}</strong></div>
<div class="card"><span>Changed verdicts</span><strong>{summary.pass_to_fail + summary.fail_to_pass}</strong></div>
<div class="card"><span>Error cases</span><strong>{summary.error_cases}</strong></div>
<div class="card"><span>Policy</span><strong><span class="badge {policy_class}">{policy_label}</span></strong></div>
</div>
<section aria-labelledby="transition-heading"><h2 id="transition-heading">Transition matrix</h2>
<table class="compact"><thead><tr><th></th><th>After pass</th><th>After fail</th></tr></thead><tbody>
<tr><th>Before pass</th><td>{summary.stable_pass}</td><td>{summary.pass_to_fail}</td></tr>
<tr><th>Before fail</th><td>{summary.fail_to_pass}</td><td>{summary.stable_fail}</td></tr>
</tbody></table>
<p>Paired bootstrap 95% interval: {_pct(summary.bootstrap_ci_low)} to {_pct(summary.bootstrap_ci_high)}. Exact McNemar p-value: {_number(summary.mcnemar_p_value)}.</p></section>
<section aria-labelledby="policy-heading"><h2 id="policy-heading">Policy checks</h2><table class="responsive"><thead><tr><th>Check</th><th>Result</th><th>Actual</th><th>Limit</th></tr></thead><tbody>{policy_rows}</tbody></table></section>
<section aria-labelledby="slice-heading"><h2 id="slice-heading">Slice analysis</h2><table class="responsive"><thead><tr><th>Slice</th><th>Value</th><th>Cases</th><th>Before</th><th>After</th><th>Delta</th><th>Changed</th></tr></thead><tbody>{slice_rows}</tbody></table></section>
<section aria-labelledby="changed-heading"><h2 id="changed-heading">Changed cases</h2><table class="responsive"><thead><tr><th>Case</th><th>Transition</th><th>Before reason</th><th>After reason</th></tr></thead><tbody>{changed_rows}</tbody></table></section>
<section aria-labelledby="diff-heading"><h2 id="diff-heading">Verifier source diff</h2><pre>{source_diff}</pre></section>
<section aria-labelledby="provenance-heading"><h2 id="provenance-heading">Provenance</h2><pre>{provenance}</pre></section>
<section aria-labelledby="limits-heading"><h2 id="limits-heading">Limitations</h2><ul>{limitations}</ul></section>
</main>
</body>
</html>
"""


def write_html(summary: ComparisonSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text(summary), encoding="utf-8")
