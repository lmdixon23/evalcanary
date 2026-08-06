# Roadmap

## 0.1: EvalCanary Diff

- fixed JSONL corpus;
- trusted Python verifier before and after;
- pass/fail transition analysis;
- paired statistics;
- slices;
- policy gates;
- provenance;
- JSON, Markdown, HTML;
- local CLI and GitHub Action.

## 0.2: Integration evidence

Only after external requests:

- generic result-import adapter;
- one Inspect adapter;
- one Promptfoo adapter;
- artifact-schema conformance tests;
- critical-subset policies.

## 0.3: Judge reliability

Only after a concrete judge-backed case study:

- repeated trials;
- judge stability intervals;
- inter-judge agreement;
- prompt and model identity tracking;
- cost and rate-limit controls.

## 0.4: Invariance testing

- deterministic perturbation interface;
- user-defined transformations;
- formatting and structured-output invariance;
- perturbation provenance;
- false-equivalence safeguards.

## 0.5: Local evaluation ledger

- comparison history;
- schema migrations;
- local report browser;
- signed or attestable manifests;
- no hosted account requirement.

## 1.0 gate

- stable public schemas;
- external benchmark adoption;
- at least two independently maintained adapters;
- documented threat model and security review;
- sustained Windows, Linux, and macOS compatibility;
- evidence that the product adds value beyond existing evaluation runners.
