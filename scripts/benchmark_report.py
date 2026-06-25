#!/usr/bin/env python3
"""Portfolio benchmark report — does the bot's realized equity beat doing nothing?

Read-only. No trade authority. This answers the one portfolio-level question the
rest of the system does not: over the same window, did the bot's realized equity
beat SPY / QQQ / an equal-weight buy-and-hold of the names it actually traded?

It is the portfolio-level complement to the signal-level expected-value bar. It
reports; humans decide. It cannot promote, size, block, approve, or route, and
it does not touch the auto-buy freeze.

Build spec: Trading Project/02-wiki/50-system/Benchmark report spec.md

Sources (all read-only):
  * matched_trades (trades.db, opened mode=ro&immutable=1) — realized round-trips.
  * Daily adjusted closes for SPY/QQQ/universe via the EXISTING
    PolygonMarketDataService (no new feed). First fetch is cached to
    --cache-dir as CSV so reruns are offline-reproducible.
  * Cost model: ExpectedValueAssumptions from
    src/trading_bot/research/expected_value.py (percentage-point units;
    project default round-trip = spread 0.05 + slippage 0.03 x2 = 0.11%).

Every structured payload carries
  "runtime_effect": "research_benchmark_no_trade_authority".
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# Make `src` and the scripts dir importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from trading_bot.research.expected_value import (  # noqa: E402
    ExpectedValueAssumptions,
    evaluate_expected_value,
    round_trip_cost_pct,
)

RUNTIME_EFFECT = "research_benchmark_no_trade_authority"
TRADING_DAYS_PER_YEAR = 252
# The spec's "41-symbol universe" predates the universe expansion. The live
# roster lives in scripts/symbols_config.py: APPROVED_SYMBOLS are tradeable;
# CONTEXT_ONLY_SYMBOLS are intelligence-only and never tradeable, so holding them
# is not a fair "do nothing" counterfactual and they are excluded by default.
SPEC_UNIVERSE_SIZE = 41


def resolve_universe(spec: str, traded_symbols: list[str]) -> tuple[list[str], dict[str, Any]]:
    """Map --universe to a concrete ticker list, excluding context-only names."""
    spec = (spec or "approved").strip().lower()
    meta: dict[str, Any] = {"mode": spec, "excluded_context_only": []}
    if spec == "traded":
        meta["description"] = "names the bot actually traded (selection-conditioned)"
        return traded_symbols, meta
    if spec == "approved":
        try:
            import symbols_config as sc  # scripts/ is on sys.path when run from repo root

            approved = sorted(set(sc.APPROVED_SYMBOLS))
            context_only = sorted(set(getattr(sc, "CONTEXT_ONLY_SYMBOLS", set())))
            meta["universe_version"] = getattr(sc, "SYMBOL_UNIVERSE_VERSION", None)
            meta["excluded_context_only"] = context_only
            meta["description"] = (
                "equal-weight of the approved tradeable universe "
                f"({getattr(sc, 'SYMBOL_UNIVERSE_VERSION', 'current')}); "
                f"{len(context_only)} context-only names excluded"
            )
            return approved, meta
        except Exception as exc:  # noqa: BLE001 — fall back, never crash
            sys.stderr.write(f"[warn] could not import symbols_config ({exc}); using traded set\n")
            meta["mode"] = "traded_fallback"
            meta["description"] = "fallback: traded names (symbols_config import failed)"
            return traded_symbols, meta
    # Explicit comma-separated list.
    custom = sorted({s.strip().upper() for s in spec.upper().split(",") if s.strip()})
    meta["description"] = "custom ticker list"
    return custom, meta


# --------------------------------------------------------------------------- #
# Data loading                                                                #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Trade:
    symbol: str
    entry_ts: datetime
    exit_ts: datetime
    holding_minutes: float
    qty: float
    entry_price: float
    realized_pnl: float
    realized_pnl_pct: float  # percentage points (0.547 == 0.547%)
    entry_source: str
    signal_source: str


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.strip())


def load_trades(db_path: Path) -> list[Trade]:
    uri = f"file:{db_path}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        rows = con.execute(
            """
            SELECT symbol, entry_timestamp, exit_timestamp, holding_minutes,
                   qty, entry_price, realized_pnl, realized_pnl_pct,
                   entry_source, signal_source
            FROM matched_trades
            WHERE entry_timestamp IS NOT NULL AND exit_timestamp IS NOT NULL
            ORDER BY exit_timestamp ASC
            """
        ).fetchall()
    finally:
        con.close()
    trades: list[Trade] = []
    for r in rows:
        try:
            trades.append(
                Trade(
                    symbol=str(r[0]).upper(),
                    entry_ts=_parse_ts(r[1]),
                    exit_ts=_parse_ts(r[2]),
                    holding_minutes=float(r[3]) if r[3] is not None else 0.0,
                    qty=float(r[4]) if r[4] is not None else 0.0,
                    entry_price=float(r[5]) if r[5] is not None else 0.0,
                    realized_pnl=float(r[6]) if r[6] is not None else 0.0,
                    realized_pnl_pct=float(r[7]) if r[7] is not None else 0.0,
                    entry_source=str(r[8]) if r[8] is not None else "unknown",
                    signal_source=str(r[9]) if r[9] is not None else "unknown",
                )
            )
        except (TypeError, ValueError):
            continue
    return trades


# --------------------------------------------------------------------------- #
# Benchmark daily closes (existing Polygon access + local cache)              #
# --------------------------------------------------------------------------- #
def _cache_file(cache_dir: Path, symbol: str, start: str, end: str) -> Path:
    return cache_dir / f"{symbol}_1d_{start}_{end}.csv"


def fetch_daily_closes(
    symbol: str,
    start: str,
    end: str,
    cache_dir: Path,
    *,
    refresh: bool,
    service: Any,
    sleep_s: float = 0.0,
) -> dict[date, float]:
    """Return {trading_date: adjusted_close}. Cached to CSV for reproducibility."""
    import time

    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_file(cache_dir, symbol, start, end)
    if path.exists() and not refresh:
        out: dict[date, float] = {}
        with path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                out[date.fromisoformat(row["date"])] = float(row["close"])
        return out
    if service is None:
        raise RuntimeError(
            f"No cache for {symbol} and Polygon service unavailable "
            "(set POLYGON_API_KEY or run once online to populate the cache)."
        )
    # Live fetch — throttle for the free-tier rate limit and back off on 429.
    bars = None
    for attempt in range(5):
        try:
            bars = service.aggregate_bar_dicts(
                symbol, from_date=start, to_date=end, multiplier=1, timespan="day", adjusted=True
            )
            break
        except Exception as exc:  # noqa: BLE001
            if "429" in str(exc) and attempt < 4:
                time.sleep(15.0 * (attempt + 1))
                continue
            raise
    if sleep_s > 0:
        time.sleep(sleep_s)
    out = {}
    for b in bars:
        ts = b.get("timestamp") or ""
        close = b.get("close")
        if not ts or close is None:
            continue
        out[datetime.fromisoformat(ts).astimezone(timezone.utc).date()] = float(close)
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "close"])
        for d in sorted(out):
            w.writerow([d.isoformat(), out[d]])
    return out


# --------------------------------------------------------------------------- #
# Series statistics                                                           #
# --------------------------------------------------------------------------- #
@dataclass
class SeriesStats:
    label: str
    total_return_pct: float | None
    annualized_pct: float | None
    max_drawdown_pct: float | None
    sharpe: float | None
    n_days: int


def _max_drawdown_pct(equity: list[float]) -> float | None:
    if len(equity) < 2:
        return None
    peak = equity[0]
    worst = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return round(worst * 100.0, 4)


def _sharpe(daily_returns: list[float]) -> float | None:
    if len(daily_returns) < 2:
        return None
    sd = statistics.pstdev(daily_returns)
    if sd == 0:
        return None
    mean = statistics.mean(daily_returns)
    return round(mean / sd * math.sqrt(TRADING_DAYS_PER_YEAR), 4)


def stats_from_equity(label: str, dates: list[date], equity: list[float]) -> SeriesStats:
    """equity is the equity curve aligned to `dates` (same length)."""
    n_days = len(dates)
    if n_days < 2 or equity[0] <= 0:
        return SeriesStats(label, None, None, None, None, n_days)
    total_return = equity[-1] / equity[0] - 1.0
    ann = (1.0 + total_return) ** (TRADING_DAYS_PER_YEAR / n_days) - 1.0
    daily_returns = [
        equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity)) if equity[i - 1] > 0
    ]
    return SeriesStats(
        label=label,
        total_return_pct=round(total_return * 100.0, 4),
        annualized_pct=round(ann * 100.0, 4),
        max_drawdown_pct=_max_drawdown_pct(equity),
        sharpe=_sharpe(daily_returns),
        n_days=n_days,
    )


def benchmark_equity_curve(
    closes: dict[date, float], trading_days: list[date]
) -> tuple[list[date], list[float]]:
    """Buy-once at the first available close; mark-to-market on each trading day."""
    aligned_dates: list[date] = []
    aligned_close: list[float] = []
    last = None
    for d in trading_days:
        if d in closes:
            last = closes[d]
        if last is not None:
            aligned_dates.append(d)
            aligned_close.append(last)
    return aligned_dates, aligned_close


# --------------------------------------------------------------------------- #
# Core report                                                                 #
# --------------------------------------------------------------------------- #
def build_report(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db)
    trades = load_trades(db_path)
    if not trades:
        return {"runtime_effect": RUNTIME_EFFECT, "verdict": "underpowered", "n_trades": 0}

    start_dt = min(t.entry_ts for t in trades)
    end_dt = max(t.exit_ts for t in trades)
    start_d, end_d = start_dt.date(), end_dt.date()
    equity0 = float(args.equity)

    # --- Bot realized-equity curve, by exit date ---------------------------- #
    daily_pnl: dict[date, float] = {}
    for t in trades:
        daily_pnl[t.exit_ts.date()] = daily_pnl.get(t.exit_ts.date(), 0.0) + t.realized_pnl
    bot_dates = sorted(daily_pnl)
    bot_equity: list[float] = []
    running = equity0
    for d in bot_dates:
        running += daily_pnl[d]
        bot_equity.append(running)
    # Prepend the starting equity so day-0 return is measured from the base.
    bot_curve_dates = [start_d] + bot_dates
    bot_curve_equity = [equity0] + bot_equity

    total_pnl = sum(t.realized_pnl for t in trades)
    total_return_on_equity = total_pnl / equity0 * 100.0

    # --- Source decomposition: the blended headline mixes two populations ---- #
    # auto_buy_manager / internal_bar_only are the bot's own decisions; webhook /
    # tradingview_alert trades are externally fed. They must not be conflated.
    def _group(field: str) -> list[dict[str, Any]]:
        agg: dict[str, list[float]] = {}
        for t in trades:
            agg.setdefault(getattr(t, field), []).append(t.realized_pnl)
        out = [
            {
                "key": k,
                "n": len(v),
                "realized_pnl": round(sum(v), 2),
                "return_on_equity_pct": round(sum(v) / equity0 * 100.0, 4),
            }
            for k, v in agg.items()
        ]
        return sorted(out, key=lambda d: d["realized_pnl"], reverse=True)

    by_entry_source = _group("entry_source")
    by_signal_source = _group("signal_source")

    # --- Return on capital deployed (time-weighted exposure) ---------------- #
    window_minutes = max(1.0, (end_dt - start_dt).total_seconds() / 60.0)
    exposure_dollar_minutes = sum(
        abs(t.qty) * t.entry_price * max(0.0, t.holding_minutes) for t in trades
    )
    time_weighted_deployed = exposure_dollar_minutes / window_minutes
    return_on_deployed_pct = (
        total_pnl / time_weighted_deployed * 100.0 if time_weighted_deployed > 0 else None
    )

    # --- Cost model: per-trade EV (reuse canonical tool) + net P&L ---------- #
    assumptions = ExpectedValueAssumptions(
        spread_pct=args.spread_pct,
        slippage_pct=args.slippage_pct,
        slippage_turns=args.slippage_turns,
        commission_pct=args.commission_pct,
        account_equity=equity0,
        max_position_pct=args.max_position_pct,
        reference_price=statistics.median(t.entry_price for t in trades),
    )
    cost_pct = round_trip_cost_pct(assumptions)  # percentage points per round trip
    per_trade_ev = evaluate_expected_value(
        [t.realized_pnl_pct for t in trades], assumptions=assumptions
    )
    # Net realized P&L: charge the round-trip cost against each trade's notional.
    net_total_pnl = sum(
        t.realized_pnl - (cost_pct / 100.0) * abs(t.qty) * t.entry_price for t in trades
    )
    net_return_on_equity = net_total_pnl / equity0 * 100.0

    # --- Profit concentration ---------------------------------------------- #
    best_day = max(daily_pnl.values()) if daily_pnl else 0.0
    best_day_date = max(daily_pnl, key=daily_pnl.get) if daily_pnl else None
    best_day_pct_of_total = (best_day / total_pnl * 100.0) if total_pnl else None
    return_ex_best_day_pct = (total_pnl - best_day) / equity0 * 100.0
    best_trade = max(trades, key=lambda t: t.realized_pnl)
    best_trade_pct_of_total = best_trade.realized_pnl / total_pnl * 100.0 if total_pnl else None

    # --- Benchmarks --------------------------------------------------------- #
    traded_symbols = sorted({t.symbol for t in trades})
    universe, universe_meta = resolve_universe(args.universe, traded_symbols)

    service = _make_service()
    cache_dir = Path(args.cache_dir)
    fetch_from = (start_d).isoformat()
    fetch_to = end_d.isoformat()

    def closes_for(sym: str) -> dict[date, float] | None:
        try:
            return fetch_daily_closes(
                sym,
                fetch_from,
                fetch_to,
                cache_dir,
                refresh=args.refresh,
                service=service,
                sleep_s=args.sleep,
            )
        except Exception as exc:  # noqa: BLE001 — flag, never crash the report
            sys.stderr.write(f"[warn] {sym}: {exc}\n")
            return None

    # The union of trading days that appear in the index ETFs defines the axis.
    spy_closes = closes_for("SPY") or {}
    qqq_closes = closes_for("QQQ") or {}
    trading_days = sorted(d for d in set(spy_closes) | set(qqq_closes) if start_d <= d <= end_d)

    def bench_stats(label: str, closes: dict[date, float]) -> tuple[SeriesStats | None, dict]:
        in_window = {d: c for d, c in closes.items() if start_d <= d <= end_d}
        d_aligned, c_aligned = benchmark_equity_curve(in_window, trading_days)
        if len(c_aligned) < 2:
            return None, {"buy_hold_return_pct": None, "n_days": len(c_aligned)}
        bh = (c_aligned[-1] / c_aligned[0] - 1.0) * 100.0
        return stats_from_equity(label, d_aligned, c_aligned), {
            "buy_hold_return_pct": round(bh, 4),
            "anchor_date": d_aligned[0].isoformat(),
            "anchor_close": round(c_aligned[0], 4),
            "final_date": d_aligned[-1].isoformat(),
            "final_close": round(c_aligned[-1], 4),
            "n_days": len(c_aligned),
        }

    spy_stats, spy_meta = bench_stats("SPY buy-and-hold", spy_closes)
    qqq_stats, qqq_meta = bench_stats("QQQ buy-and-hold", qqq_closes)

    # Equal-weight (buy-once) of the traded names.
    ew_returns: list[float] = []
    ew_missing: list[str] = []
    ew_per_symbol: dict[str, float] = {}
    for sym in universe:
        closes = closes_for(sym) or {}
        in_window = {d: c for d, c in closes.items() if start_d <= d <= end_d}
        d_aligned, c_aligned = benchmark_equity_curve(in_window, trading_days)
        if len(c_aligned) < 2 or c_aligned[0] <= 0:
            ew_missing.append(sym)
            continue
        r = c_aligned[-1] / c_aligned[0] - 1.0
        ew_returns.append(r)
        ew_per_symbol[sym] = round(r * 100.0, 4)
    ew_return_pct = round(statistics.mean(ew_returns) * 100.0, 4) if ew_returns else None

    # --- Bot equity stats (on the same axis) -------------------------------- #
    bot_stats = stats_from_equity("Bot realized equity", bot_curve_dates, bot_curve_equity)

    # --- Verdict ------------------------------------------------------------ #
    benchmarks = {
        "SPY": spy_meta.get("buy_hold_return_pct"),
        "QQQ": qqq_meta.get("buy_hold_return_pct"),
        "equal_weight_universe": ew_return_pct,
    }
    valid_bench = [v for v in benchmarks.values() if v is not None]
    best_bench = max(valid_bench) if valid_bench else None

    # Underpowered if too few trades, too few independent days, or one day/trade
    # dominates the entire result. Mirrors the blocked-null discipline.
    n_active_days = len(daily_pnl)
    underpowered_reasons = []
    if len(trades) < args.min_trades:
        underpowered_reasons.append(f"N={len(trades)} < {args.min_trades}")
    if n_active_days < args.min_active_days:
        underpowered_reasons.append(f"active_days={n_active_days} < {args.min_active_days}")
    if best_day_pct_of_total is not None and best_day_pct_of_total >= args.dominance_pct:
        underpowered_reasons.append(
            f"best_day={best_day_pct_of_total:.1f}% >= {args.dominance_pct}% of P&L"
        )

    if best_bench is None:
        verdict = "underpowered"
    elif underpowered_reasons:
        verdict = "underpowered"
    elif net_return_on_equity > best_bench:
        verdict = "beats_benchmark"
    else:
        verdict = "lags_benchmark"

    return {
        "runtime_effect": RUNTIME_EFFECT,
        "verdict": verdict,
        "underpowered_reasons": underpowered_reasons,
        "window": {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "trading_days_in_axis": len(trading_days),
            "active_days": n_active_days,
        },
        "account_equity": equity0,
        "n_trades": len(trades),
        "bot": {
            "total_realized_pnl": round(total_pnl, 2),
            "gross_return_on_equity_pct": round(total_return_on_equity, 4),
            "net_return_on_equity_pct": round(net_return_on_equity, 4),
            "net_total_realized_pnl": round(net_total_pnl, 2),
            "return_on_capital_deployed_pct": (
                round(return_on_deployed_pct, 4) if return_on_deployed_pct is not None else None
            ),
            "time_weighted_deployed_dollars": round(time_weighted_deployed, 2),
            "stats": vars(bot_stats),
        },
        "source_decomposition": {
            "by_entry_source": by_entry_source,
            "by_signal_source": by_signal_source,
        },
        "per_trade_expected_value": per_trade_ev,
        "cost_model": {
            "round_trip_cost_pct": cost_pct,
            "spread_pct": args.spread_pct,
            "slippage_pct": args.slippage_pct,
            "slippage_turns": args.slippage_turns,
            "commission_pct": args.commission_pct,
        },
        "profit_concentration": {
            "best_day": best_day_date.isoformat() if best_day_date else None,
            "best_day_pnl": round(best_day, 2),
            "best_day_pct_of_total": (
                round(best_day_pct_of_total, 2) if best_day_pct_of_total is not None else None
            ),
            "return_ex_best_day_pct": round(return_ex_best_day_pct, 4),
            "best_trade_symbol": best_trade.symbol,
            "best_trade_pnl": round(best_trade.realized_pnl, 2),
            "best_trade_pct_of_total": (
                round(best_trade_pct_of_total, 2) if best_trade_pct_of_total is not None else None
            ),
        },
        "benchmarks": {
            "SPY": {"stats": vars(spy_stats) if spy_stats else None, **spy_meta},
            "QQQ": {"stats": vars(qqq_stats) if qqq_stats else None, **qqq_meta},
            "equal_weight_universe": {
                "buy_hold_return_pct": ew_return_pct,
                "n_symbols": len(ew_returns),
                "n_requested": len(universe),
                "missing_symbols": ew_missing,
                "per_symbol_return_pct": ew_per_symbol,
                "universe": universe_meta,
                "spec_universe_size": SPEC_UNIVERSE_SIZE,
            },
        },
        "deltas_vs_net_bot_pct": {
            k: (round(net_return_on_equity - v, 4) if v is not None else None)
            for k, v in benchmarks.items()
        },
    }


def _make_service() -> Any:
    try:
        from trading_bot.services.polygon_market_data_service import PolygonMarketDataService

        svc = PolygonMarketDataService()
        return svc if svc.configured else None
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #
def _fmt(v: Any, suffix: str = "") -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:+.2f}{suffix}" if suffix == "%" else f"{v:.4f}{suffix}"
    return f"{v}{suffix}"


def render_markdown(rep: dict[str, Any]) -> str:
    if rep.get("n_trades", 0) == 0:
        return "# Portfolio benchmark report\n\nNo matched trades found — underpowered.\n"

    w = rep["window"]
    bot = rep["bot"]
    pc = rep["profit_concentration"]
    bm = rep["benchmarks"]
    deltas = rep["deltas_vs_net_bot_pct"]
    verdict = rep["verdict"]
    badge = {
        "beats_benchmark": "✅ BEATS",
        "lags_benchmark": "❌ LAGS",
        "underpowered": "⚠️ UNDERPOWERED",
    }.get(verdict, verdict)

    lines: list[str] = []
    lines.append("# Portfolio benchmark report")
    lines.append("")
    lines.append(
        f"> **Verdict: {badge}** — bot net return on equity "
        f"{_fmt(bot['net_return_on_equity_pct'], '%')} vs best benchmark over the same window. "
        "Read-only; no trade authority."
    )
    lines.append("")
    lines.append(
        f"**Window:** {w['start'][:16]} → {w['end'][:16]}  "
        f"({w['trading_days_in_axis']} trading days, {w['active_days']} with realized P&L)  \n"
        f"**Trades:** N = {rep['n_trades']}  ·  **Account base:** ${rep['account_equity']:.2f}"
    )
    if rep.get("underpowered_reasons"):
        lines.append("")
        lines.append("**Underpowered because:** " + "; ".join(rep["underpowered_reasons"]) + ".")
    lines.append("")

    # Headline comparison table
    lines.append("## Did effort beat inaction?")
    lines.append("")
    lines.append("| Series | Total return | Ann. | Max DD | Sharpe* |")
    lines.append("|---|---:|---:|---:|---:|")

    def row(label: str, st: dict | None, total_override: float | None = None) -> str:
        if st is None:
            return f"| {label} | n/a | n/a | n/a | n/a |"
        tot = total_override if total_override is not None else st.get("total_return_pct")
        return (
            f"| {label} | {_fmt(tot, '%')} | {_fmt(st.get('annualized_pct'), '%')} "
            f"| {_fmt(st.get('max_drawdown_pct'), '%')} | {_fmt(st.get('sharpe'))} |"
        )

    lines.append(
        row(
            "**Bot (gross)**",
            bot["stats"],
            total_override=bot["gross_return_on_equity_pct"],
        )
    )
    lines.append(
        f"| **Bot (net of costs)** | {_fmt(bot['net_return_on_equity_pct'], '%')} | — | — | — |"
    )
    lines.append(row("SPY buy-and-hold", bm["SPY"]["stats"], bm["SPY"].get("buy_hold_return_pct")))
    lines.append(row("QQQ buy-and-hold", bm["QQQ"]["stats"], bm["QQQ"].get("buy_hold_return_pct")))
    ew = bm["equal_weight_universe"]
    ew_label = (
        "approved"
        if ew.get("universe", {}).get("mode", "").startswith("approved")
        else ew.get("universe", {}).get("mode", "universe")
    )
    lines.append(
        f"| Equal-weight {ew_label} ({ew['n_symbols']} names) "
        f"| {_fmt(ew['buy_hold_return_pct'], '%')} | — | — | — |"
    )
    lines.append("")
    lines.append(
        "*Sharpe is annualized from daily returns and is **not trustworthy** at this N — "
        "the bot sits in cash most days, so a handful of active days dominate. Treat all "
        "risk-adjusted figures as directional only.*"
    )
    lines.append("")

    # Deltas
    lines.append("## Net bot edge vs each benchmark")
    lines.append("")
    lines.append("| Benchmark | Bot net − benchmark |")
    lines.append("|---|---:|")
    for k, label in (
        ("SPY", "SPY"),
        ("QQQ", "QQQ"),
        ("equal_weight_universe", "Equal-weight universe"),
    ):
        lines.append(f"| {label} | {_fmt(deltas.get(k), '%')} |")
    lines.append("")

    # Two framings
    lines.append("## Is the signal good when active?")
    lines.append("")
    ev = rep["per_trade_expected_value"]
    lines.append(
        f"- **Return on equity** (mostly-cash portfolio): gross "
        f"{_fmt(bot['gross_return_on_equity_pct'], '%')}, net "
        f"{_fmt(bot['net_return_on_equity_pct'], '%')} on ${rep['account_equity']:.0f}."
    )
    lines.append(
        f"- **Return on capital deployed** (time-weighted, per-$-at-risk, gross): "
        f"{_fmt(bot['return_on_capital_deployed_pct'], '%')} on an average "
        f"${bot['time_weighted_deployed_dollars']:.2f} deployed."
    )
    lines.append(
        f"- **Per-trade EV:** gross {_fmt(ev.get('gross_expected_return_pct'))}pp, "
        f"net {_fmt(ev.get('net_expected_return_pct'))}pp after {rep['cost_model']['round_trip_cost_pct']}pp "
        f"round-trip cost; win rate {_fmt(ev.get('win_rate_pct'))}%, "
        f"profit factor {_fmt(ev.get('profit_factor'))}."
    )
    lines.append("")

    # Source decomposition
    sd = rep.get("source_decomposition", {})
    if sd:
        lines.append("## Whose P&L is this? (source decomposition)")
        lines.append("")
        lines.append(
            "The blended headline mixes the bot's **own** decisions with externally-fed "
            "webhook/alert trades. They behave very differently — read them apart:"
        )
        lines.append("")
        lines.append("| Entry source | N | Realized P&L | Return on equity |")
        lines.append("|---|---:|---:|---:|")
        for g in sd.get("by_entry_source", []):
            lines.append(
                f"| `{g['key']}` | {g['n']} | ${g['realized_pnl']:.2f} "
                f"| {_fmt(g['return_on_equity_pct'], '%')} |"
            )
        lines.append("")
        lines.append("| Signal source | N | Realized P&L | Return on equity |")
        lines.append("|---|---:|---:|---:|")
        for g in sd.get("by_signal_source", []):
            lines.append(
                f"| `{g['key']}` | {g['n']} | ${g['realized_pnl']:.2f} "
                f"| {_fmt(g['return_on_equity_pct'], '%')} |"
            )
        lines.append("")

    # Profit concentration
    lines.append("## Is the result an artifact of one day?")
    lines.append("")
    lines.append(
        f"- **Best day:** {pc['best_day']} contributed ${pc['best_day_pnl']:.2f} = "
        f"**{_fmt(pc['best_day_pct_of_total'])}%** of total P&L."
    )
    lines.append(
        f"- **Best single trade:** {pc['best_trade_symbol']} ${pc['best_trade_pnl']:.2f} = "
        f"{_fmt(pc['best_trade_pct_of_total'])}% of total."
    )
    lines.append(
        f"- **Return with the best day removed:** {_fmt(pc['return_ex_best_day_pct'], '%')} "
        f"on equity (vs {_fmt(bot['gross_return_on_equity_pct'], '%')} including it)."
    )
    lines.append("")

    # Honesty caveats
    lines.append("## Caveats")
    lines.append("")
    lines.append(
        f"- **N = {rep['n_trades']} round-trips over {w['active_days']} active days — low power.** "
        "Every statistic above carries wide error bars; this is a description, not a validated edge."
    )
    lines.append(
        "- **Matched round-trips only.** Open/unmatched positions are excluded from the equity curve."
    )
    lines.append(
        "- **Benchmarks are close-to-close, buy-once**, anchored at the first in-window session "
        f"close (e.g. SPY anchor {bm['SPY'].get('anchor_date')} @ {bm['SPY'].get('anchor_close')}). "
        "Adjusted closes; dividends included where Polygon adjusts for them."
    )
    uni = ew.get("universe", {})
    lines.append(
        f"- **Equal-weight basket:** {uni.get('description', 'n/a')} "
        f"({ew['n_symbols']}/{ew.get('n_requested', '?')} names priced, buy-once, equal $)."
    )
    if ew["missing_symbols"]:
        n_missing = len(ew["missing_symbols"])
        lines.append(
            f"- **Equal-weight excluded {n_missing} priced-out "
            f"name{'s' if n_missing != 1 else ''}** lacking 2+ in-window closes "
            f"(e.g. delisted): {', '.join(ew['missing_symbols'])}."
        )
    lines.append(
        f"- **Whole-share drag at ${rep['account_equity']:.0f}:** at the reference price the "
        f"account deploys {_fmt(ev.get('deployment_pct'))}% of target "
        f"({ev.get('shares')} whole shares), cash drag "
        f"{_fmt(ev.get('whole_share_cash_drag_pct'))}%. See the per-trade EV block."
    )
    lines.append("")
    lines.append(f"`runtime_effect: {rep['runtime_effect']}`  ·  `verdict: {verdict}`")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Vault drop                                                                  #
# --------------------------------------------------------------------------- #
def write_vault_raw(rep: dict[str, Any], md: str, raw_dir: Path) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = rep["window"]["end"][:10]
    path = raw_dir / f"{stamp}-benchmark-report.md"
    header = (
        "---\n"
        "source: scripts/benchmark_report.py\n"
        f"verdict: {rep['verdict']}\n"
        "runtime_effect: research_benchmark_no_trade_authority\n"
        "note: candidate signal only — never authority\n"
        'compiles_into: "[[Benchmark report spec]]"\n'
        "---\n\n"
    )
    footer = (
        "\n## Related\n"
        "- [[Benchmark report spec]] — the build spec this report implements\n"
        "- [[The bar is EV after your costs]] — the signal-level bar this complements\n"
        "- [[expected_value_tools]] — the cost model reused here\n"
    )
    path.write_text(header + md + footer, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--db", default=os.getenv("TRADES_DB_PATH", "trades.db"))
    p.add_argument("--equity", type=float, default=531.0, help="account equity base (~$531)")
    p.add_argument("--max-position-pct", type=float, default=1.0)
    p.add_argument(
        "--universe",
        default="approved",
        help="'approved' (tradeable universe from symbols_config), 'traded' (names actually "
        "traded), or a comma-separated ticker list",
    )
    p.add_argument("--cache-dir", default="data/benchmark_cache")
    p.add_argument("--refresh", action="store_true", help="re-fetch daily bars, ignore cache")
    p.add_argument(
        "--sleep",
        type=float,
        default=13.0,
        help="seconds to sleep after each LIVE daily-bar fetch (free-tier throttle; "
        "ignored on cache hits)",
    )
    # Cost model — project defaults (percentage points): 0.05 + 0.03x2 = 0.11% round-trip.
    p.add_argument("--spread-pct", type=float, default=0.05)
    p.add_argument("--slippage-pct", type=float, default=0.03)
    p.add_argument("--slippage-turns", type=float, default=2.0)
    p.add_argument("--commission-pct", type=float, default=0.0)
    # Power thresholds for the underpowered verdict.
    p.add_argument("--min-trades", type=int, default=200)
    p.add_argument("--min-active-days", type=int, default=15)
    p.add_argument("--dominance-pct", type=float, default=40.0)
    p.add_argument("--out", default=None, help="write Markdown report to this path")
    p.add_argument("--json", action="store_true", help="also print the structured JSON payload")
    p.add_argument("--write-vault", action="store_true", help="drop a dated raw note in the vault")
    p.add_argument(
        "--vault-raw-dir",
        default=os.getenv(
            "VAULT_RAW_DIR",
            "/mnt/c/AI Brain/Trading Project/01-raw",
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    # Markdown contains non-ASCII (arrows, badges); keep output UTF-8 everywhere.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    args = parse_args(argv)
    rep = build_report(args)
    md = render_markdown(rep)
    sys.stdout.write(md + "\n")
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        sys.stderr.write(f"[info] wrote {args.out}\n")
    if args.write_vault:
        path = write_vault_raw(rep, md, Path(args.vault_raw_dir))
        sys.stderr.write(f"[info] vault raw drop: {path}\n")
    if args.json:
        sys.stderr.write(json.dumps(rep, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
