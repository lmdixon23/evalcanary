"""Strict exact-match baseline verifier."""

from typing import Any


def verify(case: dict[str, Any]) -> dict[str, Any]:
    passed = case["output"] == case["expected"]
    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "strict exact match" if passed else "output differs exactly",
    }
