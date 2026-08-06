# Security policy

## Supported versions

Security fixes target the latest release on the default branch during the v0.x series.

## Critical boundary

EvalCanary executes user-supplied Python verifier files. The child process reduces accidental state coupling, but it is not a security sandbox. A verifier can read files, access the network, consume resources, or execute operating-system commands with the current user's permissions.

Run only verifier code you trust. Use a container, virtual machine, or restricted operating-system account for untrusted code.

## Sensitive reports

Evaluation cases, reasons, and reports may contain proprietary prompts, model outputs, personal data, or security-sensitive behavior. Original case payloads are excluded unless `--include-content` is supplied. Verifier source is excluded unless `--include-source-diff` is supplied. These defaults do not make reports automatically safe: reasons, details, paths, and deliberately included content may still disclose sensitive information.

## Reporting a vulnerability

Do not open a public issue for a vulnerability or accidentally exposed evaluation data. Contact the maintainer privately through the security-reporting mechanism available on the GitHub repository.

Include:

- affected version and platform;
- minimal reproduction using synthetic data;
- security impact;
- whether public disclosure has occurred;
- proposed mitigation, when known.
