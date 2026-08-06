# Product assurance record

## Evidence status

- **Executed:** automated tests and demo commands run in the delivered Linux environment.
- **Observed:** source tree, reports, packaging, and generated hashes inspected directly.
- **Inferred:** expected behavior on Windows PowerShell 5.1 from ASCII-only scripts and explicit compatibility design.
- **Unknown:** Windows 11 execution, GitHub-hosted CI execution, external maintainer demand, and public name clearance.

## Material methods

### Red team

Principal attacks:

- existing evaluation frameworks may add equivalent comparison features;
- users may treat changed verdicts as proof that the new evaluator is wrong;
- subprocess isolation may be mistaken for secure sandboxing;
- reports may leak proprietary outputs through reasons or details;
- small paired samples can produce unstable statistical interpretations;
- package expansion may outrun solo-maintainer capacity.

### Blue team

Controls:

- narrow fixed-corpus proposition;
- explicit epistemic limitations in every report;
- trusted-code warning in CLI and security documentation;
- original payload and verifier source exclusion by default;
- deterministic statistics and named methods;
- demand-gated roadmap and kill conditions;
- dependency-free runtime.

### Arbiter

Proceed with v0.1 as a bounded technical prototype. Do not describe it as a complete evaluation platform or secure execution environment. Expansion requires external use evidence.

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
- local path reveals internal structure.

## STPA constraints

- Never compare unmatched identities.
- Never classify an error as pass or fail.
- Never imply that changed means incorrect.
- Never include original payloads without an explicit option.
- Never return policy success when a configured check failed.
- Never describe subprocess execution as a security sandbox.

## Common-cause risks

- one maintainer controls code, documentation, statistics, and release decisions;
- one malformed input schema can affect every report surface;
- Python runtime differences can affect both verifier versions;
- hidden external services can invalidate deterministic assumptions;
- pressure for stars can encourage premature scope expansion.

## Control-induced risks

- strict policy gates can block legitimate evaluator improvements;
- content redaction can make root-cause review harder;
- dependency restraint can delay sophisticated statistics or sandboxing;
- extensive assurance work can delay user validation;
- a memorable brand can create confidence disproportionate to maturity.

## Release requirements

- all unit and integration tests pass;
- compile check passes;
- demo produces JSON, Markdown, and HTML;
- deterministic replay reproduces canonical report hash under `SOURCE_DATE_EPOCH`;
- package contains no generated reports, secrets, or private data;
- Windows PowerShell parser and installation gates pass before public release;
- no Critical or unresolved Serious finding remains.
