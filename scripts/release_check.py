#!/usr/bin/env python3
"""Deterministic pre-release verification using only the standard library."""

from __future__ import annotations

import compileall
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_VERSION_PATTERN = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
_USES_PATTERN = re.compile(r"^\s*(?:-\s+)?uses:\s+(\S+)", re.MULTILINE)
_FULL_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project_version() -> str:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = document.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise RuntimeError("pyproject.toml does not contain a project version")
    return version


def _source_version() -> str:
    text = (ROOT / "src" / "evalcanary" / "__init__.py").read_text(
        encoding="utf-8"
    )
    match = _VERSION_PATTERN.search(text)
    if match is None:
        raise RuntimeError("Unable to read evalcanary.__version__ from source")
    return match.group(1)


def verify_release_metadata() -> str:
    version = _project_version()
    if _source_version() != version:
        raise RuntimeError("pyproject.toml and source versions do not match")

    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    if f"version: {version}" not in citation:
        raise RuntimeError("CITATION.cff version does not match the project version")

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## {version} - " not in changelog:
        raise RuntimeError("CHANGELOG.md does not contain the release version")

    metadata_paths = [
        path
        for path in (ROOT / "action.yml", ROOT / "action.yaml")
        if path.is_file()
    ]
    if len(metadata_paths) != 1:
        raise RuntimeError("The repository must contain exactly one root action metadata file")
    action_text = metadata_paths[0].read_text(encoding="utf-8")
    required_action_fragments = (
        "name: EvalCanary Diff",
        "using: composite",
        "report_json:",
        "run_id:",
        "changed_cases:",
        "policy_passed:",
        "scripts",
        "run_action.py",
    )
    missing = [item for item in required_action_fragments if item not in action_text]
    if missing:
        raise RuntimeError(
            "action.yml is missing required release metadata: " + ", ".join(missing)
        )
    if "shell: bash" in action_text:
        raise RuntimeError("The root composite action must not require Bash")
    return version


def verify_workflow_action_pins() -> int:
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    if not workflows:
        raise RuntimeError("No GitHub Actions workflows were found")

    references = 0
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        if "pull_request_target:" in text:
            raise RuntimeError(
                f"High-risk pull_request_target trigger is not permitted: {workflow.name}"
            )
        for raw_reference in _USES_PATTERN.findall(text):
            reference = raw_reference.split("#", 1)[0].strip()
            if reference.startswith("./"):
                continue
            if "@" not in reference:
                raise RuntimeError(
                    f"Unversioned action reference in {workflow.name}: {reference}"
                )
            action_name, revision = reference.rsplit("@", 1)
            if "/" not in action_name or not _FULL_SHA_PATTERN.fullmatch(revision):
                raise RuntimeError(
                    "External workflow actions must be pinned to a full 40-character "
                    f"commit SHA: {workflow.name}: {reference}"
                )
            references += 1
    if references == 0:
        raise RuntimeError("No pinned external workflow actions were inspected")
    return references


def main() -> int:
    pass_items: list[str] = []
    fail_items: list[str] = []

    try:
        if not compileall.compile_dir(ROOT / "src", quiet=1):
            raise RuntimeError("Python source compile gate failed")
        if not compileall.compile_dir(ROOT / "tests", quiet=1):
            raise RuntimeError("Python test compile gate failed")
        if not compileall.compile_dir(ROOT / "scripts", quiet=1):
            raise RuntimeError("Python script compile gate failed")
        pass_items.append("Python source, test, and script compile gates passed")

        version = verify_release_metadata()
        pass_items.append(f"Release metadata alignment passed: {version}")

        pinned_references = verify_workflow_action_pins()
        pass_items.append(
            "Workflow action SHA-pin and trigger gate passed: "
            f"{pinned_references} references"
        )

        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["SOURCE_DATE_EPOCH"] = "1785960000"
        run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-v",
            ],
            env=env,
        )
        pass_items.append("Unit and integration suite passed")

        with (
            tempfile.TemporaryDirectory(prefix="evalcanary-release-a-") as temp_a,
            tempfile.TemporaryDirectory(prefix="evalcanary-release-b-") as temp_b,
        ):
            target_a = Path(temp_a) / "demo"
            target_b = Path(temp_b) / "demo"
            for target in (target_a, target_b):
                run(
                    [
                        sys.executable,
                        "-m",
                        "evalcanary",
                        "demo",
                        "--out",
                        str(target),
                    ],
                    env=env,
                )

            report_a = target_a / "report" / "report.json"
            report_b = target_b / "report" / "report.json"
            payload = json.loads(report_a.read_text(encoding="utf-8"))
            expected = {
                "total_cases": 12,
                "error_cases": 0,
                "fail_to_pass": 5,
                "pass_to_fail": 0,
            }
            actual = {
                "total_cases": payload["total_cases"],
                "error_cases": payload["error_cases"],
                "fail_to_pass": payload["transition_counts"]["fail_to_pass"],
                "pass_to_fail": payload["transition_counts"]["pass_to_fail"],
            }
            if actual != expected:
                raise RuntimeError(
                    f"Demo contract mismatch. Expected {expected}, received {actual}."
                )
            if not payload["policy"]["passed"]:
                raise RuntimeError("Demo policy did not pass")
            serialized = report_a.read_text(encoding="utf-8")
            if temp_a in serialized or temp_b in serialized:
                raise RuntimeError("Canonical report leaked a temporary parent path")
            first_hash = sha256(report_a)
            second_hash = sha256(report_b)
            if first_hash != second_hash:
                raise RuntimeError(
                    "Canonical JSON report was not reproducible across fresh directories "
                    "under SOURCE_DATE_EPOCH"
                )
            pass_items.append(
                "Demo contract and fresh-directory report reproducibility passed: "
                f"{first_hash}"
            )

        run([sys.executable, "scripts/mutation_gate.py"], env=env)
        pass_items.append("Mutation gate passed")
    except Exception as exc:  # noqa: BLE001
        fail_items.append(str(exc))

    print()
    print("EvalCanary release-check summary")
    print(f"PASS: {len(pass_items)}")
    for item in pass_items:
        print(f"  PASS {item}")
    print(f"FAIL: {len(fail_items)}")
    for item in fail_items:
        print(f"  FAIL {item}")
    return 0 if not fail_items else 1


if __name__ == "__main__":
    raise SystemExit(main())
