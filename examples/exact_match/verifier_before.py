"""Strict exact-match baseline verifier."""


def verify(case: dict) -> dict:
    passed = case["output"] == case["expected"]
    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "strict exact match" if passed else "output differs exactly",
    }
