#!/usr/bin/env python3
"""Verify that a behavior mutation produces a detectable migration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="evalcanary-mutation-") as temp:
        root = Path(temp)
        data = root / "cases.jsonl"
        before = root / "before.py"
        after = root / "after.py"
        report = root / "report"
        data.write_text(
            '{"id":"a","expected":"ok","output":"ok"}\n'
            '{"id":"b","expected":"ok","output":"OK"}\n',
            encoding="utf-8",
        )
        before.write_text(
            'def verify(case):\n    return case["output"] == case["expected"]\n',
            encoding="utf-8",
        )
        after.write_text(
            'def verify(case):\n    return case["output"].casefold() == case["expected"].casefold()\n',
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "evalcanary",
                "diff",
                "--data",
                str(data),
                "--before",
                str(before),
                "--after",
                str(after),
                "--out",
                str(report),
                "--bootstrap-replicates",
                "200",
            ],
            cwd=ROOT,
            env=env,
            check=False,
        )
        if completed.returncode != 0:
            return completed.returncode
        payload = json.loads((report / "report.json").read_text(encoding="utf-8"))
        if payload["transition_counts"]["fail_to_pass"] != 1:
            print("Mutation gate failed: expected one fail-to-pass transition.")
            return 1
    print("Mutation gate passed: evaluator behavior change detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
