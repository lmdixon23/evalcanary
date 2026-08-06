"""Whitespace- and case-normalized candidate verifier."""


def verify(case: dict) -> dict:
    observed = str(case["output"]).strip().casefold()
    expected = str(case["expected"]).strip().casefold()
    passed = observed == expected
    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "normalized exact match" if passed else "normalized output differs",
        "details": {"observed": observed, "expected": expected},
    }
