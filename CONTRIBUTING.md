# Contributing

## Scope

EvalCanary is an evaluator reliability layer, not a general model-evaluation
runner. Contributions should strengthen evaluator migration analysis,
provenance, policies, integrations, or review quality.

## Development setup

```console
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python scripts/release_check.py
```

On Windows PowerShell, replace `.venv/bin/python` with
`.venv\Scripts\python.exe`.

The complete development gate is:

```console
ruff check .
mypy
pytest
python -m build
python scripts/release_check.py
```

The runtime remains standard-library-only. Development tools are isolated in
the `dev` optional dependency group.

## Pull-request requirements

1. Add or update tests before changing public behavior.
2. Preserve fixed-corpus semantics.
3. State whether findings are observed, measured, inferred, or unknown.
4. Document any new dependency and why the standard library is insufficient.
5. Avoid unrelated refactoring.
6. Do not include private model outputs or benchmark data.
7. Update the changelog for user-visible changes.
8. Keep all external workflow actions pinned to full commit SHAs.
9. Preserve the trusted-code warning and privacy-preserving report defaults.

## Compatibility

The supported runtime is Python 3.11 through 3.14 on Windows, Linux, and
macOS. PowerShell delivery scripts must remain compatible with Windows
PowerShell 5.1 and use ASCII-only executable text.

## Review model

Material changes receive an applicability check, adversarial review,
regression tests, and an explicit rollback path. The number of review methods
agreeing is not treated as proof; evidence quality and causal specificity
control the decision.
