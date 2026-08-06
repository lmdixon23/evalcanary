#!/usr/bin/env python3
"""Fail when executable PowerShell scripts contain non-ASCII bytes."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    failures: list[str] = []
    for path in sorted(ROOT.rglob("*.ps1")):
        data = path.read_bytes()
        try:
            data.decode("ascii")
        except UnicodeDecodeError:
            failures.append(str(path.relative_to(ROOT)))
    if failures:
        print("Non-ASCII PowerShell scripts:")
        for item in failures:
            print("  ", item)
        return 1
    print("PowerShell ASCII gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
