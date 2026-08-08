# EvalCanary

[![CI](https://github.com/lmdixon23/evalcanary/actions/workflows/ci.yml/badge.svg)](https://github.com/lmdixon23/evalcanary/actions/workflows/ci.yml)
[![CodeQL](https://github.com/lmdixon23/evalcanary/actions/workflows/codeql.yml/badge.svg)](https://github.com/lmdixon23/evalcanary/actions/workflows/codeql.yml)
[![Python 3.11–3.14](https://img.shields.io/badge/python-3.11--3.14-3776AB.svg)](https://www.python.org/)
[![MIT license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Catch evaluation drift before it ships.**

EvalCanary shows exactly which fixed evaluation results change when a verifier,
scorer, rubric implementation, or grading rule changes.

It treats an evaluator update as a migration:

- replay the same output corpus against both versions;
- classify every verdict transition;
- estimate paired uncertainty;
- inspect subgroup effects;
- attach source and execution provenance;
- enforce explicit CI policy gates.

EvalCanary does **not** determine automatically which evaluator is correct. It
produces the change packet that a domain reviewer needs.

![EvalCanary synthetic migration report](docs/assets/evalcanary-demo-report.png)

## Why evaluator migrations need their own diff

An aggregate benchmark score can remain nearly unchanged while many individual
cases reverse in opposite directions. In reinforcement learning with verifiable
rewards, an evaluator defect can become a training signal rather than merely a
reporting error.

EvalCanary holds the model-output corpus fixed and changes only the evaluator.
That isolates evaluator sensitivity from model sampling, prompt changes, and
new generations.

## Five-minute local start

Requires Python 3.11 or later. The runtime has no third-party dependencies.

```console
git clone https://github.com/lmdixon23/evalcanary.git
cd evalcanary
python -m venv .venv
.venv/bin/python scripts/bootstrap_local.py
.venv/bin/evalcanary demo --out evalcanary-demo
```

Windows PowerShell:

```powershell
git clone https://github.com/lmdixon23/evalcanary.git
Set-Location evalcanary
py -3.11 -m venv .venv
.venv\Scripts\python.exe scripts\bootstrap_local.py
.venv\Scripts\evalcanary.cmd demo --out evalcanary-demo
```

Open `evalcanary-demo/report/report.html`.

## Use the GitHub Action

The caller must set up Python 3.11 or later. The exact release tag is preferred
for reproducibility.

```yaml
name: Evaluator migration

on:
  pull_request:

permissions:
  contents: read

jobs:
  evaluator-diff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.11"
      - name: Compare evaluator versions
        id: evalcanary
        uses: lmdixon23/evalcanary@v0.1.0
        with:
          data: outputs.jsonl
          before: verifier_before.py
          after: verifier_after.py
          policy: evalcanary.toml
          slice: |
            metadata.domain
            metadata.language
          output: evalcanary-report
      - name: Upload review packet
        if: always()
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: evalcanary-report
          path: evalcanary-report
          if-no-files-found: error
```

Action outputs:

- `report_directory`;
- `report_json`;
- `report_markdown`;
- `report_html`;
- `run_id`;
- `changed_cases`;
- `policy_passed` (`true`, `false`, or `not-configured`).

The action executes both verifier files with the runner account's permissions.
It is process isolation, **not a security sandbox**. Use only trusted verifier
code.

## Compare two verifiers from the CLI

Every JSONL object requires a unique `id`. The same fixed object is passed to
both verifiers.

```json
{"id":"math-001","expected":"4","output":"4 ","metadata":{"domain":"math"}}
```

Each trusted Python verifier defines `verify(case)` and returns either a
boolean or a dictionary containing boolean `passed`.

```python
def verify(case: dict) -> dict:
    passed = case["output"].strip() == case["expected"]
    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "normalized exact match",
    }
```

Run:

```console
evalcanary diff \
  --data outputs.jsonl \
  --before verifier_before.py \
  --after verifier_after.py \
  --policy evalcanary.toml \
  --slice metadata.domain \
  --out evalcanary-report
```

Outputs:

- `report.json` for automation;
- `report.md` for pull requests and research records;
- `report.html` for accessible local review.

Source code is not embedded in reports by default. Add
`--include-source-diff` only when the verifier files are safe to disclose to
the report audience. Original case payloads likewise require the separate
`--include-content` flag. Absolute and parent paths are reduced to basenames in
report provenance and recorded commands; content hashes provide artifact
identity.

## CI policy

```toml
[policy]
min_cases = 100
max_error_cases = 0
max_abs_score_delta = 0.005
max_pass_to_fail = 10
max_fail_to_pass = 10
max_changed_cases = 15
require_statistical_review_below_p = 0.05
```

Exit codes:

- `0`: comparison completed and the configured policy passed;
- `2`: comparison completed and the configured policy failed;
- `3`: input, execution, or configuration error.

## Public boundary

Version 0.1 supports trusted deterministic Python verifiers and pass/fail
migration analysis. It does not yet provide:

- an untrusted-code sandbox;
- repeated LLM-judge sampling;
- semantic perturbation generation;
- hosted storage or dashboards;
- automatic causal attribution;
- a general benchmark runner.

## Documentation

- [Project design](docs/PROJECT_DESIGN.md)
- [Verifier API](docs/VERIFIER_API.md)
- [Policy reference](docs/POLICY.md)
- [Report schema](docs/REPORT_SCHEMA.md)
- [Product assurance](docs/ASSURANCE.md)
- [Release procedure](docs/RELEASING.md)
- [Roadmap](docs/ROADMAP.md)
- [Name-clearance record](docs/NAME_CLEARANCE.md)

## Trust model

A changed verdict demonstrates evaluator sensitivity. It does not demonstrate
that the previous evaluator was wrong, that the candidate is better, or that a
benchmark conclusion is invalid. Reports preserve that distinction explicitly.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development and review gates.
Report security issues through the private process described in
[SECURITY.md](SECURITY.md), not through a public issue.

## License

MIT
