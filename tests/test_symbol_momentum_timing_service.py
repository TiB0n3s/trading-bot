#!/usr/bin/env python3
"""Focused tests for symbol momentum timing analysis."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.symbol_momentum_timing_service import (  # noqa: E402
    SymbolMomentumTimingService,
    long_state_score,
    short_state_score,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(label)


class FakeRepo:
    def __init__(self, rows):
        self.rows = rows

    def load_feature_label_rows(self, target_date, symbol=None, limit=None):
        rows = self.rows
        if symbol:
            rows = [r for r in rows if r["symbol"] == symbol]
        if limit is not None:
            rows = rows[:limit]
        return rows


def row(
    symbol,
    minute,
    *,
    price=100,
    ret5=0.2,
    ret15=0.4,
    vwap=0.3,
    range_pos=0.7,
    volume=1.4,
    rel_strength=0.1,
    fwd15=0.2,
    fwd30=0.5,
    setup="confirmed_near_vwap_recovery",
):
    return {
        "timestamp": f"2026-06-01 10:{minute:02d}:00",
        "symbol": symbol,
        "last_price": price,
        "ret_5m": ret5,
        "ret_15m": ret15,
        "distance_from_vwap": vwap,
        "range_pos_15m": range_pos,
        "volume_ratio_5m": volume,
        "relative_strength_5m": rel_strength,
        "ret_fwd_5m": fwd15 / 2,
        "ret_fwd_15m": fwd15,
        "ret_fwd_30m": fwd30,
        "max_up_15m": max(fwd15, 0),
        "max_down_15m": min(fwd15, 0),
        "setup_label": setup,
        "setup_score": 70,
        "label_horizon_status": "complete",
        "outcome_label": "up" if fwd15 > 0 else "down",
    }


def test_long_state_score_rewards_constructive_momentum():
    score, reasons = long_state_score(row("AAPL", 1))

    assert_true(score >= 5, "long score should be actionable")
    assert_true("constructive_vwap" in reasons, "long vwap reason")
    assert_true("relative_strength" in reasons, "relative strength reason")


def test_short_state_score_rewards_below_vwap_pressure():
    score, reasons = short_state_score(
        row(
            "AAPL",
            2,
            ret5=-0.2,
            ret15=-0.5,
            vwap=-0.4,
            range_pos=0.3,
            rel_strength=-0.2,
            fwd15=-0.3,
            fwd30=-0.8,
            setup="near_vwap_neutral_fade_risk",
        )
    )

    assert_true(score >= 5, "short score should be actionable")
    assert_true("below_vwap_pressure" in reasons, "short vwap reason")
    assert_true("relative_weakness" in reasons, "relative weakness reason")


def test_analyze_rows_ranks_best_long_and_short_windows():
    rows = []
    for i in range(25):
        rows.append(row("LONG", i % 60, price=100 + i, fwd15=0.2, fwd30=0.4))
    rows.append(row("LONG", 55, price=130, fwd15=1.2, fwd30=2.4, setup="balanced_transition_state"))

    for i in range(25):
        rows.append(
            row(
                "SHORT",
                i % 60,
                price=100 - i / 10,
                ret5=-0.2,
                ret15=-0.4,
                vwap=-0.3,
                range_pos=0.3,
                rel_strength=-0.1,
                fwd15=-0.2,
                fwd30=-0.5,
                setup="near_vwap_neutral_fade_risk",
            )
        )
    rows.append(
        row(
            "SHORT",
            56,
            price=95,
            ret5=-0.5,
            ret15=-0.8,
            vwap=-0.5,
            range_pos=0.2,
            rel_strength=-0.2,
            fwd15=-1.0,
            fwd30=-2.2,
            setup="unclassified_transition",
        )
    )

    service = SymbolMomentumTimingService(repository=FakeRepo(rows))
    memory = service.analyze(target_date="2026-06-01", top_n=3)

    assert_equal(memory["row_count"], len(rows), "row count")
    assert_equal(memory["symbol_count"], 2, "symbol count")
    assert_equal(memory["top_long_windows"][0]["symbol"], "LONG", "top long symbol")
    assert_equal(memory["top_long_windows"][0]["ret_fwd_30m"], 2.4, "top long return")
    assert_equal(memory["top_short_windows"][0]["symbol"], "SHORT", "top short symbol")
    assert_equal(memory["top_short_windows"][0]["ret_fwd_30m"], -2.2, "top short return")
    assert_true(
        memory["symbol_memory"]["LONG"]["recommendation"] in ("favor_long_pullbacks", "two_sided_timing_required"),
        "long recommendation",
    )
    assert_true(
        memory["symbol_memory"]["SHORT"]["recommendation"] in ("favor_short_or_sell_rallies", "two_sided_timing_required"),
        "short recommendation",
    )


def main():
    tests = [
        test_long_state_score_rewards_constructive_momentum,
        test_short_state_score_rewards_below_vwap_pressure,
        test_analyze_rows_ranks_best_long_and_short_windows,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print()
    print(f"All {len(tests)} symbol momentum timing tests passed.")


if __name__ == "__main__":
    main()
