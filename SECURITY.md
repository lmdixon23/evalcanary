# Security policy

## Supported versions

Security fixes target the latest release on the default branch during the v0.x series.

## Critical boundary

ReplayDocket's legacy `diff` workflow executes user-supplied Python verifier files. The child process reduces accidental state coupling, but it is not a security sandbox. A verifier can read files, access the network, consume resources, or execute operating-system commands with the current user's permissions.

The data-only `migrate` workflow consumes frozen outputs and does not execute
the evaluator or make network requests during report generation.

Run only verifier code you trust. Use a container, virtual machine, or restricted operating-system account for untrusted code.

## Sensitive reports

Evaluation cases, reasons, and reports may contain proprietary prompts, model outputs, personal data, or security-sensitive behavior. Original case payloads are excluded unless `--include-content` is supplied. Verifier source is excluded unless `--include-source-diff` is supplied. These defaults do not make reports automatically safe: reasons, details, paths, and deliberately included content may still disclose sensitive information.

## Frozen assurance artifacts

`migrate` and `contract-review` parse data only. They validate strict schemas,
cross-record identities, explicit context comparability, and configured resource
limits without importing evaluator code or fetching remote resources. They do
not verify the truth of caller-supplied fingerprints or the sufficiency of a
contract. Preflight success is authoring validation, not policy approval.

Assurance reports omit original payloads and private annotations. Identifiers,
declared component names, labels, contract rationales, group metadata and
provenance still reach the report audience; use safe public values when sharing.
HTML escapes supplied text, contains no script, and requires no remote assets.
Review the canonical JSON and both review queues as well as the HTML before
publishing a packet.

Write into a private output directory. The five-file bundle includes bounded
recovery checks for interrupted writes, but it is not a transaction against
another process with the same account privileges. Limits bound accepted
evidence; they do not turn the program into an untrusted-code sandbox.
See the [assurance reference](docs/EVALUATOR_ASSURANCE.md) for exact boundaries.

## Reporting a vulnerability

Do not open a public issue for a vulnerability or accidentally exposed evaluation data. Contact the maintainer privately through the security-reporting mechanism available on the GitHub repository.

Include:

- affected version and platform;
- minimal reproduction using synthetic data;
- security impact;
- whether public disclosure has occurred;
- proposed mitigation, when known.
