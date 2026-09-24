"""Fisher exact and Holm correction, in the standard library.

Two reasons not to pull scipy in for this: a security CLI people install with
`uvx` should not drag 30 MB of numerical libraries behind it, and the tables here
are tiny (n <= 20 per arm), so `math.comb` is exact and instant.
"""

from __future__ import annotations

from math import comb


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for [[a, b], [c, d]].

    a = real-arm trials where the signal fired, b = real-arm trials where it did
    not, c/d the same on the sanitized arm. Two-sided means: sum the probability
    of every table with the same margins that is at least as extreme as this one.
    """
    n = a + b + c + d
    if n == 0:
        return 1.0
    row1, col1 = a + b, a + c
    total = comb(n, col1)
    if total == 0:
        return 1.0

    def prob(x: int) -> float:
        # hypergeometric: choose x of col1 from row1, the rest from row2
        return comb(row1, x) * comb(n - row1, col1 - x) / total

    observed = prob(a)
    lo = max(0, col1 - (n - row1))
    hi = min(row1, col1)
    # 1e-9 slack: the equally-extreme table on the other tail is only equal up to
    # float error, and dropping it would halve p on a symmetric table.
    p = sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= observed * (1 + 1e-9))
    return min(1.0, p)


def holm(ps: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values, returned in the input order.

    Bonferroni over every signal we test would be too blunt -- a server with 40
    tools would need p < 0.001 to ever confirm. Holm controls the same family-wise
    error rate with more power, and needs no independence assumption.
    """
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    out = [1.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * ps[i]))
        out[i] = running
    return out
