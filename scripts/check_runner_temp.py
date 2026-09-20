"""Diagnose temporary paths and select a verified GitHub runner temp directory."""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any


def inspect_root(value: str) -> dict[str, Any]:
    """Inspect the supplied spelling without following ancestor links."""
    absolute = Path(os.path.abspath(value))
    ancestors = []
    for path in (*reversed(absolute.parents), absolute):
        entry: dict[str, Any] = {"path": str(path)}
        try:
            info = path.lstat()
        except OSError as exc:
            entry["error"] = type(exc).__name__
        else:
            entry.update(
                directory=stat.S_ISDIR(info.st_mode),
                symlink=stat.S_ISLNK(info.st_mode),
                reparse=bool(getattr(info, "st_file_attributes", 0) & 0x400),
            )
        ancestors.append(entry)
    return {
        "supplied": value,
        "abspath": str(absolute),
        "realpath": os.path.realpath(value),
        "ancestors": ancestors,
    }


def validate_root(value: str) -> Path:
    if not value or any(character in value for character in "\r\n\0"):
        raise ValueError("Runner temporary root must be a non-empty single path.")
    if not Path(value).is_absolute():
        raise ValueError("Runner temporary root must be absolute.")
    inspection = inspect_root(value)
    for entry in inspection["ancestors"]:
        if entry.get("symlink") or entry.get("reparse"):
            raise ValueError(
                "Runner temporary root traverses a symlink or reparse point."
            )
        if entry.get("error") or not entry.get("directory"):
            raise ValueError(
                "Runner temporary root must have existing directory ancestors."
            )
    return Path(inspection["abspath"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=os.environ.get("CHECKED_RUNNER_TEMP", os.environ.get("RUNNER_TEMP")),
    )
    parser.add_argument("--github-env", type=Path, default=os.environ.get("GITHUB_ENV"))
    args = parser.parse_args(argv)
    if args.root is None or args.github_env is None:
        parser.error("Supply a runner root and GitHub environment file.")

    original = tempfile.gettempdir()
    diagnostic = {
        "before": {
            "tempfile_gettempdir": original,
            "TMPDIR": os.environ.get("TMPDIR"),
            "TEMP": os.environ.get("TEMP"),
            "TMP": os.environ.get("TMP"),
            "RUNNER_TEMP": os.environ.get("RUNNER_TEMP"),
            "inspection": inspect_root(original),
        },
        "candidate": inspect_root(args.root),
    }
    print(json.dumps(diagnostic, indent=2), flush=True)
    try:
        root = validate_root(args.root)
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 1
    with args.github_env.open("a", encoding="utf-8", newline="\n") as handle:
        for name in ("TMPDIR", "TEMP", "TMP"):
            handle.write(f"{name}={root}\n")
    print(
        "PASS: verified non-link runner temporary root selected for subsequent steps."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
