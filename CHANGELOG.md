# Changelog

All notable changes are documented here. The project follows semantic
versioning after the v0.x experimental series.

## 0.2.0 - Unreleased

This entry describes the release candidate. The publication date will be set
only when the release is authorized; it is not a release announcement.

### Added

- Offline, data-only comparison of frozen evaluator judgments, including
  categorical and exact numeric transitions, repeated trials, declared
  invariance relations, critical groups, and raw and aggregate anchors.
- Explicit evaluator, corpus, component, and context provenance with strict
  comparability checks and reviewed context exceptions.
- Human-authored contracts using a closed metric vocabulary, explicit missing
  evidence behavior, and hard, review, or informational rule severities.
- Canonical JSON evidence, bounded Markdown and scriptless HTML projections,
  and exhaustive JSON plus bounded Markdown review queues with exact pointers.
- Four bundled structural schemas, runtime semantic validation, resource limits,
  validation-only preflight, and an inert authoring scaffold.
- A public producer API with explicit semantic decisions, unresolved-marker
  guards, deterministic serialization, and synthetic offline examples.
- Read-only `contract-review` with source-bound contract coverage, evidence
  availability, and advisory duplicate-rule warnings. Coverage does not rate
  policy sufficiency or evaluator correctness.

### Changed

- Adopted ReplayDocket as the public brand and `replaydocket` as the distribution
  and preferred CLI. The `evalcanary` CLI, Python imports, environment variables,
  schema identifiers, canonical provenance and historical repository remain
  compatible. See [migration guidance](docs/MIGRATION.md).
- Prepared new ReplayDocket presentation assets while preserving the original
  EvalCanary images and immutable v0.1.0/v0.1.1 release history.
- Updated the release procedure, candidate-date policy, two-workflow quickstart,
  privacy guidance and packaged assurance documentation.

### Fixed

- Reject excessively nested JSON through the handled validation-error path.
- Bound preflight input and contract reads before parsing, enforcing the existing
  configured byte limit without changing valid-input policy semantics.

- Hardened assurance report recovery, queue integrity, canonical relation
  configuration, and bounded numeric reviewer projections during development.
- Added hosted CI definitions for the extracted-sdist full test suite and the
  Windows PowerShell 5.1 parser gate.

The trusted-verifier `diff` workflow remains supported. Assurance results are
review evidence, not automatic correctness certification. Hosted RC1 validation
and publication remain separate gates.

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
