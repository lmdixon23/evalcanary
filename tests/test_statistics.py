from __future__ import annotations

import unittest

from evalcanary.statistics import exact_mcnemar_two_sided, paired_bootstrap_delta_ci


class StatisticsTests(unittest.TestCase):
    def test_exact_mcnemar_symmetric(self) -> None:
        p_value, method = exact_mcnemar_two_sided(2, 2)
        self.assertEqual(p_value, 1.0)
        self.assertEqual(method, "exact two-sided binomial")

    def test_exact_mcnemar_one_sided_extreme(self) -> None:
        p_value, _ = exact_mcnemar_two_sided(5, 0)
        self.assertAlmostEqual(p_value or 0.0, 0.0625)

    def test_no_discordance_returns_none(self) -> None:
        self.assertEqual(exact_mcnemar_two_sided(0, 0), (None, None))

    def test_bootstrap_is_reproducible(self) -> None:
        before = [True, False, False, True]
        after = [True, True, False, True]
        first = paired_bootstrap_delta_ci(before, after, replicates=500, seed=7)
        second = paired_bootstrap_delta_ci(before, after, replicates=500, seed=7)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
