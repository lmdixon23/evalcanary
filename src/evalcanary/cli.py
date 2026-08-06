"""Command-line interface for EvalCanary."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .compare import compare_verdicts
from .errors import EvalCanaryError, InputValidationError
from .io import load_cases
from .policy import evaluate_policy, load_policy
from .reports import write_html, write_json, write_markdown
from .runner import run_verifier

EXIT_OK = 0
EXIT_POLICY_FAIL = 2
EXIT_ERROR = 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evalcanary",
        description="Catch evaluation drift before it ships.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"EvalCanary {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    diff = sub.add_parser(
        "diff",
        help=(
            "Compare two trusted Python verifier versions on one fixed "
            "JSONL corpus."
        ),
    )
    diff.add_argument(
        "--data",
        type=Path,
        required=True,
        help="JSONL file with a unique id on every object.",
    )
    diff.add_argument(
        "--before",
        type=Path,
        required=True,
        help="Trusted Python verifier defining verify(case).",
    )
    diff.add_argument(
        "--after",
        type=Path,
        required=True,
        help="Trusted Python verifier defining verify(case).",
    )
    diff.add_argument(
        "--out",
        type=Path,
        default=Path("evalcanary-report"),
        help="Output directory.",
    )
    diff.add_argument(
        "--policy", type=Path, help="Optional TOML migration policy."
    )
    diff.add_argument(
        "--slice",
        action="append",
        default=[],
        help="Repeatable dotted JSON path for subgroup analysis.",
    )
    diff.add_argument(
        "--include-content",
        action="store_true",
        help=(
            "Include original case payloads in JSON output. Off by default "
            "for privacy."
        ),
    )
    diff.add_argument(
        "--include-source-diff",
        action="store_true",
        help=(
            "Include verifier source text in reports. Off by default because "
            "source files can contain secrets or proprietary logic."
        ),
    )
    diff.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Total timeout per verifier process in seconds.",
    )
    diff.add_argument("--bootstrap-replicates", type=int, default=2000)
    diff.add_argument("--bootstrap-seed", type=int, default=20260805)
    diff.add_argument(
        "--python",
        dest="python_executable",
        help="Alternative Python executable for verifier subprocesses.",
    )

    validate = sub.add_parser(
        "validate",
        help="Validate a JSONL corpus and verifier API without comparison.",
    )
    validate.add_argument("--data", type=Path, required=True)
    validate.add_argument("--verifier", type=Path, required=True)
    validate.add_argument("--timeout", type=float, default=60.0)

    demo = sub.add_parser(
        "demo",
        help="Copy and run the packaged exact-match demonstration.",
    )
    demo.add_argument(
        "--out", type=Path, default=Path("evalcanary-demo")
    )

    return parser


def _run_diff(args: argparse.Namespace, argv: list[str]) -> int:
    cases = load_cases(args.data)
    before = run_verifier(
        args.before,
        cases,
        timeout_seconds=args.timeout,
        python_executable=args.python_executable,
    )
    after = run_verifier(
        args.after,
        cases,
        timeout_seconds=args.timeout,
        python_executable=args.python_executable,
    )
    summary = compare_verdicts(
        cases,
        before,
        after,
        data_path=args.data.resolve(),
        before_path=args.before.resolve(),
        after_path=args.after.resolve(),
        slices=args.slice,
        include_content=args.include_content,
        include_source_diff=args.include_source_diff,
        bootstrap_replicates=args.bootstrap_replicates,
        bootstrap_seed=args.bootstrap_seed,
        command=["evalcanary", *argv],
    )
    summary = evaluate_policy(summary, load_policy(args.policy))
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(summary, args.out / "report.json")
    write_markdown(summary, args.out / "report.md")
    write_html(summary, args.out / "report.html")

    changed = summary.pass_to_fail + summary.fail_to_pass
    print("EvalCanary evaluator migration report")
    print(f"  cases: {summary.total_cases}")
    print(f"  comparable: {summary.comparable_cases}")
    print(f"  errors: {summary.error_cases}")
    print(f"  pass -> fail: {summary.pass_to_fail}")
    print(f"  fail -> pass: {summary.fail_to_pass}")
    print(f"  changed: {changed}")
    before_text = (
        summary.before_rate if summary.before_rate is not None else "n/a"
    )
    after_text = (
        summary.after_rate if summary.after_rate is not None else "n/a"
    )
    print(f"  before rate: {before_text}")
    print(f"  after rate: {after_text}")
    print(f"  report: {args.out.resolve()}")
    if summary.policy.get("configured"):
        passed = bool(summary.policy.get("passed"))
        print(f"  policy: {'PASS' if passed else 'FAIL'}")
        return EXIT_OK if passed else EXIT_POLICY_FAIL
    print("  policy: NOT CONFIGURED")
    return EXIT_OK


def _run_validate(args: argparse.Namespace) -> int:
    cases = load_cases(args.data)
    verdicts = run_verifier(
        args.verifier, cases, timeout_seconds=args.timeout
    )
    errors = [item for item in verdicts if item.error]
    result = {
        "cases": len(cases),
        "verdicts": len(verdicts),
        "errors": len(errors),
        "valid": not errors,
    }
    print(json.dumps(result, sort_keys=True))
    return EXIT_OK if not errors else EXIT_ERROR


def _example_root() -> Path:
    package_candidate = (
        Path(__file__).resolve().parent / "examples" / "exact_match"
    )
    if package_candidate.is_dir():
        return package_candidate
    project_candidate = (
        Path(__file__).resolve().parents[2] / "examples" / "exact_match"
    )
    if project_candidate.is_dir():
        return project_candidate
    raise InputValidationError("Packaged demonstration files were not found.")


def _run_demo(args: argparse.Namespace) -> int:
    source = _example_root()
    if args.out.exists():
        shutil.rmtree(args.out)
    shutil.copytree(source, args.out)
    report_dir = args.out / "report"
    demo_args = argparse.Namespace(
        data=args.out / "cases.jsonl",
        before=args.out / "verifier_before.py",
        after=args.out / "verifier_after.py",
        out=report_dir,
        policy=args.out / "evalcanary.toml",
        slice=["metadata.domain"],
        include_content=False,
        include_source_diff=True,
        timeout=30.0,
        bootstrap_replicates=1000,
        bootstrap_seed=20260805,
        python_executable=None,
    )
    return _run_diff(demo_args, ["demo"])


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(raw_args)
    try:
        if args.command == "diff":
            return _run_diff(args, raw_args)
        if args.command == "validate":
            return _run_validate(args)
        if args.command == "demo":
            return _run_demo(args)
        parser.error("Unknown command.")
    except EvalCanaryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("ERROR: interrupted", file=sys.stderr)
        return 130
    return EXIT_ERROR
