# Roadmap

## Shipped history: EvalCanary 0.1

Fixed-corpus trusted Python verifier replay, pass/fail transitions, paired
statistics, slices, policy gates, provenance, local reports, and the composite
GitHub Action remain supported. See the historical changelog for released scope.

## Current release: ReplayDocket 0.2

ReplayDocket 0.2 adds offline frozen-judgment assurance: categorical and
numeric transitions, repeated evidence, explicit invariance relations and
anchors, strict comparability, human-authored contracts, canonical reports and
review queues, schemas, preflight, producer/scaffold authoring, and contract
coverage review.

Product features are frozen for the 0.2 release. Declared relations and repeated
trials are analyzed from supplied data; ReplayDocket does not generate
perturbations or rerun models.

## Demand-gated future work

These are deferred possibilities, not scheduled versions or current features:

- adapters for Inspect, Promptfoo or other producers after concrete demand;
- judge sampling, stability studies, provider/cost controls after a case study;
- perturbation execution with explicit false-equivalence safeguards;
- local comparison history, waivers, report browsing and attestable manifests.

Hosted storage, automatic correctness certification and a general benchmark
runner are outside the present product boundary.

## Requirements before a stable 1.0

- stable public schemas and explicit compatibility policy;
- external adoption and independently maintained integrations;
- a maintained threat model and security review;
- sustained Windows, Linux and macOS verification;
- evidence of useful migration review beyond existing evaluation runners.
