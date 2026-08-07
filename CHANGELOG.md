# Changelog

All notable changes are documented here. The project follows semantic versioning after the v0.x experimental series.

## 0.1.0 - 2026-08-05

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
- Exact-match demonstration, GitHub Action, test suite, and release gates.

### Fixed

- Windows PowerShell 5.1 publication root resolution and expected-failure handling.
- Publication preflight now uses bounded native-process execution, exact-head confirmation, remote-availability discrimination, and post-push verification.
