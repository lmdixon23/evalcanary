#!/usr/bin/env python3
"""Offline local bootstrap for a project virtual environment.

Run this script with the target virtual environment's Python executable. It
writes a .pth file that points to the repository's src directory and creates a
small platform-native evalcanary launcher. No package index is required.
"""

from __future__ import annotations

import os
import site
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def site_packages() -> Path:
    candidates = [Path(item) for item in site.getsitepackages()]
    if not candidates:
        raise RuntimeError("Python did not report a site-packages directory.")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    candidates[0].mkdir(parents=True, exist_ok=True)
    return candidates[0]


def write_launcher() -> Path:
    executable = Path(sys.executable).absolute()
    if os.name == "nt":
        launcher = executable.parent / "evalcanary.cmd"
        launcher.write_text(
            '@"%~dp0python.exe" -m evalcanary %*\r\n',
            encoding="ascii",
        )
        return launcher
    launcher = executable.parent / "evalcanary"
    launcher.write_text(
        f"#!{executable}\nfrom evalcanary.cli import main\nraise SystemExit(main())\n",
        encoding="utf-8",
    )
    launcher.chmod(
        launcher.stat().st_mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
    )
    return launcher


def main() -> int:
    target = site_packages() / "evalcanary-local.pth"
    target.write_text(str(SRC.resolve()) + os.linesep, encoding="utf-8")
    launcher = write_launcher()
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import evalcanary; print(evalcanary.__version__)",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        print(completed.stdout, end="")
        print(completed.stderr, end="", file=sys.stderr)
        return completed.returncode
    print(f"EvalCanary {completed.stdout.strip()} local bootstrap complete.")
    print(f"  source: {SRC.resolve()}")
    print(f"  pth: {target}")
    print(f"  launcher: {launcher}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
