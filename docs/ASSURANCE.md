# Product assurance record

## Evidence status

- **Executed locally:** the source compile gate, 23-test suite, deterministic
  fresh-directory replay, mutation gate, report contract, and PowerShell ASCII
  gate passed in the release-construction environment.
- **Executed on Windows 11:** installation, the 20-test predecessor suite,
  deterministic replay, mutation testing, PowerShell 5.1 parsing, ASCII checks,
  the Windows report contract, exact-path staging, publication preflight, and
  remote publication passed on the maintainer workstation.
- **Executed on the first public release candidate:** GitHub-hosted CI passed on
  Windows, Linux, and macOS for Python 3.11–3.13, and CodeQL passed at commit
  `21dd31a7d750d6eb8ea9d6ec79eac36667de8768`.
- **Required before the v0.1.0 tag:** this hardening change must pass the expanded
  Python 3.11–3.14 matrix, Ruff, mypy, pytest, distribution build, clean-wheel
  install, three-platform `uses: ./` action smoke test, stable `ci-gate`, and
  CodeQL.
- **Required before Marketplace publication:** a separate repository must use
  the exact `v0.1.0` tag successfully, including a policy-failure case and all
  declared action outputs.
- **Unknown:** external maintainer demand and final legal or trademark clearance
  of the public name.

## Material methods

### Red team

Principal attacks:

- existing evaluation frameworks may add equivalent comparison features;
- users may treat changed verdicts as proof that the new evaluator is wrong;
- subprocess isolation may be mistaken for secure sandboxing;
- reports may leak proprietary outputs through reasons or details;
- path or command provenance may leak local directory structure;
- a run identifier may fail to distinguish different verifier pairs;
- small paired samples can produce unstable statistical interpretations;
- a composite action can appear supported without being tested through
  `uses: ./` on each operating system;
- declared development-tool ranges can appear compatible without CI actually
  installing or executing those tools;
- mutable workflow tags can introduce unreviewed supply-chain changes;
- package expansion may outrun solo-maintainer capacity.

### Blue team

Controls:

- narrow fixed-corpus proposition;
- explicit epistemic limitations in every report;
- trusted-code warning in CLI and security documentation;
- original payload and verifier source exclusion by default;
- basename-only path provenance and content-derived run identity;
- deterministic statistics and named methods;
- cross-platform composite-action runner with machine-readable outputs;
- a three-operating-system local-action smoke matrix;
- explicit Ruff, mypy, pytest, distribution, and clean-wheel gates;
- full-SHA workflow action pins and a release check that rejects floating refs;
- stable aggregate status checks for branch protection;
- demand-gated roadmap and kill conditions;
- dependency-free runtime.

### Arbiter

Proceed with v0.1 as a bounded technical prototype after the expanded remote
release gates pass. Do not describe it as a complete evaluation platform or
secure execution environment. Marketplace publication remains blocked until an
external tagged-consumer canary succeeds.

## FMEA summary

| Failure | Consequence | Control | Residual risk |
|---|---|---|---|
| Mismatched case identity | invalid paired comparison | unique IDs and ordered identity checks | upstream semantic duplicates |
| Verifier exception | incomplete comparison | error verdict and policy count | silent logic errors remain possible |
| Verifier hangs | blocked CI | total process timeout | one case can consume most of timeout |
| Sensitive report | data disclosure | payloads omitted by default | reasons, details, paths, and diffs remain |
| Statistical overclaim | false assurance | named tests and limitations | users may ignore wording |
| Policy misuse | arbitrary gate treated as validity | policy described as project-specific | organizational pressure can harden weak thresholds |
| Untrusted verifier | host compromise | explicit trusted-code boundary | user may overlook warning |
| Schema drift | broken automation | versioned schema | v0.x additions still require consumers to tolerate extras |
| Action wrapper mismatch | Marketplace users receive behavior different from the CLI | shared CLI invocation, action unit tests, three-platform `uses: ./` smoke | external repositories can have unusual runner policies |
| Dev-tool major update | declared range accepts an incompatible release | CI installs and runs the complete dev extra | future tool semantics can change between monthly updates |
| Workflow dependency compromise | CI executes substituted action code | full commit-SHA pins and Dependabot review | reviewed upstream commit can still contain defects |
| Unprotected main | broken release state can be pushed directly | stable required checks and branch protection | owner emergency bypass remains a governance risk |

## Fault-tree top events

### Incorrect migration conclusion

Possible paths:

- corpus changed between versions;
- case identity is semantically duplicated;
- external verifier dependency changed;
- verifier is nondeterministic;
- errors are ignored;
- aggregate score is reviewed without changed cases.

### Sensitive data disclosure

Possible paths:

- explicit `--include-content`;
- reasons or details echo output content;
- user explicitly includes a source diff containing credentials;
- output directory is published as a CI artifact;
- a basename, reason, or detail reveals internal naming or content.

### Broken public action release

Possible paths:

- action metadata differs from the tested CLI contract;
- caller Python is unsupported or absent;
- cross-platform shell assumptions fail;
- declared outputs are not written on policy failure;
- a release tag points to an unverified commit;
- Marketplace publication precedes an external tagged-consumer test.

## STPA constraints

- Never compare unmatched identities.
- Never classify an error as pass or fail.
- Never imply that changed means incorrect.
- Never include original payloads without an explicit option.
- Never return policy success when a configured check failed.
- Never describe subprocess execution as a security sandbox.
- Never publish a release from a commit that did not pass `ci-gate` and
  `codeql`.
- Never treat a local `uses: ./` smoke test as proof that the published tag is
  consumable externally.

## Common-cause risks

- one maintainer controls code, documentation, statistics, and release
  decisions;
- one malformed input schema can affect every report surface;
- Python runtime differences can affect both verifier versions;
- hidden external services can invalidate deterministic assumptions;
- one workflow configuration defect can invalidate every matrix result;
- pressure for stars can encourage premature scope expansion.

## Control-induced risks

- strict policy gates can block legitimate evaluator improvements;
- content redaction can make root-cause review harder;
- dependency restraint can delay sophisticated statistics or sandboxing;
- full-SHA workflow pins require disciplined update review;
- a larger CI matrix increases cost and can delay feedback;
- branch protection can block emergency corrections when required checks are
  unavailable;
- extensive assurance work can delay user validation;
- a memorable brand can create confidence disproportionate to maturity.

## Release requirements

- all unit and integration tests pass;
- compile check passes across source, tests, and scripts;
- package, citation, changelog, and source versions agree;
- every external workflow action is pinned to a full commit SHA;
- the Windows/Linux/macOS runtime matrix passes on Python 3.11–3.14;
- Ruff, strict mypy, pytest, sdist/wheel build, and clean-wheel installation
  pass;
- the composite action passes through `uses: ./` on all three operating
  systems and emits the documented outputs;
- demo produces JSON, Markdown, and HTML;
- fresh-directory replay reproduces the canonical report hash on one runtime
  under `SOURCE_DATE_EPOCH`;
- package contains no generated reports, secrets, or private data;
- Windows PowerShell parser and installation gates pass before public release;
- `ci-gate` and `codeql` protect `main` before tagging;
- an external repository consumes the exact tag before Marketplace
  publication;
- publication verifies repository identity, visibility, remote main SHA,
  default branch, and final clean local state;
- no Critical or unresolved Serious finding remains.
