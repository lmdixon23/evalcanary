from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.check_runner_temp import inspect_root, main, validate_root


class RunnerTempTests(unittest.TestCase):
    def test_existing_non_link_root_is_accepted_without_resolving_spelling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch(
                "scripts.check_runner_temp.os.path.realpath",
                return_value="diagnostic-only",
            ):
                actual = validate_root(str(root))
            self.assertTrue(actual.is_absolute())
            self.assertTrue(os.path.samefile(actual, root))

    def test_invalid_missing_or_relative_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in (
                "",
                "relative",
                "bad\nvalue",
                str(Path(directory) / "missing"),
            ):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    validate_root(value)

    def test_real_symlink_root_and_ancestor_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            (target / "child").mkdir(parents=True)
            alias = root / "alias"
            try:
                alias.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Directory symlinks unavailable: {type(exc).__name__}")
            for destination in (alias, alias / "child"):
                with (
                    self.subTest(destination=destination),
                    self.assertRaises(ValueError),
                ):
                    validate_root(str(destination))

    def test_reparse_ancestor_diagnostic_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            inspection = {
                "ancestors": [{"directory": True, "symlink": False, "reparse": True}]
            }
            with (
                patch(
                    "scripts.check_runner_temp.inspect_root", return_value=inspection
                ),
                self.assertRaisesRegex(ValueError, "reparse"),
            ):
                validate_root(directory)

    def test_diagnostic_records_actual_ancestor_topology(self):
        with tempfile.TemporaryDirectory() as directory:
            inspection = inspect_root(directory)
            self.assertEqual(inspection["abspath"], os.path.abspath(directory))
            self.assertEqual(inspection["realpath"], os.path.realpath(directory))
            self.assertTrue(inspection["ancestors"])
            self.assertTrue(all(item["directory"] for item in inspection["ancestors"]))
            self.assertFalse(
                any(
                    item["symlink"] or item["reparse"]
                    for item in inspection["ancestors"]
                )
            )

    def test_cli_records_original_model_before_exporting_verified_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export = root / "github-env"
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "--github-env", str(export)])
            self.assertEqual(code, 0)
            diagnostic, _ = json.JSONDecoder().raw_decode(output.getvalue())
            for field in ("tempfile_gettempdir", "TMPDIR", "RUNNER_TEMP", "inspection"):
                self.assertIn(field, diagnostic["before"])
            values = dict(
                line.split("=", 1) for line in export.read_text().splitlines()
            )
            self.assertEqual(
                values, {name: str(root) for name in ("TMPDIR", "TEMP", "TMP")}
            )
            child = subprocess.run(
                [sys.executable, "-c", "import tempfile; print(tempfile.gettempdir())"],
                env={**os.environ, **values},
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue(os.path.samefile(child.stdout.strip(), root))

    def test_invalid_root_cannot_change_github_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            export = Path(directory) / "github-env"
            export.write_bytes(b"EXISTING=value\n")
            with redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "--root",
                        str(Path(directory) / "absent"),
                        "--github-env",
                        str(export),
                    ]
                )
            self.assertEqual(code, 1)
            self.assertEqual(export.read_bytes(), b"EXISTING=value\n")


if __name__ == "__main__":
    unittest.main()
