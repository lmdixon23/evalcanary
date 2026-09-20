# Release procedure

This procedure separates candidate source, local verification, human review,
hosted checks, immutable tags and publication. Passing a check does not authorize
the next external action.

## 1. Candidate identity and dates

Prepare v0.2.0 on `release/replaydocket-v0.2.0-rc1` from the accepted
ReplayDocket migration. Keep the historical stopped candidate and v0.1.0/v0.1.1
tags, release names, assets and checksums unchanged.

Package metadata, `evalcanary.__version__` and CITATION.cff use `0.2.0`.
While the candidate is unpublished, omit `date-released` from CITATION.cff and
use `## 0.2.0 - Unreleased` in CHANGELOG.md. Set the actual publication date
in both only as part of the authorized final release preparation. Do not copy a
historical release date or treat a reproducible report timestamp as publication.

`SOURCE_DATE_EPOCH` controls the demo/report timestamp for reproducibility.
Record its exact value with screenshot provenance. After any source or metadata
change, rebuild artifacts and revalidate their identities; recapture screenshots
if the generating report changes.

The stable assurance-engine identifier `0.2.0.dev0` is intentionally retained
in canonical evidence; it is separate from the distribution version. Schema
URNs, report IDs, import names, environment variables and canonical tool names
also remain stable. See [migration guidance](MIGRATION.md).

## 2. Local validation and package gates

Run from a clean candidate checkout with Python 3.11 or later:

```console
python -m pip install -e ".[dev]"
python -m pip check
ruff check .
mypy
pytest
python scripts/release_check.py
python scripts/check_ascii_ps.py
python -m build
python scripts/check_sdist.py dist/replaydocket-0.2.0.tar.gz
```

Use a fresh output directory for every build. The sdist gate extracts safely,
installs into a fresh environment, verifies that the imported package comes from
that environment and runs every shipped unittest. Build isolation may download
the backend; dependency-free/offline runtime does not imply offline installation.

On Windows, run the actual Windows PowerShell 5.1 parser:

```powershell
powershell.exe -NoProfile -NonInteractive -File .\scripts\Test-EvalCanary-Windows.ps1 -ParseOnly
```

Also verify the exact built wheel in a fresh environment: both command aliases,
`python -m evalcanary`, imports, demo, offline migrate, preflight, contract
review and the shipped test suite. Confirm zero mandatory runtime dependencies,
all four schemas, bundled examples, and the supported old-distribution
uninstall/replacement path. Exclude local evidence, environments, caches,
generated reports and private input from packages. Inspect every archive member
and retain SHA-256 and byte size for each final artifact.

Use the maintained tests, schema/example byte-drift checks, fresh-directory
deterministic replay and mutation gate. A successful clean source export is
useful evidence; it does not substitute for checking out the exact final commit.

## 3. Hosted pull-request verification

Opening a PR, pushing, merging, tagging or publishing requires separate authority.
When authorized, open a release PR targeting `main`; do not push directly to it.
Resolve review conversations and verify the exact merge commit.

The exact reviewed revision must pass:

- Windows/Linux/macOS × Python 3.11–3.14 (12 runtime cells);
- Ruff, strict mypy, pytest and unittest;
- wheel and sdist builds, clean wheel install/demo, extracted-sdist full suite;
- three-OS `uses: ./` Action smoke tests, including policy-failure outputs;
- deterministic replay, mutation, schema and example drift gates;
- PowerShell ASCII and Windows PowerShell 5.1 parser gates;
- CodeQL.

Required stable protection contexts are `ci-gate` and `codeql`.
Check actual results for the exact revision and live branch protection. A
workflow definition or local Windows run is not a hosted matrix PASS.

## 4. Manual release review

Review rendered README, new featured card and genuine desktop/mobile report
captures. Preserve the original EvalCanary PNGs as historical assets. Inspect
canonical JSON and queue artifacts for unintended disclosure. Confirm metadata,
action inputs/outputs, repository description/topics/license/security policy,
Marketplace display and installation instructions. Confirm no private evidence
or credentials entered source or artifacts.

The maintained repository/Action address remains `lmdixon23/EvalCanary`.
A source Action display-name change does not change the live Marketplace listing.
Record package namespace observations and their time; an empty namespace does
not guarantee availability or authorize upload.

## 5. Exact tag and external canary

Only after human authorization and all required checks pass, create the
annotated `v0.2.0` tag from the verified `main` commit. Resolve local and remote
tag targets and record that exact commit. Do not create or move `v0` without an
explicit maintenance policy. Do not execute the historical repository-bootstrap
`Publish-EvalCanary.ps1` as an update-release procedure.

The separate `lmdixon23/EvalCanaryReleaseCanary` repository must consume
`lmdixon23/EvalCanary@v0.2.0`. Its mutation and execution require explicit
authorization for that target. Verify a clean-runner install, passing comparison,
hard-policy failure with exit 2, all seven declared outputs, and safe report
artifact contents. A local Action test does not replace this exact-tag consumer.

## 6. Authorized channels and publication

The existing channels are GitHub Releases and GitHub Action Marketplace.
PyPI publication, a repository rename, a new domain or a renamed canary is not
implied by the distribution name or by this procedure.

After authorization, draft the GitHub release from the exact tag. Attach only
the reviewed final `replaydocket-0.2.0` wheel and sdist, checksums, and public
release notes. Do not upload internal handoffs/review ZIPs. Check the
ReplayDocket Marketplace name, categories, branding, description, trusted-code
boundary, inputs and outputs before its authorized publication. Publish only
after the exact-tag external canary succeeds.

## 7. Post-publication checks and rollback

Verify the published tag target, downloaded asset sizes and hashes, Marketplace
rendering, external consumer result, branch protection, and release/citation
dates. Append a public evidence record without rewriting historical claims.

If an exact tag is wrong or released behavior is unsafe, mark the release
withdrawn and issue a corrected patch version. Never silently move an exact tag,
replace published bytes or normalize old checksums.
