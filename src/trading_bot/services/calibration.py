"""Probability calibration from realized outcomes (dependency-free).

A raw model score or a 0-100 confidence index is NOT a probability of profit.
Feeding an uncalibrated score into Kelly sizing or a probability-threshold gate
is a category error. This module fits a monotone, binned reliability calibrator
from realized (score, outcome) pairs and maps a raw score to a calibrated
win-rate — no sklearn required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class CalibrationBin:
    lo: float
    hi: float
    calibrated_prob: float
    count: int


@dataclass(frozen=True)
class BinnedCalibrator:
    bins: tuple[CalibrationBin, ...]
    base_rate: float
    sample_size: int

    def predict(self, score: float) -> float:
        """Map a raw score to a calibrated probability in [0, 1]."""
        if not self.bins:
            return self.base_rate
        value = float(score)
        for b in self.bins:
            if b.lo <= value <= b.hi:
                return b.calibrated_prob
        # Outside the fitted range: clamp to the nearest edge bin.
        if value < self.bins[0].lo:
            return self.bins[0].calibrated_prob
        return self.bins[-1].calibrated_prob


def fit_binned_calibration(
    scores: Sequence[float],
    outcomes: Sequence[int],
    *,
    n_bins: int = 10,
) -> BinnedCalibrator:
    """Fit an equal-count (quantile) binned reliability calibrator.

    ``outcomes`` are 1 (win) / 0 (loss). Each bin's calibrated probability is the
    realized win rate of its members, enforced monotone non-decreasing in score
    via pool-adjacent-violators so the mapping is well-behaved.
    """
    # Treat only strictly positive outcomes as wins. Callers should pass binarized
    # 0/1, but guard defensively so a stray multi-class label (e.g. a -1 stop-out
    # from triple_barrier/trend_scan) is never miscounted as a win.
    pairs = [
        (float(s), 1 if int(o) > 0 else 0)
        for s, o in zip(scores, outcomes)
        if s is not None and o is not None
    ]
    n = len(pairs)
    base_rate = sum(o for _, o in pairs) / n if n else 0.0
    if n < 2:
        return BinnedCalibrator(bins=(), base_rate=base_rate, sample_size=n)

    pairs.sort(key=lambda p: p[0])
    n_bins = max(1, min(n_bins, n))
    raw_bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for idx, pair in enumerate(pairs):
        raw_bins[min(n_bins - 1, idx * n_bins // n)].append(pair)

    # Per-bin win rate.
    stats = []
    for members in raw_bins:
        if not members:
            continue
        lo = members[0][0]
        hi = members[-1][0]
        prob = sum(o for _, o in members) / len(members)
        stats.append([lo, hi, prob, len(members)])

    # Pool-adjacent-violators: enforce monotone non-decreasing prob.
    i = 0
    while i < len(stats) - 1:
        if stats[i][2] > stats[i + 1][2]:
            total = stats[i][3] + stats[i + 1][3]
            merged_prob = (stats[i][2] * stats[i][3] + stats[i + 1][2] * stats[i + 1][3]) / total
            stats[i] = [stats[i][0], stats[i + 1][1], merged_prob, total]
            del stats[i + 1]
            if i > 0:
                i -= 1
        else:
            i += 1

    bins = tuple(
        CalibrationBin(lo=lo, hi=hi, calibrated_prob=round(prob, 6), count=count)
        for lo, hi, prob, count in stats
    )
    return BinnedCalibrator(bins=bins, base_rate=base_rate, sample_size=n)
