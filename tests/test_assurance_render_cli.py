from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import tempfile
import unittest
import urllib.request
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from tests.assurance_helpers import (
    clone_records,
    component,
    contract,
    rule,
    write_json,
    write_records,
)

from evalcanary.assurance.engine import build_report
from evalcanary.assurance.numeric import canonical_json_text
from evalcanary.assurance.renderers import (
    html_text,
    json_bytes,
    markdown_text,
    write_report_bundle,
)
from evalcanary.assurance.schema import Limits, load_artifact, load_contract
from evalcanary.cli import main
from evalcanary.errors import InputValidationError


class AssuranceRendererTests(unittest.TestCase):
    def _report(self, root: Path, *, sensitive: bool = False) -> dict[str, object]:
        items = clone_records(with_anchors=True)
        if sensitive:
            trial = next(item for item in items if item.get("record_type") == "trial")
            trial.update(
                {
                    "status": "error",
                    "label": None,
                    "reason": "Authorization: Bearer PRIVATE_REASON_123",
                    "details": {
                        "provider_request_id": "PRIVATE_REQUEST_456",
                        "path": "C:\\Users\\PrivatePerson\\payload.txt",
                    },
                    "error": {
                        "error_class": "ParserError",
                        "message": "sk-PRIVATE_ERROR_789",
                    },
                }
            )
        artifact = load_artifact(write_records(root / "input.jsonl", items))
        return build_report(artifact)

    def _existing_bundle(
        self, root: Path
    ) -> tuple[
        Path,
        Path,
        tuple[Path, ...],
        dict[str, bytes],
        dict[str, object],
    ]:
        report = self._report(root)
        source = root / "input.jsonl"
        output = root / "output"
        write_report_bundle(
            report, output, limits=Limits(), source_paths=(source,)
        )
        targets = tuple(
            output / name
            for name in (
                "report.json",
                "report.md",
                "report.html",
                "review-queue.json",
                "review-queue.md",
            )
        )
        previous = {target.name: target.read_bytes() for target in targets}
        changed = deepcopy(report)
        changed["warnings"] = ["new generation marker"]
        return source, output, targets, previous, changed

    def test_cross_format_fact_parity_and_accessible_scriptless_html(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._report(Path(temp))
        canonical = canonical_json_text(report)
        markdown = markdown_text(report)
        rendered_html = html_text(report)
        self.assertEqual(json_bytes(report), canonical.encode("utf-8") + b"\n")
        canonical_hash = hashlib.sha256(json_bytes(report)).hexdigest()
        self.assertIn(canonical_hash, markdown)
        self.assertIn(canonical_hash, rendered_html)
        self.assertNotIn(canonical, markdown)
        self.assertNotIn(canonical, rendered_html)
        self.assertIn("report.json", markdown)
        self.assertIn("report.json", rendered_html)
        self.assertIn("displayed", markdown)
        self.assertIn("omitted", markdown)
        self.assertNotIn("<script", rendered_html.lower())
        self.assertNotIn(" onclick=", rendered_html.lower())
        self.assertIn("Content-Security-Policy", rendered_html)
        self.assertIn("<caption>", rendered_html)
        self.assertIn('scope="col"', rendered_html)
        self.assertIn(":focus-visible", rendered_html)
        headings = (
            "A. Evidence, isolation, contract, and report status",
            "B. Decision summary",
            "C. Contract findings",
            "D. Critical findings",
            "E. Invariance summary",
            "F. Human-anchor summary",
            "G. Provenance and context changes",
            "H. Bounded detail",
            "I. Limitations",
        )
        for heading in headings:
            self.assertIn(f"## {heading}", markdown)
            self.assertIn(f">{heading}</h2>", rendered_html)
        self.assertEqual(
            [markdown.index(f"## {heading}") for heading in headings],
            sorted(markdown.index(f"## {heading}") for heading in headings),
        )
        self.assertEqual(
            [rendered_html.index(f">{heading}</h2>") for heading in headings],
            sorted(rendered_html.index(f">{heading}</h2>") for heading in headings),
        )

    def test_contract_projection_is_decision_complete_and_escaped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = load_artifact(
                write_records(root / "input.jsonl", clone_records())
            )
            contract_path = write_json(
                root / "contract.json",
                contract(rule("determinate_coverage", parameters={"role": "candidate"})),
            )
            loaded_contract = load_contract(contract_path, artifact)
            assert loaded_contract is not None
            loaded_contract.document["rules"][0]["rationale"] = "Visible <reason> | `safe`"
            report = build_report(artifact, loaded_contract)
        markdown = markdown_text(report)
        rendered_html = html_text(report)
        for value in (
            "rule-determinate_coverage",
            "hard",
            "all_cases",
            "determinate_coverage",
            "eq",
            "hard_fail",
        ):
            self.assertIn(value, markdown)
            self.assertIn(value, rendered_html)
        self.assertIn("Visible &lt;reason&gt; \\| \\`safe\\`", markdown)
        self.assertIn("Visible &lt;reason&gt; | `safe`", rendered_html)

    def test_metadata_only_output_omits_content_secrets_paths_and_annotators(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self._report(root, sensitive=True)
            rendered = "\n".join(
                (canonical_json_text(report), markdown_text(report), html_text(report))
            )
            for canary in (
                "PRIVATE_REASON_123",
                "PRIVATE_REQUEST_456",
                "PrivatePerson",
                "payload.txt",
                "PRIVATE_ERROR_789",
                "person-0",
                str(root),
            ):
                self.assertNotIn(canary, rendered)
            self.assertIn('"mode":"metadata_only"', rendered)
            trial = report["cases"][0]["trials"]["baseline"][0]  # type: ignore[index]
            self.assertEqual(trial["error_class"], "ParserError")
            self.assertTrue(trial["reason"]["omitted"])
            self.assertTrue(trial["details"]["omitted"])
            self.assertTrue(trial["error_message"]["omitted"])

    def test_dangerous_links_never_become_clickable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            items = clone_records()
            items[0]["provenance"]["source_url"] = component(
                "https://127.0.0.1/private?token=secret"
            )
            report = build_report(load_artifact(write_records(root / "input.jsonl", items)))
        self.assertNotIn("127.0.0.1", markdown_text(report))
        self.assertNotIn("127.0.0.1", html_text(report))
        source = report["provenance"]["artifact"]["source_url"]
        self.assertIsNone(source["identity"])
        self.assertTrue(source["identity_omitted"])

    def test_output_size_preflight_leaves_no_report_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self._report(root)
            for limit_name in (
                "json_report_bytes",
                "markdown_report_bytes",
                "html_report_bytes",
                "combined_report_bytes",
            ):
                output = root / limit_name
                values = dict(Limits().values)
                values[limit_name] = 1
                with self.subTest(limit=limit_name), self.assertRaisesRegex(
                    InputValidationError, limit_name
                ):
                    write_report_bundle(report, output, limits=Limits(values=values))
                self.assertFalse(output.exists())

    def test_source_conflict_file_destination_and_symlink_targets_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self._report(root)
            with self.assertRaisesRegex(InputValidationError, "source input"):
                write_report_bundle(
                    report,
                    root,
                    limits=Limits(),
                    source_paths=(root / "report.json",),
                )
            destination_file = root / "not-a-directory"
            destination_file.write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(InputValidationError, "not a directory"):
                write_report_bundle(report, destination_file, limits=Limits())
            actual = root / "actual"
            actual.mkdir()
            linked = root / "linked"
            if os.name == "nt":
                made = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(linked), str(actual)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(made.returncode, 0, made.stderr)
            else:
                linked.symlink_to(actual, target_is_directory=True)
            with self.assertRaisesRegex(
                InputValidationError, "reparse point|symbolic link"
            ):
                write_report_bundle(report, linked / "child", limits=Limits())

    def test_final_target_reparse_and_hardlink_source_alias_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = write_records(root / "input.jsonl", clone_records())
            report = build_report(load_artifact(input_path))
            output = root / "output"
            output.mkdir()
            target = output / "report.json"
            if os.name == "nt":
                elsewhere = root / "elsewhere"
                elsewhere.mkdir()
                made = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(target), str(elsewhere)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(made.returncode, 0, made.stderr)
            else:
                elsewhere = root / "elsewhere.json"
                elsewhere.write_text("untouched", encoding="utf-8")
                target.symlink_to(elsewhere)
            with self.assertRaisesRegex(
                InputValidationError, "reparse point|symbolic link"
            ):
                write_report_bundle(report, output, limits=Limits())
            if target.is_symlink():
                target.unlink()
            elif os.name == "nt":
                os.rmdir(target)
            os.link(input_path, target)
            with self.assertRaisesRegex(InputValidationError, "source input"):
                write_report_bundle(
                    report, output, limits=Limits(), source_paths=(input_path,)
                )

    def test_write_failure_removes_temporary_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self._report(root)
            output = root / "report"
            with patch.object(
                os, "replace", side_effect=OSError("blocked")
            ), self.assertRaisesRegex(InputValidationError, "replaced safely"):
                write_report_bundle(report, output, limits=Limits())
            self.assertEqual(list(output.glob(".*.tmp")), [])
            self.assertEqual(list(output.glob("report.*")), [])

    def test_bundle_discloses_stabilized_sizes_and_stream_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self._report(root)
            json_path, markdown_path, html_path = write_report_bundle(
                report, root / "out", limits=Limits()
            )
            json_data = json_path.read_bytes()
            markdown = markdown_path.read_text(encoding="utf-8")
            rendered_html = html_path.read_text(encoding="utf-8")
            expected_hash = hashlib.sha256(json_data).hexdigest()
            for rendered in (markdown, rendered_html):
                self.assertIn(expected_hash, rendered)
                self.assertIn(str(len(json_data)), rendered)
                self.assertIn(str(markdown_path.stat().st_size), rendered)
                self.assertIn(str(html_path.stat().st_size), rendered)

    def test_bounded_invariance_projection_uses_exact_caps(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._report(Path(temp))
        prototype = report["invariance_groups"][0]
        outcomes = ["violated"] * 60 + ["not_evaluable"] * 30 + ["satisfied"] * 20
        groups = []
        for index, outcome in enumerate(outcomes):
            item = deepcopy(prototype)
            item["group_id"] = f"group-{index:04d}"
            for role in ("baseline", "candidate"):
                item["roles"][role] = [{"pairing_key": None, "result": outcome}]
            groups.append(item)
        report["invariance_groups"] = groups
        markdown = markdown_text(report)
        for role in ("baseline", "candidate"):
            for expected in (
                f"| invariance {role} violated | 60 | 50 | 10 |",
                f"| invariance {role} not_evaluable | 30 | 25 | 5 |",
                f"| invariance {role} satisfied | 20 | 10 | 10 |",
            ):
                self.assertIn(expected, markdown)
        self.assertIn("violated 50, not evaluable 25, satisfied 10", markdown)
        self.assertNotIn("group-0050", markdown)

    def test_late_critical_regression_is_prioritized_before_detail_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._report(Path(temp))
        prototype = report["critical_groups"][0]
        groups = []
        for index in range(50):
            item = deepcopy(prototype)
            item["group_id"] = f"a-benign-{index:02d}"
            groups.append(item)
        regression = deepcopy(prototype)
        regression["group_id"] = "z-sole-regression"
        regression["transitions"]["label_transitions"] = {"pass->fail": 1}
        groups.append(regression)
        report["critical_groups"] = groups
        markdown = markdown_text(report)
        rendered_html = html_text(report)
        for rendered in (markdown, rendered_html):
            self.assertIn("z-sole-regression", rendered)
            self.assertIn("pass-&gt;fail", rendered)
            self.assertIn("1", rendered)
        self.assertNotIn("a-benign-49", markdown)

    def test_mapping_evidence_is_bounded_and_json_limit_short_circuits(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self._report(root)
            report["critical_groups"][0]["transitions"]["label_transitions"] = {
                f"before-{index}->after-{index}": 1 for index in range(20)
            }
            for rendered in (markdown_text(report), html_text(report)):
                self.assertIn("12 omitted", rendered)

            values = dict(Limits().values)
            values["json_report_bytes"] = 1
            from evalcanary.assurance import renderers as renderer_module

            with (
                patch.object(
                    renderer_module,
                    "markdown_text",
                    side_effect=AssertionError("Markdown must not render"),
                ),
                patch.object(
                    renderer_module,
                    "html_text",
                    side_effect=AssertionError("HTML must not render"),
                ),
                self.assertRaisesRegex(InputValidationError, "json_report_bytes"),
            ):
                write_report_bundle(
                    report, root / "short-circuit", limits=Limits(values=values)
                )

    def test_topology_change_simulation_fails_closed_and_cleans_temps(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self._report(root)
            output = root / "output"
            from evalcanary.assurance import renderers as renderer_module

            original = renderer_module._assert_directory_topology
            calls = 0

            def changing(path: Path, expected: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 7:
                    raise InputValidationError(
                        "Report output topology changed during validation."
                    )
                original(path, expected)  # type: ignore[arg-type]

            with patch.object(
                renderer_module, "_assert_directory_topology", side_effect=changing
            ), self.assertRaisesRegex(InputValidationError, "topology changed"):
                write_report_bundle(report, output, limits=Limits())
            self.assertEqual(list(output.glob(".*.tmp")), [])
            self.assertEqual(list(output.glob("report.*")), [])

    def test_second_publication_failure_restores_prior_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self._report(root)
            output = root / "output"
            write_report_bundle(report, output, limits=Limits())
            targets = tuple(
                output / name
                for name in (
                    "report.json",
                    "report.md",
                    "report.html",
                    "review-queue.json",
                    "review-queue.md",
                )
            )
            previous = {target.name: target.read_bytes() for target in targets}
            changed = deepcopy(report)
            changed["warnings"] = ["new generation marker"]
            real_replace = os.replace
            calls = 0

            def fail_second_publication(source: object, target: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 7:
                    raise OSError("second publication blocked")
                real_replace(source, target)

            with patch.object(
                os, "replace", side_effect=fail_second_publication
            ), self.assertRaisesRegex(InputValidationError, "replaced safely"):
                write_report_bundle(changed, output, limits=Limits())
            self.assertEqual(
                {target.name: target.read_bytes() for target in targets}, previous
            )
            self.assertEqual(list(output.glob(".*.tmp")), [])
            self.assertEqual(list(output.glob(".*.backup")), [])

    def test_each_preparation_failure_preserves_prior_bundle(self) -> None:
        from evalcanary.assurance import renderers as renderer_module

        for failure_at in (1, 2, 3, 4, 5):
            with self.subTest(failure_at=failure_at), tempfile.TemporaryDirectory() as temp:
                source, output, targets, previous, changed = self._existing_bundle(
                    Path(temp)
                )
                source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
                real_write = renderer_module._write_temporary
                calls = 0

                def fail_preparation(
                    *args: object,
                    _failure_at: int = failure_at,
                    _real_write: object = real_write,
                    **kwargs: object,
                ) -> Path:
                    nonlocal calls
                    calls += 1
                    if calls == _failure_at:
                        raise InputValidationError("injected preparation failure")
                    return _real_write(*args, **kwargs)  # type: ignore[operator]

                with patch.object(
                    renderer_module, "_write_temporary", side_effect=fail_preparation
                ), self.assertRaisesRegex(
                    InputValidationError, "injected preparation failure"
                ):
                    write_report_bundle(
                        changed, output, limits=Limits(), source_paths=(source,)
                    )
                self.assertEqual(
                    {target.name: target.read_bytes() for target in targets}, previous
                )
                self.assertEqual(
                    hashlib.sha256(source.read_bytes()).hexdigest(), source_hash
                )
                self.assertEqual(list(output.glob(".*.tmp")), [])
                self.assertEqual(list(output.glob(".*.backup")), [])

    def test_each_publication_failure_restores_prior_bundle(self) -> None:
        for failure_at in (6, 7, 8, 9, 10):
            with self.subTest(failure_at=failure_at), tempfile.TemporaryDirectory() as temp:
                source, output, targets, previous, changed = self._existing_bundle(
                    Path(temp)
                )
                real_replace = os.replace
                calls = 0

                def fail_publication(
                    source_path: object,
                    target_path: object,
                    _failure_at: int = failure_at,
                    _real_replace: object = real_replace,
                ) -> None:
                    nonlocal calls
                    calls += 1
                    if calls == _failure_at:
                        raise OSError("injected publication failure")
                    _real_replace(source_path, target_path)  # type: ignore[operator]

                with patch.object(
                    os, "replace", side_effect=fail_publication
                ), self.assertRaisesRegex(InputValidationError, "replaced safely"):
                    write_report_bundle(
                        changed, output, limits=Limits(), source_paths=(source,)
                    )
                self.assertEqual(
                    {target.name: target.read_bytes() for target in targets}, previous
                )
                self.assertEqual(list(output.glob(".*.tmp")), [])
                self.assertEqual(list(output.glob(".*.backup")), [])

    def test_each_post_publication_validation_failure_restores_prior_bundle(
        self,
    ) -> None:
        from evalcanary.assurance import renderers as renderer_module

        for failed_name in (
            "report.json",
            "report.md",
            "report.html",
            "review-queue.json",
            "review-queue.md",
        ):
            with self.subTest(failed_name=failed_name), tempfile.TemporaryDirectory() as temp:
                source, output, targets, previous, changed = self._existing_bundle(
                    Path(temp)
                )
                real_replace = os.replace
                real_validate = renderer_module._validate_path_chain
                published: set[str] = set()
                injected = False

                def observe_publication(
                    source_path: object,
                    target_path: object,
                    _real_replace: object = real_replace,
                    _published: set[str] = published,
                ) -> None:
                    target = Path(target_path)  # type: ignore[arg-type]
                    source_name = Path(source_path).name  # type: ignore[arg-type]
                    _real_replace(source_path, target_path)  # type: ignore[operator]
                    if source_name.endswith(".tmp") and target.name in {
                        "report.json",
                        "report.md",
                        "report.html",
                        "review-queue.json",
                        "review-queue.md",
                    }:
                        _published.add(target.name)

                def fail_validation(
                    path: Path,
                    *,
                    leaf_kind: str,
                    _real_validate: object = real_validate,
                    _failed_name: str = failed_name,
                    _published: set[str] = published,
                ) -> Path:
                    nonlocal injected
                    validated = _real_validate(  # type: ignore[operator]
                        path, leaf_kind=leaf_kind
                    )
                    if (
                        path.name == _failed_name
                        and path.name in _published
                        and not injected
                    ):
                        injected = True
                        raise InputValidationError(
                            "injected post-publication validation failure"
                        )
                    return validated

                with (
                    patch.object(os, "replace", side_effect=observe_publication),
                    patch.object(
                        renderer_module,
                        "_validate_path_chain",
                        side_effect=fail_validation,
                    ),
                    self.assertRaisesRegex(
                        InputValidationError, "post-publication validation"
                    ),
                ):
                    write_report_bundle(
                        changed, output, limits=Limits(), source_paths=(source,)
                    )
                self.assertTrue(injected)
                self.assertEqual(
                    {target.name: target.read_bytes() for target in targets}, previous
                )
                self.assertEqual(list(output.glob(".*.tmp")), [])
                self.assertEqual(list(output.glob(".*.backup")), [])

    def test_each_primary_restore_failure_uses_verified_fallback(self) -> None:
        for failed_name in (
            "report.json",
            "report.md",
            "report.html",
            "review-queue.json",
            "review-queue.md",
        ):
            with self.subTest(failed_name=failed_name), tempfile.TemporaryDirectory() as temp:
                source, output, targets, previous, changed = self._existing_bundle(
                    Path(temp)
                )
                source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
                real_replace = os.replace
                publication_failed = False
                primary_failed = False

                def fail_publication_and_primary_restore(
                    source_path: object,
                    target_path: object,
                    _failed_name: str = failed_name,
                    _real_replace: object = real_replace,
                ) -> None:
                    nonlocal publication_failed, primary_failed
                    target = Path(target_path)  # type: ignore[arg-type]
                    if target.name == "report.md" and not publication_failed:
                        publication_failed = True
                        raise OSError("injected Markdown publication failure")
                    if (
                        publication_failed
                        and target.name == _failed_name
                        and not primary_failed
                    ):
                        primary_failed = True
                        raise OSError("injected primary restore failure")
                    _real_replace(source_path, target_path)  # type: ignore[operator]

                with patch.object(
                    os, "replace", side_effect=fail_publication_and_primary_restore
                ), self.assertRaisesRegex(InputValidationError, "replaced safely"):
                    write_report_bundle(
                        changed, output, limits=Limits(), source_paths=(source,)
                    )
                self.assertTrue(publication_failed)
                self.assertTrue(primary_failed)
                self.assertEqual(
                    {target.name: target.read_bytes() for target in targets}, previous
                )
                self.assertEqual(
                    hashlib.sha256(source.read_bytes()).hexdigest(), source_hash
                )
                self.assertEqual(list(output.glob(".*.tmp")), [])
                self.assertEqual(list(output.glob(".*.backup")), [])

    def test_secondary_restore_failure_is_explicit_and_retains_backups(self) -> None:
        for failed_name in (
            "report.json",
            "report.md",
            "report.html",
            "review-queue.json",
            "review-queue.md",
        ):
            with self.subTest(failed_name=failed_name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source, output, _, previous, changed = self._existing_bundle(root)
                source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
                real_replace = os.replace
                publication_failed = False
                restore_failures = 0

                def fail_publication_and_both_restores(
                    source_path: object,
                    target_path: object,
                    _failed_name: str = failed_name,
                    _real_replace: object = real_replace,
                ) -> None:
                    nonlocal publication_failed, restore_failures
                    target = Path(target_path)  # type: ignore[arg-type]
                    if target.name == "report.md" and not publication_failed:
                        publication_failed = True
                        raise OSError("injected Markdown publication failure")
                    if publication_failed and target.name == _failed_name:
                        restore_failures += 1
                        if restore_failures <= 2:
                            raise OSError("injected restore failure")
                    _real_replace(  # type: ignore[operator]
                        source_path, target_path
                    )

                with patch.object(
                    os, "replace", side_effect=fail_publication_and_both_restores
                ), self.assertRaisesRegex(
                    InputValidationError,
                    f"recovery is incomplete.*{failed_name}.*sha256=",
                ) as raised:
                    write_report_bundle(
                        changed, output, limits=Limits(), source_paths=(source,)
                    )
                self.assertNotIn(str(root), str(raised.exception))
                self.assertEqual(restore_failures, 2)
                self.assertEqual(
                    hashlib.sha256(source.read_bytes()).hexdigest(), source_hash
                )
                backups = list(output.glob(".*.backup"))
                self.assertEqual(len(backups), 5)
                for name, expected_bytes in previous.items():
                    matching = [
                        path
                        for path in backups
                        if path.name.startswith(f".{name}.")
                    ]
                    self.assertEqual(len(matching), 1)
                    self.assertEqual(matching[0].read_bytes(), expected_bytes)
                self.assertEqual(list(output.glob(".*.tmp")), [])

    def test_core_pipeline_attempts_no_network_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = write_records(root / "input.jsonl", clone_records())
            with (
                patch.object(socket.socket, "connect", side_effect=AssertionError("network")),
                patch.object(socket, "create_connection", side_effect=AssertionError("network")),
                patch.object(urllib.request, "urlopen", side_effect=AssertionError("network")),
            ):
                artifact = load_artifact(input_path)
                report = build_report(artifact)
                write_report_bundle(report, root / "out", limits=artifact.limits)


class AssuranceCliTests(unittest.TestCase):
    def test_migrate_exit_code_mapping_and_report_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            valid = write_records(root / "valid.jsonl", clone_records())
            no_contract_out = root / "no-contract"
            self.assertEqual(
                main(["migrate", "--input", str(valid), "--out", str(no_contract_out)]),
                0,
            )
            self.assertTrue((no_contract_out / "report.json").is_file())

            hard_contract = write_json(
                root / "hard.json", contract(rule("corpus_equal", operator="ne"))
            )
            self.assertEqual(
                main(
                    [
                        "migrate",
                        "--input",
                        str(valid),
                        "--contract",
                        str(hard_contract),
                        "--out",
                        str(root / "hard"),
                    ]
                ),
                2,
            )

            review_items = clone_records()
            before = review_items[0]["evaluations"][0]["context_components"]["runtime"]
            after = component("python-3.14")
            review_items[0]["evaluations"][1]["context_components"]["runtime"] = after
            review_items[0]["allowed_context_differences"] = [
                {
                    "component": "runtime",
                    "expected_baseline_component_value": before,
                    "expected_candidate_component_value": after,
                    "rationale": "Exact reviewed difference.",
                    "reviewer_id": "reviewer-1",
                    "disposition": "not_isolated_review_required",
                }
            ]
            review = write_records(root / "review.jsonl", review_items)
            self.assertEqual(
                main(["migrate", "--input", str(review), "--out", str(root / "review")]),
                4,
            )

            missing_items = clone_records()
            missing_items[:] = [
                item
                for item in missing_items
                if item.get("trial_id") != "case-2-candidate-0"
            ]
            missing = write_records(root / "missing.jsonl", missing_items)
            self.assertEqual(
                main(["migrate", "--input", str(missing), "--out", str(root / "missing")]),
                3,
            )

            invalid = root / "invalid.jsonl"
            invalid.write_bytes(b"not-json\n")
            self.assertEqual(
                main(["migrate", "--input", str(invalid), "--out", str(root / "invalid")]),
                3,
            )

    def test_invalid_contract_configuration_exits_three(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            valid = write_records(root / "valid.jsonl", clone_records())
            bad_rule = rule("determinate_coverage", parameters={"role": "candidate"})
            bad_rule["parameters"]["extra"] = True
            bad_contract = write_json(root / "bad.json", contract(bad_rule))
            self.assertEqual(
                main(
                    [
                        "migrate",
                        "--input",
                        str(valid),
                        "--contract",
                        str(bad_contract),
                        "--out",
                        str(root / "bad"),
                    ]
                ),
                3,
            )
            self.assertEqual(
                main(
                    [
                        "migrate",
                        "--input",
                        str(valid),
                        "--contract",
                        str(root / "missing-contract.json"),
                        "--out",
                        str(root / "missing-contract"),
                    ]
                ),
                3,
            )
            self.assertEqual(
                main(
                    [
                        "migrate",
                        "--input",
                        str(valid),
                        "--limits",
                        str(root / "missing-limits.json"),
                        "--out",
                        str(root / "missing-limits"),
                    ]
                ),
                3,
            )


if __name__ == "__main__":
    unittest.main()
