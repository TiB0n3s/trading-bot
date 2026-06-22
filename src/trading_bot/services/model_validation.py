"""Time-aware model validation helpers (purged walk-forward).

A row-index 80/20 split over rows fetched in arbitrary (e.g. DESC, or
per-symbol-concatenated) order is NOT a forward-time holdout and leaks future
information into the training set. These helpers build a true forward holdout
and purge/embargo the train/test boundary so overlapping forward-label windows
do not leak across it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

# Embargo seconds by horizon label — at least the forward-label window so a
# train row's label cannot overlap the test period.
_HORIZON_SECONDS = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "60m": 60 * 60,
    "1h": 60 * 60,
}


def horizon_embargo_seconds(horizon: str, default: float = 15 * 60) -> float:
    return float(_HORIZON_SECONDS.get(str(horizon or "").strip().lower(), default))


def _to_epoch(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return None


def purged_time_split_indices(
    timestamps: Sequence[Any],
    *,
    test_fraction: float = 0.2,
    embargo_seconds: float = 0.0,
) -> tuple[list[int], list[int]]:
    """Return (train_idx, test_idx) for a forward-time holdout with embargo.

    The last ``test_fraction`` of rows *by time* form the test set (a true
    forward holdout). Train rows whose timestamp falls within
    ``embargo_seconds`` before the test start are dropped to remove label-window
    overlap. Rows with unparseable timestamps are excluded from both sets.

    Returns indices into the ORIGINAL ``timestamps`` sequence. Returns
    ``([], [])`` if there are not enough parseable timestamps to form both sets.
    """
    parsed = [(idx, _to_epoch(ts)) for idx, ts in enumerate(timestamps)]
    usable = [(idx, epoch) for idx, epoch in parsed if epoch is not None]
    if len(usable) < 2:
        return [], []

    usable.sort(key=lambda pair: pair[1])
    n = len(usable)
    n_test = max(1, int(round(n * test_fraction)))
    n_test = min(n_test, n - 1)  # keep at least one train row
    test = usable[n - n_test :]
    train_candidates = usable[: n - n_test]

    test_start_epoch = test[0][1]
    embargo_cutoff = test_start_epoch - float(embargo_seconds)
    train_idx = [idx for idx, epoch in train_candidates if epoch < embargo_cutoff]
    test_idx = [idx for idx, _ in test]
    if not train_idx or not test_idx:
        return [], []
    return train_idx, test_idx
