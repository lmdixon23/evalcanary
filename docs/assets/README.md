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

The capture uses CPython 3.13.9 on Windows 11, Microsoft Edge, and
agent-browser 0.38.1. The reproducible report timestamp is
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

- report.json SHA-256: `69c9966d14682dc2e2eeeafd40a7cfe87302b751e016a97efc80ea9d1cdfcb5f`
- report.html SHA-256: `9116892f11325a8f32000b08248504716341e9908b6075df4fac2f0b763e17c1`

Other runtimes can change recorded runtime provenance. Recapture and update
this record when report bytes change. Candidate screenshots are not evidence
that hosted CI or publication has completed.
