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

## Review queue projection

`review-queue.json` remains the exhaustive canonical derivative. Its
unreleased `evaluator-assurance-review-queue-v1` schema was amended before
public release to add `invariance_summary` and `workload_summary`, and to
replace the vague ordinary-change reason with neutral `STATUS_TRANSITION`.
No v2 was created because v1 has not been publicly released.

The Markdown projection separates candidate invariance violations, candidate
not-evaluable results, baseline violations, and baseline not-evaluable results.
Candidate violations appear before expected baseline policy exclusions.
Baseline not-evaluable facts with declared evidence-policy provenance are
labelled as expected policy exclusions and grouped rather than allowed to
dominate the worklist.

Ordinary baseline-to-candidate status changes use `STATUS_TRANSITION` with
the role, both statuses, case/trial identities, and report pointers. The
machine queue retains every row; Markdown groups repeated transitions by role
and status pair without describing them as better, worse, regressions, or
improvements.

Workload is reported both as queue items and unique logical review subjects.
A logical subject is normatively the exact `(subject_type, subject_id)` pair,
so multiple reason codes on the same pair are not presented as independent
human tasks. Separate deterministic counts cover implicated cases and primary
trial, invariance-group, rule, and anchor subjects.

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
scaffold is intentionally inert: typed unresolved markers cover evaluator,
context, component, corpus, case, trial, group, and anchor declarations. All
emitted records are built from those guarded declarations. Scaffold-specific
sentinel text, UTF-8 bytes, and the direct `sha256_bytes(token.encode("utf-8"))`
and `sha256_value(token)` digests are also blocked. Only registered scaffold
markers are recognized; unrelated strings and valid fingerprints remain allowed.
The guard traverses mapping keys/values and supported collections, including
public producer sequences, and checks judgment kind and label space.
This structural check does not establish real-world fingerprint provenance or
detect arbitrary transformations of marker data. Renaming marker text
does not resolve a marker. The guard establishes explicit structural completion,
not semantic truth or correctness, and the scaffold emits no contract.

The canonical public hash-helper import is:

```python
from evalcanary.assurance import sha256_bytes, sha256_value
```

`evalcanary.assurance` also exports `AssurancePacket`, `Evaluation`,
`ComponentInventories`, `Rule`, `Contract`, `component_requirements`,
`complete_components`, `complete_evaluation`, `make_evaluation`, and
`component_value`. Fingerprints remain explicit inputs; the hash helpers act
only on exact caller-supplied values.

### SEMANTIC DECISIONS

Before authoring, a maintainer must decide the status mapping, parser and
aggregation-policy ownership and identities, trial pairing, invariance
relations, allowed context differences, anchor interpretation, and every
contract rule. The producer never determines whether component identities
should change between evaluator versions. It does not generate an acceptance
policy or infer evaluator or policy identity.

### MECHANICAL REPRESENTATION

After those decisions are reviewed, the normal public authoring path is:

1. Represent the explicit semantic choices.
2. Create the baseline and candidate `Evaluation` values.
3. Create `AssurancePacket` with both evaluations.
4. Add normalized cases, trials, groups, and anchors. Every case supplies both
   `critical_group_ids` and `invariance_group_ids`; these are the supported
   case/group assignment mechanism. Every trial supplies `pairing_key`, `label`,
   `score`, and `error`, including explicit `None` when the reviewed choice is
   empty. Use the packet's read-only `evaluation_ids_by_role` property when the
   already-declared evaluation IDs are needed for trial rows.
5. Finalize the input with
   `input_path = packet.write(Path("evaluator-assurance.jsonl"))`.
6. Author explicit keyword-only `Rule` values and a `Contract`.
7. Write the contract with
   `contract.write(Path("evaluator-contract.json"), artifact=input_path)`.
8. Run `evalcanary migrate --preflight --input evaluator-assurance.jsonl
   --contract evaluator-contract.json`.
9. Run `evalcanary migrate --input evaluator-assurance.jsonl --contract
   evaluator-contract.json --out evaluator-assurance-report`.

The normal rule constructor is deliberately explicit and keyword-only:

```python
Rule(
    rule_id=rule_id,
    severity=severity,
    scope=scope,
    scope_id=scope_id,
    metric=metric,
    parameters=parameters,
    operator=operator,
    threshold=threshold,
    missing_evidence=missing_evidence,
    rationale=rationale,
)
```

Those names stand for reviewed user-supplied decisions; they are not product
defaults or a suggested policy. `Contract.write(..., artifact=...)` accepts
either an `AssuranceArtifact` already returned by `load_artifact` or a
`str`/`os.PathLike[str]` for a finalized evaluator-assurance JSONL input. A
path-like input is loaded through `load_artifact`; there is no second parser or
weaker validation path.

The complete locked component vocabulary is:

| Inventory | Required names |
| --- | --- |
| FIXED EVALUATOR COMPONENTS | `implementation`, `model_provider`, `rubric_prompt` |
| FIXED CONTEXT COMPONENTS | `container_image`, `dependency_lock`, `harness_configuration`, `locale_time`, `preprocessing`, `resource_policy`, `response_order`, `runner_adapter`, `runtime`, `sampling_settings`, `task_benchmark` |
| MOVABLE COMPONENTS | `aggregation_policy`, `parser` |

`parser` and `aggregation_policy` must each be assigned explicitly to
`evaluator` or `context`. `component_requirements(ownership)` returns the
deterministically ordered complete names for that exact declaration. It
inspects no environment and infers neither ownership nor presence.

`complete_components(..., confirm_unlisted_not_applicable=True)` is a bulk
semantic affirmation: every owned component not explicitly declared
`present`, `missing`, `intentionally_omitted`, or `not_applicable` is
affirmed not applicable. The default is false and fails clearly; explicit
component facts are retained and contradictions are rejected. The result feeds
`make_evaluation`, whose identity, role, ownership, component, and provenance
arguments remain explicit.

`complete_evaluation(...)` is the compact equivalent when component facts are
easier to maintain as one flat mapping. Fixed component ownership comes from
the locked vocabulary; movable ownership comes only from the required
`component_ownership` argument. The helper partitions those already-declared
facts mechanically and requires the same explicit bulk not-applicable
affirmation; it does not choose ownership, presence, identity, or provenance.

`Rule` requires keyword-only metric, scope, scope ID, parameters, severity,
operator, threshold, missing-evidence policy, and rationale. `Contract` fills
only the schema binding, empty extensions, stable rule ordering, and atomic
output; its `write(..., artifact=...)` path validates through the normative
artifact and contract loaders. `AssurancePacket.add_cases`, `add_trials`, and
`add_anchors` remove only loops over already-semantic normalized objects.

The exact case/group mechanism is:

```python
packet.add_case(
    "case-a",
    critical_group_ids=["release-blockers"],
    invariance_group_ids=["paraphrase-pair"],
)
```

Declare `release-blockers` with `packet.add_critical_group(...)` and
`paraphrase-pair` with `packet.add_invariance_group(...)`. There is no
`assign_case_groups` API. For compact maintained mappings, prefer
`add_cases(...)` and `add_trials(...)` over repeated mechanical calls; each
mapping still names every required semantic field.

The producer never derives identity from names, files, imports, objects,
environments, package metadata, or time, and it never selects status mappings,
label polarity, pairing, ownership, invariance, context exceptions, or
acceptance policy. Finalization orders records, computes the manifest, runs the
normative runtime validator, and only then atomically writes the final JSONL
artifact.

The generated scaffold makes status and pairing causally explicit:
`STATUS_MAPPING(source)` must return exactly `status`, `label`, `score`, and
`error`, while `PAIRING_POLICY(source)` returns the exact pairing key or explicit
`None`. Their results become the emitted trial fields. Both initial functions
fail with `AUTHORING_INCOMPLETE`; they do not inspect external data or supply a
hard-coded semantic outcome. Setting `INVARIANCE_GROUPS = []` explicitly selects
no invariance relations. Setting both `ANCHOR_SETS = []` and `ANCHORS = []`
explicitly selects no human anchors; otherwise the exact supplied declarations
control output.

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

## Canonical invariance relation configuration

Report-v1 invariance-group objects permit additive fields (`object_array` has
object items with no closed property list). Existing fields keep their meanings;
no schema identifier, engine version, input domain, or producer API changes are
needed for the additive `relation_configuration` field.

Each group retains its exact validated relation semantics:

- `same_label`: `{}`.
- `same_score_within_tolerance`: `{"absolute_tolerance": <exact number>}`.
- `swapped_preference`: `first_label_index`, `second_label_index`, and
  `tie_label_index` address the ordered canonical `judgment_spec.label_space`.
  The tie index is null when omitted in the source declaration.

Indices come from exact lookup in the validated declaration's label space, never
from outcomes. The configuration contains only fixed keys, exact numbers,
bounded integers, and null. It duplicates no label strings and needs no redaction.
The already canonical label space and accepted label domain retain their existing
behavior. Configuration is a semantic representation, not raw source parameters.

`scripts/verify_assurance_relations.py INPUT REPORT` independently resolves these
references against validated source semantics. With `--before-report`,
`--before-queue`, and `--queue`, it checks that the sole semantic report change is
the added configuration, recomputes report/queue identities, resolves every queue
pointer, and requires unchanged queue facts, ordering, ranks, and dispositions.

## Reviewer numeric evidence

Numeric Markdown and HTML reports share one bounded projection from canonical
report facts. The paired-score table reuses the review queue's valid-pair
selection and shows both scores, statuses, candidate-minus-baseline delta, and
score completeness. Unavailable scores never become zero. The complete-pair
summary includes all valid pairs in its counts, but only score-complete pairs in
its exact sum and mean, with the denominator printed explicitly. This descriptive
subset summary does not replace a contract metric or its missing-evidence policy.

Numeric invariance rows resolve the already declared canonical member cases and
instances, show numeric member counts and exact observed spreads, and read the
absolute tolerance only from `relation_configuration`. Older reports without
that additive field show the tolerance as unavailable. Unresolved or insufficient
numeric instances are explicitly incomplete; the existing result is printed.
Repeated-score rows show total and numeric counts, minimum, maximum, range, the
existing repeat tolerance, and the existing canonical score-instability state.

Arithmetic uses exact fractions of canonical decimal numbers. Terminating values
use ordinary decimals without extra trailing zeros or negative zero; other means
retain exact rational form. A positive or negative delta implies no quality,
correctness, acceptance, severity, or regression judgment. No new pairing,
invariance, instability, label-polarity, or missing-evidence decision is made.

Paired-score and repeated-case-role detail each reuse the 25-row case-detail cap.
Numeric invariance detail reuses the per-role caps: 50 violated, 25 not evaluable,
and 10 satisfied. Each population declares total/displayed/omitted counts; sums
and means cover the complete population even when detail is omitted. Categorical
reports receive no numeric sections. HTML remains static and shares the same
facts and escaping boundaries as Markdown; rendering never reopens source input.

## Read-only contract review

```console
evalcanary contract-review --input evaluator-assurance.jsonl --contract evaluator-contract.json
```

This local/offline command writes one human-readable JSON review to stdout and
creates no files. It uses the normal loaders, then derives evidence availability
from the existing report engine. `--limits` accepts the existing bounded resource
configuration. Exit 0 means the review completed; it is not a contract PASS.
Invalid input/configuration returns 3 through the normal loader. Use
`migrate --preflight` for existing authoring diagnostics and `migrate` for policy
dispositions. This review does not change migration status, exit codes, reports,
queue items, severities or the five-member publication/recovery protocol.

Coverage denominators are explicit:

- All 16 supported locked metric names, counting each name at most once.
- Allowed metric/scope **types** from `METRIC_SIGNATURES`, crossed with baseline
  and candidate only for metrics with an explicit role parameter. Null means
  that the metric has no explicit role parameter. These rows do not enumerate
  scope IDs or all possible label, status or other parameter combinations.
- The eight registered role/trial-status combinations observed in this input.
  Only the exact `all_cases` `status_count` selector counts as corresponding
  coverage in this table; other metrics and subset selectors are not inferred
  to address it. Zero trials means not observed in this input.

Rule rows address the actual selections in the contract. Existing `missing`
results become `not evaluable`, `not_applicable` becomes `not applicable`, and
satisfied/violated results both have observed evidence. A rule with no result
because the contract was not evaluated has `unknown` availability. None of
these observations overrides its explicit missing-evidence policy.

Covered does not mean sufficient; not covered does not mean bad or a defect.
More rules do not mean better policy, all metrics covered does not establish
safety, and not evaluable does not mean failed. Not observed is limited to the
supplied evidence. Unknown and untested remain unknown and untested. There is
no coverage score, quality rating, recommended rule or automatic policy change.

`evaluator-assurance-contract-review-v1` binds the exact contract ID/version,
contract SHA-256, input SHA-256, tool/report schema identity and canonical report
identity/hash. Its RFC 6901 pointers address the exact contract: an empty pointer
means the root for an absence observation, while a covered aggregate points to
the first matching rule. Finding IDs hash the schema, exact contract hash and
canonical mechanical observation. No timestamps or source paths are included.
User-authored labels, rationales and extensions are not copied into the review.

Vocabulary rows sort lexically; rule details follow source array order. Every
collection reports total/displayed/omitted findings and uses the existing
100-diagnostic cap. Aggregate counts always include omitted rows. The existing
JSON output-byte limit is checked before stdout receives the payload. Review
projection is linear in rules and trials apart from fixed vocabulary sorting;
it reuses the existing report computation without changing its complexity.
No public Python API or mandatory dependency is added.
