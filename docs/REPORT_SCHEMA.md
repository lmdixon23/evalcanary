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

## Privacy

Case payloads in `changed_cases` are null unless the user explicitly runs with `--include-content`. Verifier source is replaced by an omission notice unless `--include-source-diff` is supplied. Reasons, details, file paths, and explicitly included source diffs can still contain sensitive information.
