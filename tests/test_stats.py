"""Fisher exact against hand-checked reference values (ROADMAP §1.4).

These numbers are the verdict's spine: if the p-value drifts, thresholds that were
calibrated against the fixtures silently stop meaning what they meant.
"""

from __future__ import annotations

import pytest

from mcp_audit.stats import fisher_exact, holm

# (real hits, real misses, san hits, san misses, expected two-sided p)
TABLE = [
    (5, 0, 0, 5, 0.0079),
    (4, 1, 0, 5, 0.048),
    (5, 0, 1, 4, 0.048),
    (3, 2, 0, 5, 0.167),
    (4, 1, 1, 4, 0.206),
    (6, 4, 0, 10, 0.011),
    (7, 3, 2, 8, 0.070),
]


@pytest.mark.parametrize("a,b,c,d,expected", TABLE)
def test_reference_values(a, b, c, d, expected):
    assert fisher_exact(a, b, c, d) == pytest.approx(expected, abs=0.001)


def test_symmetry_and_degenerate_tables():
    assert fisher_exact(0, 5, 5, 0) == pytest.approx(0.0079, abs=0.001)  # steered away
    assert fisher_exact(5, 0, 5, 0) == 1.0  # identical arms
    assert fisher_exact(0, 5, 0, 5) == 1.0
    assert fisher_exact(0, 0, 0, 0) == 1.0
    assert fisher_exact(3, 2, 3, 2) == pytest.approx(1.0)


def test_p_is_never_above_one():
    for a in range(6):
        for c in range(6):
            assert 0.0 <= fisher_exact(a, 5 - a, c, 5 - c) <= 1.0


def test_holm_is_ordered_monotone_and_order_preserving():
    assert holm([0.01, 0.04, 0.2]) == pytest.approx([0.03, 0.08, 0.2])
    # input order is preserved, not sorted order
    assert holm([0.2, 0.01]) == pytest.approx([0.2, 0.02])
    # monotone: an adjusted p never drops below the one before it
    out = holm([0.001, 0.02, 0.03, 0.9])
    assert out == sorted(out)
    assert holm([]) == []
    assert holm([0.5]) == [0.5]


def test_holm_is_less_blunt_than_bonferroni():
    """The whole reason we use Holm: a real finding on a big server still lands."""
    ps = [0.001] + [0.9] * 39
    assert holm(ps)[0] < 0.05
