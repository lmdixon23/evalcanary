# Evaluator-assurance development reference

The `evalcanary migrate` command analyzes two sets of already-produced
judgments over one frozen corpus. It is data-only: the command does not import,
execute, or call an evaluator, model, benchmark, patch, container, or provider.
The core uses the Python standard library and makes no network request.

This development interface is deliberately narrow. It produces evidence for a
reviewer; it does not decide that an evaluator is correct, fair, safe, unbiased,
certified, or causally responsible for an observed change.

## Command

```console
evalcanary migrate \
  --input evaluator-assurance.jsonl \
  [--contract evaluator-contract.json] \
  [--limits local-limits.json] \
  --out evaluator-assurance-report
```

The output directory contains `report.json`, `report.md`, `report.html`,
`review-queue.json`, and `review-queue.md`. The queue is a pure derivative of
the canonical report and does not change report or contract status. Legacy
`diff` output remains the historical three-report bundle. The report JSON is the
exhaustive deterministic UTF-8 record without a BOM. Markdown and HTML are
bounded decision-review projections: they identify the JSON by SHA-256, report
what detail was displayed or omitted, and retain complete contract decisions
without embedding the full JSON. HTML is self-contained, accessible, escaped,
and scriptless.

Exit statuses are:

- `0`: evidence passed its contract, or no contract was configured;
- `2`: a hard contract rule failed;
- `3`: invalid input/configuration, non-comparable evidence, or safe execution
  failure;
- `4`: system or contract review is required.

Authoring preflight validates without evaluating policy or writing a packet:

```console
evalcanary migrate --preflight --input evaluator-assurance.jsonl \
  [--contract evaluator-contract.json] [--limits local-limits.json]
```

Its only exits are `0` (valid enough to execute `migrate`) and `3` (invalid or
preflight failure). A valid contract that would later hard-fail or require
review still passes preflight.

## Structural schemas and runtime semantics

The four bundled Draft 2020-12 schemas are available offline with stable URN
identifiers:

```console
evalcanary schema input-record
evalcanary schema contract
evalcanary schema report
evalcanary schema review-queue
```

`STRUCTURAL_SCHEMA` validates one JSON value's fields, types, enums, and
structurally expressible combinations. `RUNTIME_SEMANTICS` remains normative
for JSONL ordering, byte/numeric limits, duplicate keys, manifest
recomputation, cross-record identities and references, pairing, ownership,
context comparability, contract evaluation, and whole-artifact resource facts.
The schemas neither replace the runtime validators nor use network resolution.
A shared registry generates their canonical bytes, and release checks fail on
checked-in byte drift.

## Inert scaffold and producer

Start an authoring directory without choosing migration policy:

```console
evalcanary init --judgment categorical --label pass --label fail --out assurance-start
```

Numeric and `categorical_and_numeric` judgment choices are also supported. The
scaffold is intentionally inert: mapping code stops at explicit TODOs for
status mapping, parser/aggregation ownership, pairing, invariance, context
exceptions, anchor interpretation, and contract policy. It emits no contract.

`evalcanary.assurance.producer` provides `AssurancePacket`, `Evaluation`,
`component_value`, `sha256_bytes`, and `sha256_value`. Fingerprints are required
inputs to `Evaluation`; the two hash helpers act only on exact values passed by
the caller. The producer never derives identity from names, files, imports,
objects, environments, package metadata, or time. Finalization orders records,
fills only explicitly confirmed `not_applicable` inventory slots, computes the
manifest, runs the normative runtime validator, and only then atomically writes
the final JSONL artifact.

## Input schema

`evaluator-assurance-input-v1` is strict UTF-8 JSONL. The first and only header
must be followed by records from the closed set `critical_group`,
`invariance_group`, `anchor_set`, `case`, `trial`, and `anchor`. Unknown core
fields and record types fail closed; extension data belongs under a bounded
`extensions` object.

One artifact has exactly two evaluations—`baseline` and `candidate`—one shared
corpus manifest, and one judgment specification. Cases are common to both
roles. A case without evidence for either role is `NOT_COMPARABLE`; source order
never creates an implicit trial pairing.

Judgment status is separate from label and score:

- `determinate` carries a declared categorical label when the judgment kind is
  categorical;
- `abstain`, `indeterminate`, and `error` carry a null label;
- `error` trials carry an enum-like error class; and
- scores use exact bounded decimals and are valid only for statuses declared by
  the shared score specification.

Numeric tokens are parsed directly into `decimal.Decimal`. Identity JSON emits
one ordinary, unquoted decimal form: negative zero becomes `0`, redundant zeros
are removed, and exponents are expanded. Binary floating-point values are not
accepted in canonical report construction.

Every evaluation supplies the complete locked evaluator/context component
inventory. The header explicitly owns `parser` and `aggregation_policy` on one
side of that boundary. Equal present context values establish isolation only
relative to the supplied inventory. Exact, human-reviewed context exceptions
produce `NOT_ISOLATED` and exit 4; unmatched drift is `NOT_COMPARABLE`.

The locked anchor record field list has no error object even though it delegates
to the shared status rules, under which `error` requires that object. The v1
implementation therefore rejects `status=error` anchors rather than silently
inventing a field or weakening error semantics. Non-error anchors remain fully
supported.

## Invariance, repeats, anchors, and provenance

Declared invariance relations are exactly `same_label`,
`swapped_preference`, and `same_score_within_tolerance`. Results are
`satisfied`, `violated`, or `not_evaluable`. Multiple trials form relation
instances only through a common, complete non-null pairing key.

Repeat diagnostics keep status, determinate label, and score instability
separate. They are descriptive and carry no independence, population,
confidence, significance, ranking, or causal claim.

Human annotations are optional raw anchors, not universal ground truth.
Coverage, compatible exact-label confusion, case counts, annotation counts, and
clusters remain explicit. Raw annotations remain present when an aggregate is
declared.

Provenance fields use explicit `present`, `missing`, `intentionally_omitted`, or
`not_applicable` values. Field deltas are `same`, `changed`, `missing_before`,
`missing_after`, `missing_both`, or `omitted`; absent evidence is never displayed
as equality.

## Contract schema

`evaluator-assurance-contract-v1` has ordered rules with a unique ID, severity,
scope, metric, operator, threshold, exact parameters, missing-evidence policy,
rationale, and extensions. Its closed metrics are:

- `corpus_equal`, `context_isolated`;
- `determinate_coverage`, `determinate_coverage_delta`;
- `status_count`, `new_status_count`;
- `determinate_label_count`, `determinate_label_transition_count`;
- `critical_regression_count`, `unstable_case_count`;
- `invariance_violation_count`, `invariance_not_evaluable_count`;
- `anchor_coverage`, `anchor_disagreement_count`;
- `provenance_present`; and
- `score_delta`.

Scopes and parameters are fixed per metric. Pair-dependent rules fail as
missing when pairing is incomplete. Optional-feature mismatches return
`not_applicable`; unknown scopes, parameters, labels, operators, and threshold
domains are invalid configuration. Exact rational comparisons avoid binary
floating point.

## Privacy, links, and output safety

Default reports omit prompts, responses, traces, media, provider payloads,
reason text, detail objects, error messages, extension contents, identifying
annotator data, absolute paths, and command lines. Presence and deterministic
hash facts distinguish omission from absence. Only schema-typed public source
and license HTTP(S) DNS URLs can become links; credentials, ports, IP/local
hosts, queries, fragments, controls, whitespace, backslashes, and dangerous
percent escapes are rejected without dereference.

Input, structure, string, numeric, group, anchor, trial, depth, extension, and
report sizes are bounded. A local limits document may change only named limits
within their absolute ceilings. Fixed source-text fields, including trial
reasons and error messages, retain their fixed ceilings even when general
string limits are raised. Every renderer and output size is checked before an
existing report is replaced. Source/output aliases, symbolic links, and Windows
reparse points fail closed. Existing path components are inspected without
following links; the destination topology is revalidated around exclusive
temporary-file creation and each atomic replacement. Temporary siblings are
flushed and synchronized; if later publication fails, already-published files
are removed and the prior bundle is restored before temporary siblings are
cleaned.

These checks narrow but cannot eliminate a same-privilege filesystem race:
another process with permission to replace directory entries can act between a
successful validation and the following operating-system call. Run assurance
output in a directory whose parents are not writable by untrusted principals.

## Deferred boundaries

This interface is not an untrusted-code sandbox, hosted service, benchmark
runner, Inspect adapter, CJE exporter, fresh judge sampler, perturbation
generator, or statistical inference engine. Benchmark-specific fixture
preparation stays outside the generic product core and must independently pin
licenses, revisions, byte hashes, decoder identity, row lineage, and prohibited
operations.
