# Release procedure

This procedure separates source validation, repository governance, exact tags,
and GitHub Marketplace publication. A green local run is necessary but not
sufficient.

## 1. Release-candidate branch

- Start from a clean, current `main` branch.
- Make release changes on a dedicated branch.
- Open a pull request; do not push release work directly to `main`.
- Require the stable `ci-gate` and `codeql` checks.
- Resolve all review conversations and verify the exact merge commit.

## 2. Required automated evidence

The pull request must pass:

- the Windows/Linux/macOS runtime matrix on Python 3.11–3.14;
- Ruff;
- strict mypy;
- pytest and the standard-library unittest suite;
- sdist and wheel construction;
- installation and demo from a clean wheel environment;
- the local composite-action smoke test on all three operating systems;
- deterministic fresh-directory report replay;
- mutation testing;
- PowerShell 5.1 ASCII and parser gates;
- CodeQL.

The stable protection contexts are:

```text
ci-gate
codeql
```

## 3. Manual review

Before tagging:

- inspect the rendered README and screenshot on GitHub;
- verify the repository description, topics, license, and security policy;
- confirm the action metadata banner reports no Marketplace errors;
- inspect the built report artifact for private data;
- confirm that no generated report, virtual environment, `_local`, secret, or
  private corpus is tracked;
- close or supersede redundant dependency pull requests;
- confirm the changelog, source version, package version, and citation version
  agree.

## 4. Tagging

Create the exact annotated release tag from the verified `main` commit:

```console
git tag -a v0.1.0 -m "EvalCanary v0.1.0"
git push origin v0.1.0
```

Consumers that require immutable references should use `v0.1.0` or a full
commit SHA. A movable `v0` compatibility tag may be added only if the project
explicitly adopts that maintenance policy.

## 5. External action canary

Before Marketplace publication, use `lmdixon23/evalcanary@v0.1.0` from a
separate public fixture repository. Verify:

- the action installs on a clean runner;
- a policy-passing comparison succeeds;
- a policy-failing comparison fails with exit code 2;
- all declared action outputs are present;
- the review packet can be uploaded without disclosing unintended content.

A local `uses: ./` smoke test does not replace this external tagged-consumer
check.

## 6. GitHub release and Marketplace

Draft a GitHub release from `v0.1.0`, attach the built wheel and sdist, include
checksums, and select the Marketplace publication option. Confirm that the
Marketplace name, categories, description, branding, inputs, outputs, and
trusted-code boundary render correctly before publishing.

## 7. Post-release verification

- Re-run the external canary against the published release.
- Confirm the release tag resolves to the intended commit.
- Confirm branch protection remains active.
- Record the release evidence in `docs/ASSURANCE.md`.
- Do not announce broad availability until these checks pass.

## Rollback

If the exact tag points to the wrong commit or the released action is unsafe,
do not silently move the exact tag. Mark the release as withdrawn, publish a
corrected patch version, and document the defect. Mutable compatibility tags,
when used, may move only under the documented maintenance policy.
