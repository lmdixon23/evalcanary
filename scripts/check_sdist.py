#!/usr/bin/env python3
"""Install a safely extracted sdist and run every shipped unittest."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
from pathlib import Path, PurePosixPath


def extract_sdist(archive: Path, destination: Path) -> Path:
    """Accept a single-root source archive with regular files/directories only."""
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        roots: set[str] = set()
        names: set[str] = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (
                not path.parts
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in member.name
                or ":" in member.name
                or not (member.isfile() or member.isdir())
                or member.name in names
            ):
                raise ValueError(f"Unsafe sdist member: {member.name!r}")
            roots.add(path.parts[0])
            names.add(member.name)
        if len(roots) != 1:
            raise ValueError("Expected exactly one sdist root")
        destination.mkdir(parents=True, exist_ok=False)
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise ValueError(f"Unreadable sdist member: {member.name!r}")
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
    source_root = destination / next(iter(roots))
    if not (source_root / "pyproject.toml").is_file():
        raise ValueError("Extracted sdist is missing pyproject.toml")
    if not list((source_root / "tests").glob("test_*.py")):
        raise ValueError("Extracted sdist contains no shipped tests")
    return source_root


def verify(archive: Path, work: Path) -> None:
    source = extract_sdist(archive, work / "source")
    environment = work / "environment"
    venv.create(environment, with_pip=True)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONNOUSERSITE"] = "1"

    def run(*args: str, cwd: Path = source) -> None:
        subprocess.run([str(python), *args], cwd=cwd, env=env, check=True)

    run("-m", "pip", "install", "--no-deps", str(source), cwd=work)
    run("-m", "pip", "check", cwd=work)
    run(
        "-c",
        "import evalcanary, pathlib, sys; "
        "p=pathlib.Path(evalcanary.__file__).resolve(); "
        "assert p.is_relative_to(pathlib.Path(sys.prefix).resolve()), p; "
        "print('Installed package:', p)",
        cwd=work,
    )
    run("-m", "unittest", "discover", "-s", "tests", "-v")
    run("-m", "evalcanary", "--version", cwd=work)
    print("Extracted-sdist installed-package full-suite gate PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdist", type=Path)
    parser.add_argument("--work", type=Path, help="New, nonexistent verification directory")
    args = parser.parse_args()
    archive = args.sdist.resolve(strict=True)
    if args.work is None:
        with tempfile.TemporaryDirectory(prefix="replaydocket-sdist-") as temporary:
            verify(archive, Path(temporary))
    else:
        work = args.work.resolve()
        work.mkdir(parents=True, exist_ok=False)
        verify(archive, work)
    return 0


if __name__ == "__main__":
    sys.exit(main())
