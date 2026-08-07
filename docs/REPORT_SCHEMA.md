# Report schema v1

The canonical artifact is `report.json` with schema identifier `evalcanary-comparison-v1`.

## Stability

During the v0.x series:

- existing fields will not silently change meaning;
- additive fields may appear;
- breaking changes require a new schema identifier;
- human-readable reports are derived views and are not canonical APIs.

## Core fields

- `schema_version`
- `tool_version`
- `run_id`
- `created_at`
- `total_cases`
- `comparable_cases`
- `error_cases`
- `transition_counts`
- `rates`
- `paired_bootstrap_ci`
- `mcnemar`
- `changed_cases`
- `slices`
- `policy`
- `provenance`
- `verifier_diff`
- `limitations`

## Run identity and provenance

`run_id` is the first 16 hexadecimal characters of a SHA-256 digest over the
three content identities: the fixed corpus, the before verifier, and the after
verifier. Changing any one of those artifacts changes the run ID.

Report provenance retains SHA-256 identities and runtime information. File and
command path values use basenames only by default, so a shared report does not
expose local parent directories or user-profile paths.

With fixed inputs, one runtime, and `SOURCE_DATE_EPOCH`, canonical JSON reports
must reproduce across fresh output directories. Runtime provenance is retained,
so byte-for-byte report equality is not promised across different Python or
operating-system runtimes.

## Privacy

Case payloads in `changed_cases` are null unless the user explicitly runs with
`--include-content`. Verifier source is replaced by an omission notice unless
`--include-source-diff` is supplied. Reasons, details, basenames, and explicitly
included source diffs can still contain sensitive information.
