"""Tests for purged walk-forward split (#13) and probability calibration (#12)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.services.calibration import fit_binned_calibration
from trading_bot.services.model_validation import (
    horizon_embargo_seconds,
    purged_time_split_indices,
)


# --- #13: purged walk-forward split ------------------------------------------

def _ts(minute: int) -> str:
    return f"2026-06-04T13:{minute:02d}:00+00:00"


def test_split_is_forward_in_time_regardless_of_row_order():
    # Rows supplied in DESC order; the test set must still be the LATEST by time.
    timestamps = [_ts(m) for m in [50, 40, 30, 20, 10, 0]]
    train_idx, test_idx = purged_time_split_indices(timestamps, test_fraction=0.34, embargo_seconds=0)
    # test = latest ~2 by time => minutes 50, 40 => original indices 0, 1
    assert set(test_idx) == {0, 1}
    # train indices are the earlier-by-time rows, none from the test set
    assert set(train_idx).isdisjoint(test_idx)


def test_embargo_drops_train_rows_near_test_boundary():
    timestamps = [_ts(m) for m in range(0, 60, 10)]  # 0..50 ascending
    # test_fraction 0.2 of 6 -> 1 test row (minute 50). embargo 1500s (25m)
    # drops train rows within 25 min before 13:50 -> minutes 30, 40 dropped.
    train_idx, test_idx = purged_time_split_indices(
        timestamps, test_fraction=0.2, embargo_seconds=25 * 60
    )
    assert test_idx == [5]  # minute 50
    train_minutes = sorted(i for i in train_idx)
    assert train_minutes == [0, 1, 2]  # minutes 0,10,20 ; 30,40 embargoed


def test_split_returns_empty_when_timestamps_unparseable():
    train_idx, test_idx = purged_time_split_indices(["x", None, ""], test_fraction=0.2)
    assert train_idx == [] and test_idx == []


def test_horizon_embargo_seconds():
    assert horizon_embargo_seconds("15m") == 900
    assert horizon_embargo_seconds("30m") == 1800
    assert horizon_embargo_seconds("unknown") == 900  # default


# --- #12: calibration --------------------------------------------------------

def test_calibration_maps_low_scores_to_low_probability():
    # Low scores mostly lose, high scores mostly win.
    scores = [0.1, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.9]
    outcomes = [0, 0, 0, 0, 1, 1, 1, 1]
    cal = fit_binned_calibration(scores, outcomes, n_bins=4)
    assert cal.predict(0.15) < cal.predict(0.85)
    assert 0.0 <= cal.predict(0.15) <= 0.5
    assert cal.predict(0.85) >= 0.5


def test_calibration_is_monotone_non_decreasing():
    scores = [i / 100 for i in range(100)]
    # noisy but increasing win propensity
    outcomes = [1 if (i + (i % 3)) >= 50 else 0 for i in range(100)]
    cal = fit_binned_calibration(scores, outcomes, n_bins=10)
    probs = [b.calibrated_prob for b in cal.bins]
    assert probs == sorted(probs)  # monotone non-decreasing after PAV


def test_calibration_falls_back_to_base_rate_when_too_few():
    cal = fit_binned_calibration([0.5], [1], n_bins=10)
    assert cal.bins == ()
    assert cal.predict(0.9) == cal.base_rate


def test_calibration_treats_negative_label_as_loss_not_win():
    # Multi-class triple_barrier/trend_scan stop-out (-1) must count as a loss,
    # never a win. With all losses the base rate (and every prediction) is 0.0.
    cal = fit_binned_calibration([0.2, 0.4, 0.6, 0.8], [-1, -1, 0, -1], n_bins=2)
    assert cal.base_rate == 0.0
    assert cal.predict(0.9) == 0.0
