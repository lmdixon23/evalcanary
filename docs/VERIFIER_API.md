# Verifier API

## Public contract

A v0.1 verifier is a trusted Python file defining a synchronous function:

```python
def verify(case: dict) -> bool | dict:
    ...
```

The complete JSONL object is supplied as `case`.

## Boolean result

```python
def verify(case: dict) -> bool:
    return case["output"] == case["expected"]
```

A boolean is normalized to pass/fail and a score of 1.0 or 0.0.

## Dictionary result

```python
def verify(case: dict) -> dict:
    passed = case["output"].strip() == case["expected"]
    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "normalized exact match",
        "details": {"normalization": "strip"},
    }
```

Requirements:

- `passed` must be boolean;
- `score`, when present, must be a finite number;
- `reason`, when present, must be a string;
- `details` must be JSON-serializable.

Python-level writes through `sys.stdout` or `sys.stderr`, including ordinary
`print`, are captured so they cannot corrupt the worker JSONL protocol. Version
0.1 does not preserve those captured log streams in the comparison report.
Low-level file-descriptor writes and output from child processes remain outside
that control, so verifiers should not emit console output.

## Errors

An exception raised for one case becomes an error verdict. The comparison continues for other cases. Error cases are not assigned a pass/fail transition and are counted separately.

Module-import or worker startup failures terminate the run.

## Execution boundary

The worker process is not a sandbox. Verifiers have the current user's
operating-system permissions. Use only trusted code or execute EvalCanary inside
an external sandbox.

`--python` selects the interpreter used to execute the standard-library worker
file and verifier. The selected interpreter does not need EvalCanary installed,
but it must support Python 3.11 or later and contain the verifier's dependencies.

## Determinism guidance

For a migration comparison:

- pin dependencies;
- avoid network calls;
- fix random seeds;
- record model and prompt versions for judge-backed verifiers;
- ensure before and after receive the same case object;
- avoid changing external state between runs.
