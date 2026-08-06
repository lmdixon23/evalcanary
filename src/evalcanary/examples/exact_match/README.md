# Exact-match migration example

The baseline verifier requires byte-for-byte equality. The candidate verifier
strips surrounding whitespace and uses Unicode-aware case folding. The fixed
corpus exposes five fail-to-pass transitions while preserving one genuine
failure.

Run:

```console
evalcanary diff --data cases.jsonl --before verifier_before.py --after verifier_after.py --policy evalcanary.toml --slice metadata.domain --out report
```
