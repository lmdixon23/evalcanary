# ReplayDocket presentation assets

The ReplayDocket PNGs are new assets. The three `evalcanary-*.png` files remain
unchanged historical v0.1 imagery.

## Featured card

`replaydocket-featured-card.png` is generated brand artwork, not a software
screenshot. It uses the exact ReplayDocket wordmark and descriptor, paired
evidence sheets and neutral transition paths. Built-in image generation was
used; no historical image was edited.

## Candidate report captures

`replaydocket-demo-report.png` (1440 x 1100) and
`replaydocket-demo-mobile.png` (430 x 1100) are genuine browser viewport
captures of the same unmodified `demo` HTML report from version 0.2.0.
They show trusted synthetic verifier replay, not data-only assurance.

The capture uses CPython 3.13.9 on Windows 11, Chrome Headless Shell
153.0.8010.52, and agent-browser 0.38.1. The reproducible report timestamp is
`2026-09-19T20:00:00Z` (`SOURCE_DATE_EPOCH=1789848000`); it is not a
publication date. Canonical provenance retains tool `EvalCanary` with
`tool_version: 0.2.0` by design.

Generate from a fresh candidate environment and fresh destination:

```powershell
$env:SOURCE_DATE_EPOCH = '1789848000'
replaydocket demo --out capture-demo
```

Open `capture-demo/report/report.html` in an isolated headless browser, set
each viewport above, and capture the top of the page without DOM/CSS changes,
cropping, relabeling, or image generation. Close the browser afterwards.

Captured report identity on the recorded runtime:

- report.json SHA-256: `d87c2e6ee5d1bd3887267c0a056c70921d6b174906aebe06be06dd1ed0995ad5`
- report.html SHA-256: `f14b8ee23607a85ab8f9865cb956692ab77a511443bc166394c1937432bba7ed`

- report.md SHA-256: `02824ad822aa20e976b29c91fbfb2326f1bf1492a4fb87a479a5b8a276aa5cdf`

Other runtimes can change recorded runtime provenance. Recapture and update
this record when report bytes change. Candidate screenshots are not evidence
that hosted CI or publication has completed.
