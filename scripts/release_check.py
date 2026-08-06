#!/usr/bin/env python3
"""Deterministic pre-release verification using only the standard library."""

from __future__ import annotations

import compileall
import hashlib
import json
import os
import shutil
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

        with tempfile.TemporaryDirectory(prefix="evalcanary-release-") as temp:
            target = Path(temp) / "demo"
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
            report = target / "report" / "report.json"
            payload = json.loads(report.read_text(encoding="utf-8"))
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
            first_hash = sha256(report)
            shutil.rmtree(target)
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
            second_hash = sha256(target / "report" / "report.json")
            if first_hash != second_hash:
                raise RuntimeError(
                    "Canonical JSON report was not reproducible under SOURCE_DATE_EPOCH"
                )
            pass_items.append(
                f"Demo contract and deterministic report hash passed: {first_hash}"
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
