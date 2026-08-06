"""Dependency-free paired statistics."""

from __future__ import annotations

from decimal import Decimal, localcontext
from math import comb
import random
from typing import Iterable


def exact_mcnemar_two_sided(
    pass_to_fail: int, fail_to_pass: int
) -> tuple[float | None, str | None]:
    """Return the standard exact two-sided McNemar binomial p-value."""

    if pass_to_fail < 0 or fail_to_pass < 0:
        raise ValueError("Transition counts cannot be negative.")
    discordant = pass_to_fail + fail_to_pass
    if discordant == 0:
        return None, None
    lower = min(pass_to_fail, fail_to_pass)
    with localcontext() as context:
        context.prec = 80
        numerator = sum(Decimal(comb(discordant, k)) for k in range(lower + 1))
        denominator = Decimal(2) ** discordant
        value = min(Decimal(1), (Decimal(2) * numerator) / denominator)
    return float(value), "exact two-sided binomial"


def paired_bootstrap_delta_ci(
    before: Iterable[bool],
    after: Iterable[bool],
    *,
    replicates: int = 2000,
    seed: int = 20260805,
    confidence: float = 0.95,
) -> tuple[float | None, float | None]:
    """Deterministic percentile bootstrap interval for paired rate change."""

    before_values = list(before)
    after_values = list(after)
    if len(before_values) != len(after_values):
        raise ValueError("Paired samples must have equal length.")
    size = len(before_values)
    if size == 0:
        return None, None
    if replicates < 100:
        raise ValueError("Bootstrap replicates must be at least 100.")
    if not 0.0 < confidence < 1.0:
        raise ValueError("Confidence must lie strictly between zero and one.")

    differences = [
        int(after_value) - int(before_value)
        for before_value, after_value in zip(before_values, after_values, strict=True)
    ]
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(replicates):
        total = 0
        for _ in range(size):
            total += differences[rng.randrange(size)]
        samples.append(total / size)
    samples.sort()
    alpha = (1.0 - confidence) / 2.0
    low_index = max(0, min(replicates - 1, int(alpha * replicates)))
    high_index = max(
        0,
        min(replicates - 1, int((1.0 - alpha) * replicates) - 1),
    )
    return samples[low_index], samples[high_index]
