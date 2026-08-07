#!/usr/bin/env python3
"""Cross-platform entry point for the EvalCanary composite GitHub Action."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise ValueError(f"Required action input is empty: {name}")
    return value


def _optional(environment: Mapping[str, str], name: str) -> str:
    return environment.get(name, "").strip()


def _enabled(environment: Mapping[str, str], name: str) -> bool:
    return _optional(environment, name).lower() in _TRUE_VALUES


def _slices(raw: str) -> list[str]:
    return [item.strip() for item in raw.replace(",", "\n").splitlines() if item.strip()]


def build_command(environment: Mapping[str, str] | None = None) -> list[str]:
    """Build the CLI invocation from composite-action environment inputs."""

    env = os.environ if environment is None else environment
    command = [
        sys.executable,
        "-m",
        "evalcanary",
        "diff",
        "--data",
        _required(env, "EVALCANARY_INPUT_DATA"),
        "--before",
        _required(env, "EVALCANARY_INPUT_BEFORE"),
        "--after",
        _required(env, "EVALCANARY_INPUT_AFTER"),
        "--out",
        _required(env, "EVALCANARY_INPUT_OUTPUT"),
    ]

    optional_values = (
        ("EVALCANARY_INPUT_POLICY", "--policy"),
        ("EVALCANARY_INPUT_TIMEOUT", "--timeout"),
        ("EVALCANARY_INPUT_BOOTSTRAP_REPLICATES", "--bootstrap-replicates"),
        ("EVALCANARY_INPUT_BOOTSTRAP_SEED", "--bootstrap-seed"),
        ("EVALCANARY_INPUT_PYTHON", "--python"),
    )
    for variable, flag in optional_values:
        value = _optional(env, variable)
        if value:
            command.extend((flag, value))

    for slice_name in _slices(_optional(env, "EVALCANARY_INPUT_SLICE")):
        command.extend(("--slice", slice_name))

    if _enabled(env, "EVALCANARY_INPUT_INCLUDE_CONTENT"):
        command.append("--include-content")
    if _enabled(env, "EVALCANARY_INPUT_INCLUDE_SOURCE_DIFF"):
        command.append("--include-source-diff")
    return command


def _append_github_output(path: Path, name: str, value: str) -> None:
    delimiter = f"evalcanary_{uuid.uuid4().hex}"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def write_outputs(
    report_directory: Path,
    output_file: Path,
) -> None:
    """Write action outputs after a report exists, including policy failures."""

    report_directory = report_directory.resolve()
    report_json = report_directory / "report.json"
    report_markdown = report_directory / "report.md"
    report_html = report_directory / "report.html"
    if not report_json.is_file():
        return

    payload = json.loads(report_json.read_text(encoding="utf-8"))
    transitions = payload["transition_counts"]
    changed_cases = int(transitions["pass_to_fail"]) + int(
        transitions["fail_to_pass"]
    )
    policy = payload.get("policy", {})
    if policy.get("configured"):
        policy_passed = "true" if policy.get("passed") else "false"
    else:
        policy_passed = "not-configured"

    values = {
        "report_directory": str(report_directory),
        "report_json": str(report_json),
        "report_markdown": str(report_markdown),
        "report_html": str(report_html),
        "run_id": str(payload["run_id"]),
        "changed_cases": str(changed_cases),
        "policy_passed": policy_passed,
    }
    for name, value in values.items():
        _append_github_output(output_file, name, value)


def main() -> int:
    try:
        command = build_command()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    completed = subprocess.run(command, check=False)
    output_file = _optional(os.environ, "GITHUB_OUTPUT")
    if output_file:
        report_directory = Path(
            _required(os.environ, "EVALCANARY_INPUT_OUTPUT")
        )
        try:
            write_outputs(report_directory, Path(output_file))
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(f"ERROR: unable to publish action outputs: {exc}", file=sys.stderr)
            return 3
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
