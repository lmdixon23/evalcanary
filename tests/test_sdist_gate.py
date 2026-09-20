"""Release archives must be self-testable without writing outside extraction."""

from __future__ import annotations

import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_sdist.py"
SPEC = importlib.util.spec_from_file_location("check_sdist", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class SdistGateTests(unittest.TestCase):
    def archive(self, root: Path, extra: tarfile.TarInfo | None = None,
                *, include_tests: bool = True) -> Path:
        archive = root / "candidate.tar.gz"
        entries = {"candidate/pyproject.toml": b"[project]"}
        if include_tests:
            entries["candidate/tests/test_example.py"] = b"# synthetic test"
        with tarfile.open(archive, "w:gz") as bundle:
            for name, data in entries.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                bundle.addfile(member, io.BytesIO(data))
            if extra is not None:
                bundle.addfile(extra, io.BytesIO(b""))
        return archive

    def test_regular_self_testable_source_extracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = CHECK.extract_sdist(self.archive(root), root / "extracted")
            self.assertTrue((source / "tests/test_example.py").is_file())

    def test_traversal_and_windows_paths_rejected_before_writes(self) -> None:
        for name in ("../escape", "/absolute", "candidate/../../escape",
                     "candidate\\escape", "C:/escape", "candidate/file:stream"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = self.archive(root, tarfile.TarInfo(name))
                with self.assertRaises(ValueError):
                    CHECK.extract_sdist(archive, root / "extracted")
                self.assertFalse((root / "extracted").exists())

    def test_links_and_devices_rejected(self) -> None:
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                member = tarfile.TarInfo("candidate/unsafe")
                member.type = kind
                member.linkname = "../escape"
                with self.assertRaises(ValueError):
                    CHECK.extract_sdist(self.archive(root, member), root / "extracted")
                self.assertFalse((root / "extracted").exists())

    def test_duplicate_and_multiple_root_members_rejected(self) -> None:
        for name in ("candidate/pyproject.toml", "another/file"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with self.assertRaises(ValueError):
                    CHECK.extract_sdist(
                        self.archive(root, tarfile.TarInfo(name)), root / "extracted"
                    )

    def test_archive_without_tests_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "no shipped tests"):
                CHECK.extract_sdist(
                    self.archive(root, include_tests=False), root / "extracted"
                )


if __name__ == "__main__":
    unittest.main()
