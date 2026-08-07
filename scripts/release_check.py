#!/usr/bin/env python3
"""Deterministic pre-release verification using only the standard library."""

from __future__ import annotations

import compileall
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    pass_items: list[str] = []
    fail_items: list[str] = []

    try:
        if not compileall.compile_dir(ROOT / "src", quiet=1):
            raise RuntimeError("Python compile gate failed")
        pass_items.append("Python compile gate passed")

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
