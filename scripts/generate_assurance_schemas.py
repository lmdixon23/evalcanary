#!/usr/bin/env python3
"""Generate or verify deterministic evaluator-assurance JSON Schemas."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evalcanary.assurance.structural import (  # noqa: E402
    verify_checked_in_schemas,
    write_checked_in_schemas,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="Rewrite checked-in schema bytes; default is a drift check.",
    )
    args = parser.parse_args(argv)
    if args.write:
        for path in write_checked_in_schemas():
            print(path.relative_to(ROOT).as_posix())
    else:
        verify_checked_in_schemas()
        print("Assurance schema bytes match the structural registry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
