# Changelog

All notable changes are documented here. The project follows semantic
versioning after the v0.x experimental series.

## 0.1.1 - 2026-08-08

### Changed

- Updated CodeQL `init` and `analyze` together to the same reviewed full commit SHA.
- Migrated package licensing metadata to the PEP 639 SPDX form and raised the
  Setuptools build-system floor to a version that supports it.
- Added a dedicated Dependabot group for CodeQL Action sub-actions so future
  compatible updates are proposed together instead of as mismatched steps.

## 0.1.0 - 2026-08-08

### Added

- Fixed-corpus comparison of two trusted Python verifiers.
- Pass-to-pass, pass-to-fail, fail-to-pass, and fail-to-fail transitions.
- Exact two-sided McNemar test.
- Deterministic paired bootstrap interval.
- Dotted-path subgroup analysis.
- TOML migration policies and CI-safe exit codes.
- JSON, Markdown, and self-contained accessible HTML reports.
- Input, verifier, runtime, and sanitized command provenance.
- Content-derived run IDs that distinguish corpus and both verifier versions.
- Fresh-directory report reproducibility checks and basename-only path privacy.
- Alternative verifier interpreters that do not require EvalCanary installation.
- Python-level verifier console-output protection and finite-score validation.
- Privacy-preserving report defaults.
- Exact-match demonstration, test suite, mutation gate, and release checks.
- Cross-platform composite GitHub Action with report and policy outputs.
- GitHub-hosted tests on Windows, Linux, and macOS with Python 3.11–3.14.
- Ruff, mypy, pytest, distribution-build, clean-wheel, and local-action smoke gates.
- Stable `ci-gate` and `codeql` checks for branch protection.

### Changed

- Updated GitHub-maintained workflow actions to their current major releases
  and pinned every external action reference to a full commit SHA.
- Expanded development compatibility to mypy 2.x and pytest 9.x, with those
  tools now executed in CI rather than merely declared.
- Grouped future Dependabot minor and patch updates while keeping major updates
  independently reviewable.

### Fixed

- Windows PowerShell 5.1 publication root resolution and expected-failure
  handling.
- Publication preflight now uses bounded native-process execution, exact-head
  confirmation, remote-availability discrimination, and post-push verification.
- Standalone Windows verification now resolves its project root after parameter
  binding and parses every repository PowerShell script.
- The GitHub Action no longer depends on Bash and now preserves outputs even
  when a configured policy fails.
