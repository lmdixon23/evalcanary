# ReplayDocket name and installation migration

ReplayDocket is the public name beginning with v0.2; earlier v0.1.0/v0.1.1
releases were published as EvalCanary. The descriptor is **Local evidence for
evaluator migrations**. The current source prepares the 0.2.0 candidate.
The citation release date remains unset until publication is authorized.
No ReplayDocket release or package publication is implied by this source change.

## Stable interfaces

| Surface | Supported identity |
|---|---|
| Python distribution | replaydocket |
| Preferred command | replaydocket |
| Compatibility command | evalcanary (supported, not deprecated for v0.2) |
| Python import | evalcanary |
| Assurance import | evalcanary.assurance |
| Module invocation | python -m evalcanary |
| Repository / Action address | lmdixon23/EvalCanary |

Both command names invoke the same maintained implementation. Help and version
output use ReplayDocket. Existing environment variables retain EVALCANARY_*.
Schema IDs, URNs, report IDs, schema versions, extension keys, provenance and
normative generator names remain unchanged. Existing report, queue, input,
contract and default output filenames remain unchanged.

Canonical JSON may therefore still contain EvalCanary or evalcanary, including
legacy provenance, schema titles and recorded command identities. These are
stable machine contracts, not evidence of a different installed product.
Human-facing report headings use ReplayDocket.

The repository remains at https://github.com/lmdixon23/EvalCanary.
Historical Action references and v0.1.0/v0.1.1 tags, release names, assets and
checksums remain unchanged. Updating source action metadata does not publish a
Marketplace update.

## Installation

The old evalcanary distribution and the new replaydocket distribution install
the same evalcanary import files. Side-by-side installation is **not supported**:
uninstalling either could remove shared files.

Prefer a fresh environment and an explicitly supplied, verified candidate or release wheel:

    python -m venv .venv
    .venv/bin/python -m pip install --no-deps /path/to/replaydocket-VERSION-py3-none-any.whl

On Windows, use .venv\Scripts\python.exe. Replace VERSION and the path with
the actual supplied artifact; the example is not a claim that a package is
currently available from an index.

To replace an existing installation in the same environment:

    python -m pip uninstall evalcanary
    python -m pip install --no-deps /path/to/replaydocket-VERSION-py3-none-any.whl
    python -c "import evalcanary; import evalcanary.assurance"
    replaydocket --version
    evalcanary --version
    python -m evalcanary --version

Keep application dependency declarations consistent: replace the distribution
requirement evalcanary with replaydocket when adopting the new distribution,
while retaining Python imports. Do not uninstall the compatibility CLI:
it is installed by replaydocket.

For offline source use, scripts/bootstrap_local.py creates both launchers and
a source-path link without contacting a package index. It is a development
bootstrap, not distribution installation.

## Workflow boundary

For migrate: compare frozen evaluator outputs across versions and produce
deterministic, reviewable evidence without rerunning the evaluator.
The legacy diff workflow executes trusted verifier code. Neither workflow
automatically certifies evaluator correctness.

## Historical imagery

The tracked files docs/assets/evalcanary-demo-report.png,
docs/assets/evalcanary-demo-mobile.png and docs/assets/evalcanary-featured-card.png
are EvalCanary v0.1 imagery. They are not current ReplayDocket promotional assets.
New ReplayDocket assets use separate replaydocket-* filenames. See
[asset provenance](assets/README.md) for candidate screenshot identity and
capture instructions. The original images remain unchanged.
