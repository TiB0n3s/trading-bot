"""Model accuracy baseline and broker buffer status operator checks."""

from __future__ import annotations

import os
from pathlib import Path


def run_model_accuracy_baseline(target_date: str, *, base_dir: Path) -> bool:
    """Report OOS accuracy with purged walk-forward split for the configured model."""
    print()
    print("=" * 72)
    print(f"  Model Accuracy Baseline — {target_date}")
    print("=" * 72)

    # Import here to avoid heavyweight deps at CLI startup
    import sys
    src_dir = base_dir / "src"
    scripts_dir = base_dir / "scripts"
    for d in (src_dir, scripts_dir, base_dir):
        if d.exists() and str(d) not in sys.path:
            sys.path.insert(0, str(d))

    try:
        from services.supervised_prediction_training_service import (
            fetch_training_rows,
            train_supervised_prediction_model,
        )
    except ImportError as exc:
        print(f"[WARN] supervised training service unavailable: {exc}")
        return False

    rows = fetch_training_rows(limit=5000, prediction_time_cutoff=target_date)
    print(f"training rows fetched    : {len(rows)}")

    if not rows:
        print("[WARN] no training rows available for this date")
        return False

    result = train_supervised_prediction_model(rows=rows)

    print(f"provider                 : {result.provider}")
    print(f"sample_size              : {result.sample_size}")
    print(f"trained                  : {result.trained}")
    print(f"validation_method        : {result.validation_method}")
    acc = result.accuracy
    print(f"oob_accuracy             : {acc:.4f}" if acc is not None else "oob_accuracy             : -")
    pos = result.baseline_positive_rate
    print(f"baseline_positive_rate   : {pos:.4f}" if pos is not None else "baseline_positive_rate   : -")

    m = result.promotion_metrics or {}
    brier = m.get("brier_score")
    print(f"brier_score              : {brier:.6f}" if brier is not None else "brier_score              : -")
    cal = m.get("calibration_error")
    print(f"calibration_error_mae    : {cal:.6f}" if cal is not None else "calibration_error_mae    : - (calibrator not yet fit)")
    ev = m.get("expected_value_per_decision")
    print(f"expected_value_proxy     : {ev:.6f}" if ev is not None else "expected_value_proxy     : -")

    print()
    if not result.trained:
        print(f"[WARN] model not trained: {result.reason}")
        return False
    print("[OK] model accuracy baseline completed")
    return True


def run_broker_buffer_status() -> bool:
    """Report current broker entry-buffer env-var state (#16 audit item)."""
    print()
    print("=" * 72)
    print("  Broker Buffer Status")
    print("=" * 72)

    use_quote_anchor = os.getenv("BROKER_USE_QUOTE_ANCHOR", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }
    slippage_pct_raw = os.getenv("BROKER_ENTRY_SLIPPAGE_PCT", "0.0")
    try:
        slippage_pct = float(slippage_pct_raw)
    except ValueError:
        slippage_pct = 0.0

    buffer_active = use_quote_anchor or slippage_pct != 0.0

    print(f"BROKER_USE_QUOTE_ANCHOR     : {os.getenv('BROKER_USE_QUOTE_ANCHOR', 'not set')} (resolved: {use_quote_anchor})")
    print(f"BROKER_ENTRY_SLIPPAGE_PCT   : {os.getenv('BROKER_ENTRY_SLIPPAGE_PCT', 'not set')} (resolved: {slippage_pct:.4f}%)")
    print()
    if buffer_active:
        if use_quote_anchor:
            print("  Entry anchor : ask price (BROKER_USE_QUOTE_ANCHOR=true)")
        if slippage_pct != 0.0:
            print(f"  Slippage buf : +{slippage_pct:.4f}% added to entry reference (BROKER_ENTRY_SLIPPAGE_PCT)")
        print("  Effect       : BUY qty and bracket legs anchored on buffered reference price")
    else:
        print("  Buffer       : OFF (default) — entry reference = last trade price, no buffer")
        print("  To enable    : set BROKER_USE_QUOTE_ANCHOR=true and/or BROKER_ENTRY_SLIPPAGE_PCT=0.10")
    print()
    print("[OK] broker buffer status report completed")
    return True
