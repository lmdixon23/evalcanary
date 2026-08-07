# EvalCanary project design

## 1. Product definition

EvalCanary is a local-first reliability layer for AI evaluations. Version 0.1 compares two trusted evaluator implementations against one fixed corpus of already-generated outputs.

Primary proposition:

> See exactly what changes when your evaluator changes.

Long-term category:

> Evaluation reliability platform.

The project does not initially run models, generate benchmark responses, host results, or decide which evaluator is normatively correct.

## 2. Problem

Evaluation systems evolve through changes to code, answer extraction, normalization, thresholds, test suites, rubrics, judge prompts, judge models, aggregation, timeouts, and environments.

A simple before-and-after aggregate score cannot answer:

- which cases changed;
- whether opposite transitions cancelled in aggregate;
- whether changes concentrate in a subgroup;
- whether one verifier crashed or abstained;
- whether a policy threshold was crossed;
- whether the same artifacts can be reproduced later.

The fixed-corpus design holds outputs constant and changes the evaluator. This isolates evaluator sensitivity more directly than re-running a full stochastic model evaluation.

## 3. Users

### Primary

- benchmark maintainers;
- RLVR and post-training researchers;
- AI evaluation infrastructure engineers;
- agent benchmark teams;
- model-release and leaderboard teams.

### Secondary

- reproducibility reviewers;
- AI assurance researchers;
- automated-assessment engineers;
- organizations maintaining internal golden sets.

## 4. Jobs to be done

1. Before merging a verifier change, determine its sample-level and aggregate effects.
2. During a benchmark migration, preserve a reviewable record of what changed.
3. When a leaderboard moves, separate output changes from evaluator changes.
4. When an RLVR reward changes, inspect whether acceptance boundaries shifted.
5. In CI, fail explicitly when a configured evaluator-change threshold is exceeded.

## 5. Design principles

1. **Fixed corpus first.** Evaluation outputs are inputs, not regenerated inside v0.1.
2. **Evidence before attribution.** The tool reports transitions, reasons, source diffs, and provenance; it does not invent causality.
3. **Privacy by default.** Original case payloads are omitted unless explicitly requested.
4. **Local first.** No account, backend, telemetry, or network service is required.
5. **Dependency restraint.** The runtime uses the Python standard library only.
6. **Framework neutrality.** The core schema is independent of Promptfoo, Inspect, lm-eval, OpenAI Evals, or any one benchmark.
7. **Machine and human review.** JSON serves automation; Markdown and accessible HTML serve reviewers.
8. **Explicit uncertainty.** Statistical output is labeled by method and accompanied by limitations.
9. **Solo-maintainer feasibility.** Each expansion must have external demand and a bounded support surface.

## 6. Non-goals for v0.1

- execute untrusted verifier code safely;
- replace general evaluation frameworks;
- determine ground truth automatically;
- generate perturbations using an LLM;
- support distributed or hosted evaluation storage;
- compare stochastic judge reliability over repeated samples;
- infer protected attributes;
- publish a public leaderboard;
- claim legal, scientific, or benchmark validity.

## 7. Core workflow

```text
JSONL fixed corpus
        |
        +--> trusted verifier before --> normalized verdicts --+
        |                                                       |
        +--> trusted verifier after  --> normalized verdicts --+--> paired comparison
                                                                  |
                                                                  +--> transitions
                                                                  +--> statistics
                                                                  +--> slices
                                                                  +--> policy
                                                                  +--> provenance
                                                                  +--> JSON / Markdown / HTML
```

## 8. Architecture

### CLI

`evalcanary.cli` owns argument validation, exit codes, report destinations, and command composition.

### Input layer

`evalcanary.io` validates JSONL structure, unique identifiers, UTF-8 input, and deterministic hashes.

### Verifier runner

`evalcanary.runner` launches `evalcanary.worker` in a child process. The worker imports one trusted Python file and calls `verify(case)` for each case.

This boundary prevents accidental in-process global-state coupling. It does not constrain malicious code.

### Comparison engine

`evalcanary.compare` joins fixed cases with before and after verdicts, classifies transitions, calculates rates, extracts changed cases, and computes requested slices.

### Statistics

`evalcanary.statistics` supplies:

- exact two-sided McNemar binomial testing over discordant pairs;
- deterministic percentile bootstrap intervals for paired rate change.

### Policy

`evalcanary.policy` reads a standard-library TOML configuration and produces explicit pass/fail checks.

### Provenance

`evalcanary.provenance` records content-derived run identity, hashes, basename-only path labels, sanitized command structure, tool version, Python version, platform, report schema, and a bounded unified source diff.

### Reports

`evalcanary.reports` renders canonical JSON, pull-request-friendly Markdown, and a self-contained accessible HTML report.

## 9. Data contracts

### Case

Required:

- `id`: non-empty string or integer, unique in the file.

Optional fields are passed unchanged to the verifier. Recommended conventions:

- `input`;
- `output`;
- `expected`;
- `metadata`.

### Verdict

Required normalized field:

- `passed`: boolean, or null only when a case-level execution error occurs.

Optional:

- `score`;
- `reason`;
- `details`;
- `error`;
- `duration_ms`.

### Comparison

Stable top-level groups:

- identity and counts;
- transition counts;
- rates;
- paired statistics;
- changed cases;
- slices;
- policy;
- provenance;
- verifier source diff;
- limitations.

## 10. Statistical interpretation

The primary estimand is paired pass-rate change:

```text
delta = mean(after_pass - before_pass)
```

The McNemar test uses only discordant pass/fail pairs. A low p-value indicates asymmetric transition counts under the null of equal marginal pass probability. It does not establish evaluator correctness or practical importance.

The bootstrap interval resamples paired cases with replacement using a fixed seed. It estimates uncertainty over the supplied case sample. It does not account for dataset construction bias, hidden judge nondeterminism, model sampling variance, or benchmark leakage.

## 11. Product stages

### Stage 0: validation

- three real evaluator changes;
- five external maintainer interviews;
- one flagship migration report;
- clear evidence that ordinary unit tests do not supply the same decision packet.

### Stage 1: narrow excellent product

- generic JSONL;
- trusted Python verifiers;
- transition matrix;
- paired statistics;
- slices;
- provenance;
- policy gates;
- JSON, Markdown, HTML;
- GitHub Action.

### Stage 2: evaluator assurance suite

Demand-gated additions:

- repeated LLM-judge trials;
- inter-judge agreement;
- perturbation invariance;
- framework adapters;
- protected or critical subsets;
- richer migration policies.

### Stage 3: reliability platform

- evaluation-spec artifact;
- plugin SDK;
- replay and jury modules;
- signed or attestable provenance;
- local history and comparison viewer;
- optional organization service.

### Stage 4: institutional distribution

- major benchmark adoption;
- framework-native integration;
- standard migration-report schema;
- research citation and independent case studies.

## 12. Validation and expansion gates

### Continue Stage 1 only when

- five external maintainers confirm recurring evaluator-change pain;
- three real changes yield actionable reports;
- setup takes less than ten minutes for a generic Python verifier;
- users understand that changed does not mean wrong.

### Expand integrations only when

- ten external repositories use the CLI or Action;
- at least two independent adapter requests recur;
- support cost remains bounded;
- schema changes remain backward compatible or versioned.

### Add hosted features only when

- teams require shared history, access control, and organization policy;
- users accept a clear data-retention model;
- local reports remain fully supported;
- hosted operation has a sustainable maintenance or revenue path.

## 13. Kill conditions

Pause or redefine the product if:

- external maintainers do not regard evaluator migration as recurring;
- existing frameworks produce an equivalent review packet with minimal configuration;
- every integration requires benchmark-specific custom engineering;
- verifier execution cannot be bounded without adding a large sandboxing platform;
- reports create more false confidence than actionable review;
- maintenance exceeds one active solo-maintainer lane without external contribution.

## 14. Attention model

The repository is expected to begin as a technically credible niche tool. Attention should be evaluated by relevant users rather than raw stars.

Primary adoption indicators:

- external repositories integrating it;
- benchmark changes audited;
- material evaluator defects or undocumented shifts found;
- citations in migration records or papers;
- independent contributors and adapters;
- recognized benchmark or framework adoption.

A breakout outcome is distribution-dependent. Adding features alone is insufficient.

## 15. Branding

The working brand is EvalCanary. The metaphor supports early warning without restricting the project to graders, deterministic verifiers, or benchmarks.

Initial command:

```console
evalcanary diff
```

Possible later modules:

- `replay`;
- `jury`;
- `shake`;
- `gate`;
- `ledger`;
- `slice`;
- `migrate`.

The name remains provisional until package, domain, organization, and trademark checks are completed immediately before public release.
