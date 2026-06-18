"""Tests for the read-only portfolio benchmark report.

Pins the math (drawdown, Sharpe, equal-weight, net-of-cost, profit concentration)
and one deterministic end-to-end run against a temp DB with a pre-seeded price
cache — so the report never touches the network in CI and the headline numbers
are guarded against silent regressions (mirrors the expected_value oracle test).

Run:
  python3 -m pytest tests/test_benchmark_report.py -q
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import benchmark_report as br  # noqa: E402


# --------------------------------------------------------------------------- #
# Pure-math unit tests                                                        #
# --------------------------------------------------------------------------- #
def test_max_drawdown_pct():
    # Peak 110 then trough 90 -> -18.1818%; recovery does not erase the trough.
    assert br._max_drawdown_pct([100, 110, 90, 120]) == pytest.approx(-18.1818, abs=1e-4)
    assert br._max_drawdown_pct([100]) is None  # too short
    assert br._max_drawdown_pct([100, 101, 102]) == 0.0  # monotone up -> no DD


def test_sharpe_edge_cases():
    assert br._sharpe([0.01]) is None  # too short
    assert br._sharpe([1.0, 1.0, 1.0]) is None  # zero variance
    s = br._sharpe([0.01, -0.01, 0.02, -0.02])
    assert isinstance(s, float)


def test_benchmark_equity_curve_carries_forward():
    closes = {date(2026, 1, 2): 100.0, date(2026, 1, 6): 110.0}  # 1/5 missing
    days = [date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)]
    aligned_dates, aligned_close = br.benchmark_equity_curve(closes, days)
    assert aligned_dates == days
    assert aligned_close == [100.0, 100.0, 110.0]  # 1/5 carries the prior close


def test_stats_from_equity_total_return():
    st = br.stats_from_equity("x", [date(2026, 1, 2), date(2026, 1, 3)], [100.0, 106.0])
    assert st.total_return_pct == pytest.approx(6.0, abs=1e-6)
    assert st.n_days == 2


def test_resolve_universe_modes():
    custom, meta = br.resolve_universe("AAA, bbb ,AAA", ["ZZZ"])
    assert custom == ["AAA", "BBB"]
    assert meta["mode"] == "aaa, bbb ,aaa"  # raw spec echoed; list is normalized

    traded, meta2 = br.resolve_universe("traded", ["MSFT", "AAPL"])
    assert traded == ["MSFT", "AAPL"]
    assert meta2["mode"] == "traded"


# --------------------------------------------------------------------------- #
# End-to-end fixture (temp DB + seeded cache, no network)                     #
# --------------------------------------------------------------------------- #
def _make_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.execute(
        """
        CREATE TABLE matched_trades (
            symbol TEXT, entry_timestamp TEXT, exit_timestamp TEXT,
            holding_minutes REAL, qty REAL, entry_price REAL,
            realized_pnl REAL, realized_pnl_pct REAL,
            entry_source TEXT, signal_source TEXT
        )
        """
    )
    rows = [
        # symbol, entry, exit, hold, qty, entry_px, pnl, pnl_pct, entry_src, signal_src
        (
            "AAA",
            "2026-01-02 10:00:00",
            "2026-01-02 15:00:00",
            300.0,
            2.0,
            100.0,
            10.0,
            5.0,
            "auto_buy_manager",
            "internal_bar_only",
        ),
        (
            "BBB",
            "2026-01-05 10:00:00",
            "2026-01-06 12:00:00",
            200.0,
            1.0,
            50.0,
            -4.0,
            -8.0,
            "webhook_buy",
            "tradingview_alert",
        ),
    ]
    con.executemany("INSERT INTO matched_trades VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


def _seed_cache(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Window resolves to 2026-01-02 .. 2026-01-06.
    series = {
        "SPY": [100.0, 101.0, 102.0],  # +2%
        "QQQ": [200.0, 205.0, 210.0],  # +5%
        "AAA": [100.0, 105.0, 110.0],  # +10%
        "BBB": [50.0, 45.0, 40.0],  # -20%
    }
    dates = ["2026-01-02", "2026-01-05", "2026-01-06"]
    for sym, closes in series.items():
        f = cache_dir / f"{sym}_1d_2026-01-02_2026-01-06.csv"
        f.write_text(
            "date,close\n" + "".join(f"{d},{c}\n" for d, c in zip(dates, closes)),
            encoding="utf-8",
        )


def _run(tmp_path: Path, extra: list[str]):
    db = tmp_path / "trades.db"
    cache = tmp_path / "cache"
    _make_db(db)
    _seed_cache(cache)
    args = br.parse_args(
        [
            "--db",
            str(db),
            "--cache-dir",
            str(cache),
            "--universe",
            "AAA,BBB",
            "--equity",
            "100",
            *extra,
        ]
    )
    return br.build_report(args)


def test_end_to_end_numbers(tmp_path):
    # Disable the underpowered guard so the head-to-head verdict is exercised.
    rep = _run(tmp_path, ["--min-trades", "1", "--min-active-days", "1", "--dominance-pct", "250"])

    assert rep["n_trades"] == 2
    assert rep["window"]["trading_days_in_axis"] == 3

    bot = rep["bot"]
    assert bot["gross_return_on_equity_pct"] == pytest.approx(6.0, abs=1e-6)
    # Costs: 0.11% round-trip on notional 200 + 50 -> 0.22 + 0.055 = 0.275 on $100 base.
    assert bot["net_return_on_equity_pct"] == pytest.approx(5.725, abs=1e-6)

    pc = rep["profit_concentration"]
    assert pc["best_day"] == "2026-01-02"
    assert pc["best_day_pct_of_total"] == pytest.approx(166.67, abs=1e-2)
    assert pc["return_ex_best_day_pct"] == pytest.approx(-4.0, abs=1e-6)

    bm = rep["benchmarks"]
    assert bm["SPY"]["buy_hold_return_pct"] == pytest.approx(2.0, abs=1e-4)
    assert bm["QQQ"]["buy_hold_return_pct"] == pytest.approx(5.0, abs=1e-4)
    assert bm["equal_weight_universe"]["buy_hold_return_pct"] == pytest.approx(-5.0, abs=1e-4)
    assert bm["equal_weight_universe"]["n_symbols"] == 2

    # Net bot (5.725) edges the best benchmark (QQQ 5.0).
    assert rep["deltas_vs_net_bot_pct"]["QQQ"] == pytest.approx(0.725, abs=1e-3)
    assert rep["verdict"] == "beats_benchmark"

    src = {g["key"]: g["realized_pnl"] for g in rep["source_decomposition"]["by_entry_source"]}
    assert src["auto_buy_manager"] == 10.0
    assert src["webhook_buy"] == -4.0


def test_underpowered_by_default(tmp_path):
    # Default thresholds: N=2 < 200 -> underpowered regardless of the head-to-head.
    rep = _run(tmp_path, [])
    assert rep["verdict"] == "underpowered"
    assert any("N=2" in r for r in rep["underpowered_reasons"])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
