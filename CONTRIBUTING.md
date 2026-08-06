# Contributing

## Scope

EvalCanary is an evaluator reliability layer, not a general model-evaluation runner. Contributions should strengthen evaluator migration analysis, provenance, policies, integrations, or review quality.

## Development setup

```console
python -m venv .venv
.venv/bin/python scripts/bootstrap_local.py
.venv/bin/python -m unittest discover -s tests -v
```

On Windows PowerShell, use `.venv\\Scripts\\python.exe`.

## Pull-request requirements

1. Add or update tests before changing public behavior.
2. Preserve fixed-corpus semantics.
3. State whether findings are observed, measured, inferred, or unknown.
4. Document any new dependency and why the standard library is insufficient.
5. Avoid unrelated refactoring.
6. Do not include private model outputs or benchmark data.
7. Update the changelog for user-visible changes.

## Compatibility

The supported runtime is Python 3.11 or later on Windows, Linux, and macOS. PowerShell delivery scripts must remain compatible with Windows PowerShell 5.1 and use ASCII-only executable text.

## Review model

Material changes receive an applicability check, adversarial review, regression tests, and an explicit rollback path. The number of review methods agreeing is not treated as proof; evidence quality and causal specificity control the decision.
