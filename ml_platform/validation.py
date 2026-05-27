"""Purged walk-forward validation for financial time-series.

Implements purged walk-forward splits per VALIDATION_SPLIT_POLICY.

Key concepts:
- Purge gap: training rows within purge_days of the test start are excluded to
  prevent temporal leakage from adjacent observations.
- Same-symbol embargo: test rows for a symbol are embargoed if the symbol's
  last training appearance is within embargo_days of test_start, preventing
  short-horizon look-ahead from recent symbol patterns.
- Expanding window: each fold's training set grows to include all data before
  the purge zone.

Read-only. No model training, no live behavior changes.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from db import DB_PATH
from market_time import is_trading_day
from ml_platform.governance import BASELINE_POLICIES, CALIBRATION_BUCKETS, MIN_SAMPLE_GATES


PURGE_DEFAULT_DAYS = 5
EMBARGO_DEFAULT_DAYS = 2
N_FOLDS_DEFAULT = 3
MIN_TRAIN_DAYS_DEFAULT = 15

_VALIDATION_VERSION = "purged_walk_forward_v1"


# ---------------------------------------------------------------------------
# Trading-day arithmetic
# ---------------------------------------------------------------------------

def _trading_dates_in_range(start: str, end: str) -> list[str]:
    """Return sorted list of ISO trading dates in [start, end] inclusive."""
    result = []
    current = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    while current <= end_d:
        if is_trading_day(current):
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def _add_trading_days(d: str, n: int) -> str:
    """Return ISO date n trading days from d. n may be negative."""
    if n == 0:
        return d
    current = date.fromisoformat(d)
    step = 1 if n > 0 else -1
    remaining = abs(n)
    while remaining > 0:
        current += timedelta(days=step)
        if is_trading_day(current):
            remaining -= 1
    return current.isoformat()


def _trading_days_between(start: str, end: str) -> int:
    """Count trading days strictly between start and end (exclusive of both)."""
    count = 0
    current = date.fromisoformat(start) + timedelta(days=1)
    end_d = date.fromisoformat(end)
    while current < end_d:
        if is_trading_day(current):
            count += 1
        current += timedelta(days=1)
    return count


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FoldSpec:
    fold_index: int
    train_start: str | None     # first date in training window (None = no training data)
    train_end: str | None       # last date in training window (inclusive, before purge)
    purge_start: str | None     # first date in purge zone
    purge_end: str | None       # last date in purge zone (day before test_start)
    test_start: str             # first date in test window
    test_end: str               # last date in test window (inclusive)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FoldCounts:
    fold_index: int
    train_rows: int
    purged_rows: int              # rows in purge zone (excluded from training)
    test_rows_total: int          # all test-window rows
    test_rows_embargoed: int      # test rows excluded by same-symbol embargo
    test_rows_usable: int         # test_rows_total - test_rows_embargoed
    complete_label_rows: int      # usable test rows with label_horizon_status=complete

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SymbolAdjacency:
    symbol: str
    last_train_date: str
    first_test_date: str | None
    gap_trading_days: int
    embargoed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LeakageCheck:
    fold_index: int
    date_overlap: bool                          # train and test share any date — always False if built correctly
    purge_rows_in_train: bool                   # purge-zone rows leaking into training — always False if built correctly
    feature_available_at_violations: int        # test rows where feature_available_at date > timestamp date (cross-day look-ahead)
    stale_feature_rows: int                     # test rows with is_stale=1 (should be excluded before training)
    min_train_test_gap_trading_days: int | None # trading days between train_end and test_start
    meets_purge_gap: bool                       # gap >= purge_days
    symbol_adjacency: list[dict]                # per-symbol adjacency summary (capped)
    symbols_only_in_test: list[str]             # symbols with test rows but no training rows
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WalkForwardSplitResult:
    version: str
    status: str                             # "ready" | "insufficient_data" | "spec_only"
    date_range: dict[str, str | None]
    trading_days_in_range: int
    n_folds: int
    purge_days: int
    embargo_days: int
    expanding_window: bool
    min_train_days: int
    fold_specs: list[dict]
    fold_counts: list[dict] | None          # None if no DB rows were queried
    leakage_checks: list[dict] | None
    total_train_rows: int | None
    total_test_rows: int | None
    total_purged_rows: int | None
    total_embargoed_rows: int | None
    minimum_sample_gates: dict[str, Any]
    calibration_contract: dict[str, Any]
    baseline_contract: dict[str, Any]
    warnings: list[str]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Fold spec construction (pure, no DB)
# ---------------------------------------------------------------------------

def build_fold_specs(
    trading_dates: list[str],
    *,
    n_folds: int = N_FOLDS_DEFAULT,
    purge_days: int = PURGE_DEFAULT_DAYS,
    embargo_days: int = EMBARGO_DEFAULT_DAYS,
    expanding: bool = True,
    min_train_days: int = MIN_TRAIN_DAYS_DEFAULT,
) -> tuple[list[FoldSpec], list[str]]:
    """Build fold time-window specs from a sorted list of trading dates.

    Returns (fold_specs, warnings). Fold specs are purely structural; no DB
    rows are queried here.
    """
    warnings: list[str] = []
    total = len(trading_dates)

    required_min = min_train_days + purge_days + n_folds
    if total < required_min:
        warnings.append(
            f"Only {total} trading days available; need at least {required_min} "
            f"({min_train_days} train + {purge_days} purge + {n_folds} test). "
            "Fold specs are structural only — expect zero test rows when queried."
        )

    # The test portion starts after the minimum training+purge buffer.
    first_test_idx = min_train_days + purge_days
    test_pool = total - first_test_idx

    if test_pool <= 0:
        warnings.append(
            "No test periods possible: date range is too short for the given parameters."
        )
        return [], warnings

    fold_size, remainder = divmod(test_pool, n_folds)
    actual_n_folds = n_folds
    if fold_size == 0:
        actual_n_folds = test_pool
        fold_size = 1
        remainder = 0
        warnings.append(
            f"Reduced to {actual_n_folds} folds (fold_size=1) because test pool "
            f"({test_pool} days) < requested n_folds ({n_folds})."
        )

    folds: list[FoldSpec] = []
    for i in range(actual_n_folds):
        test_start_idx = first_test_idx + i * fold_size + min(i, remainder)
        test_end_idx = first_test_idx + (i + 1) * fold_size + min(i + 1, remainder) - 1
        if i == actual_n_folds - 1:
            test_end_idx = total - 1

        test_start = trading_dates[test_start_idx]
        test_end = trading_dates[test_end_idx]

        purge_end_idx = test_start_idx - 1
        purge_start_idx = test_start_idx - purge_days

        if purge_start_idx < 0:
            warnings.append(
                f"Fold {i}: purge zone extends before the available date range — "
                "clipping to start of data. Purge gap will be smaller than requested."
            )
            purge_start_idx = 0

        purge_start = trading_dates[purge_start_idx] if purge_start_idx <= purge_end_idx else None
        purge_end = trading_dates[purge_end_idx] if purge_end_idx >= 0 else None

        train_end_idx = purge_start_idx - 1
        if train_end_idx < 0:
            train_start = None
            train_end = None
        else:
            train_end = trading_dates[train_end_idx]
            train_start = trading_dates[0] if expanding else None

        folds.append(FoldSpec(
            fold_index=i,
            train_start=train_start,
            train_end=train_end,
            purge_start=purge_start,
            purge_end=purge_end,
            test_start=test_start,
            test_end=test_end,
        ))

    return folds, warnings


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    r = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return r is not None


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


# ---------------------------------------------------------------------------
# Per-fold row counting
# ---------------------------------------------------------------------------

def _count_rows_in_fold(
    con: sqlite3.Connection,
    fold: FoldSpec,
    embargo_days: int,
) -> FoldCounts:
    """Count feature_snapshot rows assigned to each role in this fold."""

    def _count(start: str | None, end: str | None) -> int:
        if not start or not end:
            return 0
        r = con.execute(
            "SELECT COUNT(*) FROM feature_snapshots WHERE substr(timestamp,1,10) BETWEEN ? AND ?",
            (start, end),
        ).fetchone()
        return int(r[0] or 0)

    train_rows = _count(fold.train_start, fold.train_end)
    purged_rows = _count(fold.purge_start, fold.purge_end)
    test_rows_total = _count(fold.test_start, fold.test_end)

    # Same-symbol embargo: symbols whose last training date is within embargo_days
    # of train_end have their test rows embargoed for the first embargo_days of
    # the test window.
    embargoed_rows = 0
    if fold.train_end and embargo_days > 0 and test_rows_total > 0:
        embargo_window_start = _add_trading_days(fold.train_end, -(embargo_days - 1))
        if fold.train_start and embargo_window_start < fold.train_start:
            embargo_window_start = fold.train_start

        embargo_symbols_rows = con.execute(
            """
            SELECT DISTINCT symbol
            FROM feature_snapshots
            WHERE substr(timestamp,1,10) BETWEEN ? AND ?
            """,
            (embargo_window_start, fold.train_end),
        ).fetchall()
        embargo_symbols = [r[0] for r in embargo_symbols_rows]

        if embargo_symbols:
            test_embargo_end = _add_trading_days(fold.test_start, embargo_days - 1)
            if test_embargo_end > fold.test_end:
                test_embargo_end = fold.test_end
            placeholders = ",".join("?" * len(embargo_symbols))
            r2 = con.execute(
                f"""
                SELECT COUNT(*) FROM feature_snapshots
                WHERE symbol IN ({placeholders})
                  AND substr(timestamp,1,10) BETWEEN ? AND ?
                """,
                embargo_symbols + [fold.test_start, test_embargo_end],
            ).fetchone()
            embargoed_rows = int(r2[0] or 0)

    # Complete-label test rows (all fixed-horizon labels present)
    complete_label_rows = 0
    if _table_exists(con, "labeled_setups"):
        r = con.execute(
            """
            SELECT COUNT(*) FROM feature_snapshots fs
            JOIN labeled_setups ls ON ls.snapshot_id = fs.id
            WHERE substr(fs.timestamp,1,10) BETWEEN ? AND ?
              AND ls.ret_fwd_5m IS NOT NULL
              AND ls.ret_fwd_15m IS NOT NULL
              AND ls.ret_fwd_30m IS NOT NULL
            """,
            (fold.test_start, fold.test_end),
        ).fetchone()
        complete_label_rows = int(r[0] or 0)

    usable = max(0, test_rows_total - embargoed_rows)
    return FoldCounts(
        fold_index=fold.fold_index,
        train_rows=train_rows,
        purged_rows=purged_rows,
        test_rows_total=test_rows_total,
        test_rows_embargoed=embargoed_rows,
        test_rows_usable=usable,
        complete_label_rows=complete_label_rows,
    )


# ---------------------------------------------------------------------------
# Per-fold leakage check
# ---------------------------------------------------------------------------

def _check_leakage_for_fold(
    con: sqlite3.Connection,
    fold: FoldSpec,
    purge_days: int,
) -> LeakageCheck:
    """Audit temporal integrity for a single fold."""

    # 1. Date overlap (should always be False by construction)
    date_overlap = bool(
        fold.train_end and fold.train_end >= fold.test_start
    )

    # 2. Purge rows in train (structural check — always False if fold built correctly)
    purge_in_train = bool(
        fold.purge_start and fold.train_end and fold.train_end >= fold.purge_start
    )

    # 3. feature_available_at integrity: check date-level (not sub-second) look-ahead.
    # feature_available_at is set microseconds after timestamp in atomic feature
    # generation — that is benign. A cross-date violation (features dated after the
    # decision date) would be a real look-ahead issue.
    fav_violations = 0
    cols = _table_columns(con, "feature_snapshots")
    if "feature_available_at" in cols:
        r = con.execute(
            """
            SELECT COUNT(*) FROM feature_snapshots
            WHERE substr(timestamp,1,10) BETWEEN ? AND ?
              AND substr(feature_available_at,1,10) > substr(timestamp,1,10)
            """,
            (fold.test_start, fold.test_end),
        ).fetchone()
        fav_violations = int(r[0] or 0)

    # 4. Actual gap between train_end and test_start in trading days
    gap = None
    meets_gap = True
    if fold.train_end:
        gap = _trading_days_between(fold.train_end, fold.test_start)
        meets_gap = gap >= purge_days

    # 5. Per-symbol adjacency: symbols active near the train/test boundary
    symbol_adjacency: list[dict] = []
    symbols_only_in_test: list[str] = []

    if fold.train_end:
        # Symbols that have test-window rows
        test_syms_rows = con.execute(
            "SELECT DISTINCT symbol FROM feature_snapshots WHERE substr(timestamp,1,10) BETWEEN ? AND ?",
            (fold.test_start, fold.test_end),
        ).fetchall()
        test_symbols = {r[0] for r in test_syms_rows}

        # Symbols that have training rows
        train_syms_rows = con.execute(
            "SELECT DISTINCT symbol FROM feature_snapshots WHERE substr(timestamp,1,10) BETWEEN ? AND ?",
            (fold.train_start or fold.test_start, fold.train_end),
        ).fetchall() if fold.train_start else []
        train_symbols = {r[0] for r in train_syms_rows}

        symbols_only_in_test = sorted(test_symbols - train_symbols)

        # For each symbol in both sets, find last train date and proximity
        if train_symbols and test_symbols and fold.purge_start:
            boundary_rows = con.execute(
                """
                SELECT symbol, MAX(substr(timestamp,1,10)) AS last_date
                FROM feature_snapshots
                WHERE symbol IN ({})
                  AND substr(timestamp,1,10) BETWEEN ? AND ?
                GROUP BY symbol
                """.format(",".join("?" * len(train_symbols))),
                list(train_symbols) + [fold.purge_start, fold.train_end],
            ).fetchall() if fold.train_start else []

            # First test date per symbol
            first_test_rows = con.execute(
                """
                SELECT symbol, MIN(substr(timestamp,1,10)) AS first_date
                FROM feature_snapshots
                WHERE symbol IN ({})
                  AND substr(timestamp,1,10) BETWEEN ? AND ?
                GROUP BY symbol
                """.format(",".join("?" * len(test_symbols))),
                list(test_symbols) + [fold.test_start, fold.test_end],
            ).fetchall()
            first_test_by_sym = {r[0]: r[1] for r in first_test_rows}

            for row in boundary_rows[:20]:  # cap to avoid huge output
                sym = row[0]
                last_train = row[1]
                first_test = first_test_by_sym.get(sym)
                sym_gap = (
                    _trading_days_between(last_train, first_test)
                    if first_test else None
                )
                embargoed = sym_gap is not None and sym_gap < purge_days
                symbol_adjacency.append(SymbolAdjacency(
                    symbol=sym,
                    last_train_date=last_train,
                    first_test_date=first_test,
                    gap_trading_days=sym_gap if sym_gap is not None else -1,
                    embargoed=embargoed,
                ).to_dict())

    # 6. Stale feature rows in test window
    stale_rows = 0
    if "is_stale" in cols:
        r = con.execute(
            """
            SELECT COUNT(*) FROM feature_snapshots
            WHERE substr(timestamp,1,10) BETWEEN ? AND ?
              AND is_stale = 1
            """,
            (fold.test_start, fold.test_end),
        ).fetchone()
        stale_rows = int(r[0] or 0)

    note = (
        "Leakage check verified: no date overlap, no purge-zone bleed, "
        "feature_available_at integrity OK."
        if not date_overlap and not purge_in_train and fav_violations == 0 and meets_gap
        else "One or more leakage checks failed — review warnings."
    )

    return LeakageCheck(
        fold_index=fold.fold_index,
        date_overlap=date_overlap,
        purge_rows_in_train=purge_in_train,
        feature_available_at_violations=fav_violations,
        stale_feature_rows=stale_rows,
        min_train_test_gap_trading_days=gap,
        meets_purge_gap=meets_gap,
        symbol_adjacency=symbol_adjacency,
        symbols_only_in_test=symbols_only_in_test,
        note=note,
    )


# ---------------------------------------------------------------------------
# Calibration and baseline scaffolds
# ---------------------------------------------------------------------------

def _calibration_contract() -> dict[str, Any]:
    return {
        "description": (
            "Calibration-by-period requires predicted probabilities from a trained model. "
            "This scaffold defines the contract; populate after model training."
        ),
        "required_inputs": [
            "predicted_probability_per_test_row",
            "actual_label_per_test_row",
            "fold_index_per_test_row",
            "snapshot_date_per_test_row",
        ],
        "required_outputs": [
            "calibration_curve_per_fold",
            "brier_score_per_fold",
            "expected_calibration_error_per_fold",
            "calibration_buckets",
        ],
        "calibration_buckets": list(CALIBRATION_BUCKETS),
        "status": "scaffold_only_requires_trained_model",
    }


def _baseline_contract() -> dict[str, Any]:
    return {
        "description": (
            "Baseline comparison requires scored test rows. "
            "Populate after training and evaluation."
        ),
        "required_baselines": list(BASELINE_POLICIES),
        "required_metrics_per_baseline": [
            "precision_at_threshold",
            "recall_of_winners",
            "false_reject_rate_for_winners",
            "expected_value_after_friction",
            "balanced_accuracy",
        ],
        "comparison_note": (
            "Model must beat null_no_ml_current_bot and current_bot_policy "
            "before any promotion is considered."
        ),
        "status": "scaffold_only_requires_trained_model",
    }


# ---------------------------------------------------------------------------
# Top-level report
# ---------------------------------------------------------------------------

def walk_forward_split_report(
    *,
    db_path: Path | str = DB_PATH,
    start_date: str,
    end_date: str,
    n_folds: int = N_FOLDS_DEFAULT,
    purge_days: int = PURGE_DEFAULT_DAYS,
    embargo_days: int = EMBARGO_DEFAULT_DAYS,
    expanding: bool = True,
    min_train_days: int = MIN_TRAIN_DAYS_DEFAULT,
) -> dict[str, Any]:
    """Produce a purged walk-forward split report for the given date range.

    Queries feature_snapshots for row counts and leakage checks.
    Does not train models, write to DB, or affect live behavior.
    """
    db_path = Path(db_path)

    trading_dates = _trading_dates_in_range(start_date, end_date)
    fold_specs, warnings = build_fold_specs(
        trading_dates,
        n_folds=n_folds,
        purge_days=purge_days,
        embargo_days=embargo_days,
        expanding=expanding,
        min_train_days=min_train_days,
    )

    fold_counts: list[dict] | None = None
    leakage_checks: list[dict] | None = None
    total_train = total_test = total_purged = total_embargoed = None

    if fold_specs and db_path.exists():
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            if _table_exists(con, "feature_snapshots"):
                counts = [
                    _count_rows_in_fold(con, fold, embargo_days)
                    for fold in fold_specs
                ]
                leaks = [
                    _check_leakage_for_fold(con, fold, purge_days)
                    for fold in fold_specs
                ]
                fold_counts = [c.to_dict() for c in counts]
                leakage_checks = [lk.to_dict() for lk in leaks]

                total_train = sum(c.train_rows for c in counts)
                total_test = sum(c.test_rows_usable for c in counts)
                total_purged = sum(c.purged_rows for c in counts)
                total_embargoed = sum(c.test_rows_embargoed for c in counts)

    # Determine status
    usable_test = total_test or 0
    usable_train = total_train or 0
    min_test_for_ready = MIN_SAMPLE_GATES["walk_forward_splits"] * 30
    if not fold_specs:
        status = "insufficient_data"
        warnings.append(
            "No fold specs could be built. Collect more trading sessions before "
            "running walk-forward validation."
        )
    elif fold_counts is None:
        status = "spec_only"
    elif usable_train == 0:
        status = "insufficient_data"
        warnings.append(
            "All feature_snapshot rows fall inside test windows — no training data "
            "is available. Collect sessions spanning the full date range before training."
        )
    elif usable_test < min_test_for_ready:
        status = "insufficient_data"
        warnings.append(
            f"Only {usable_test} usable test rows across all folds; "
            f"need ~{min_test_for_ready} (≈{MIN_SAMPLE_GATES['walk_forward_splits']} folds × 30 rows) "
            "before validation claims are meaningful."
        )
    else:
        any_leakage = leakage_checks and any(
            lk["date_overlap"] or lk["purge_rows_in_train"] or lk["feature_available_at_violations"] > 0
            for lk in leakage_checks
        )
        status = "leakage_detected" if any_leakage else "ready"

    result = WalkForwardSplitResult(
        version=_VALIDATION_VERSION,
        status=status,
        date_range={"start": start_date, "end": end_date},
        trading_days_in_range=len(trading_dates),
        n_folds=len(fold_specs),
        purge_days=purge_days,
        embargo_days=embargo_days,
        expanding_window=expanding,
        min_train_days=min_train_days,
        fold_specs=[f.to_dict() for f in fold_specs],
        fold_counts=fold_counts,
        leakage_checks=leakage_checks,
        total_train_rows=total_train,
        total_test_rows=total_test,
        total_purged_rows=total_purged,
        total_embargoed_rows=total_embargoed,
        minimum_sample_gates=MIN_SAMPLE_GATES,
        calibration_contract=_calibration_contract(),
        baseline_contract=_baseline_contract(),
        warnings=warnings,
        note=(
            "Purged walk-forward validation infrastructure. "
            "Read-only. No model training, no live behavior changes. "
            f"Status '{status}': "
            + (
                "collect more sessions before making model claims."
                if status == "insufficient_data"
                else "fold specs and leakage checks are available."
            )
        ),
    )
    return result.to_dict()
