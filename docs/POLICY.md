# Migration policy

Policies are TOML files with one `[policy]` table.

```toml
[policy]
min_cases = 100
max_error_cases = 0
max_abs_score_delta = 0.005
max_pass_to_fail = 10
max_fail_to_pass = 10
max_changed_cases = 15
require_statistical_review_below_p = 0.05
```

## Semantics

- `min_cases`: minimum fixed-corpus size.
- `max_error_cases`: maximum cases with an error in either verifier.
- `max_abs_score_delta`: maximum absolute pass-rate change.
- `max_pass_to_fail`: maximum regressions under the candidate.
- `max_fail_to_pass`: maximum newly accepted cases.
- `max_changed_cases`: maximum total discordant verdicts.
- `require_statistical_review_below_p`: fail when the exact McNemar p-value is below the threshold, requiring review of a statistically detectable shift.

Policies are project decisions, not universal safety thresholds. A policy pass does not establish evaluator validity.

## Exit codes

- `0`: completed; no policy or policy passed.
- `2`: completed; policy failed.
- `3`: input, execution, or configuration error.
