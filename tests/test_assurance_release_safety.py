"""Release hardening for bounded reads and rejected deep JSON."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from evalcanary.assurance.preflight import preflight_paths
from evalcanary.cli import main


class BoundedReader(io.BytesIO):
    def read(self, size: int | None = -1) -> bytes:
        if size is None or size < 0 or size > 65:
            raise AssertionError(f"Unbounded source read: {size}")
        return super().read(size)


class ReleaseInputSafetyTests(unittest.TestCase):
    def test_preflight_input_read_stops_at_configured_limit(self) -> None:
        self._oversized_preflight("input")

    def test_preflight_contract_read_stops_at_configured_limit(self) -> None:
        self._oversized_preflight("contract")

    def _oversized_preflight(self, kind: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / kind
            target.write_bytes(b" " * 1024)
            limits = root / "limits.json"
            limits.write_text('{"limits":{"total_input_bytes":64}}', encoding="utf-8")
            original = Path.open

            def guarded(path: Path, *args: object, **kwargs: object) -> object:
                if path == target:
                    return BoundedReader(b" " * 1024)
                return original(path, *args, **kwargs)

            with patch.object(Path, "open", guarded):
                result = preflight_paths(
                    target if kind == "input" else root / "absent.jsonl",
                    contract_path=target if kind == "contract" else None,
                    limits_path=limits,
                )
            self.assertFalse(result.valid)
            self.assertTrue(any(
                item.code == "RESOURCE_LIMIT_EXCEEDED" and item.source_kind == kind
                for item in result.diagnostics
            ))

    def test_deep_json_is_handled_error_for_migrate_and_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "deep.jsonl"
            source.write_text("[" * 10000 + "0" + "]" * 10000 + "\n", encoding="utf-8")
            for flags in ([], ["--preflight"]):
                with self.subTest(flags=flags):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = main(["migrate", *flags, "--input", str(source),
                                     "--out", str(root / "report")])
                    self.assertEqual(code, 3)
                    self.assertNotIn("Traceback", stdout.getvalue() + stderr.getvalue())
                    self.assertFalse((root / "report").exists())


if __name__ == "__main__":
    unittest.main()
