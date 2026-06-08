#!/usr/bin/env python3
"""
Strategy learner.

Reads closed matched trades, learns which symbols/setups are working or failing,
and writes strategy_memory.json for live use by app.py.

Safe design:
- Never places orders
- Never increases max risk caps
- Requires sample size before applying lessons
- Only produces advisory/tightening memory
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from policy_artifacts import atomic_write_json
from trade_matcher import rebuild_matched_trades

from repositories.reporting_repo import ReportingRepository

BASE_DIR = Path(__file__).resolve().parent
OUT_FILE = BASE_DIR / "strategy_memory.json"
MEMORY_HISTORY_DIR = BASE_DIR / "strategy_memory_history"
REPORT_MEMORY_FILES = {
    "missed_opportunity_memory": BASE_DIR / "missed_opportunity_memory.json",
    "excursion_memory": BASE_DIR / "excursion_memory.json",
    "symbol_momentum_timing_memory": BASE_DIR / "symbol_momentum_timing_memory.json",
    "policy_backtest_summary": BASE_DIR / "policy_backtest_summary.json",
}
MANUAL_OVERRIDES_FILE = BASE_DIR / "manual_strategy_overrides.json"

LOOKBACK_DAYS = 20
MIN_TRADES_REQUIRED = 3


def pct(n, d):
    return round((n / d * 100), 1) if d else 0.0


def money(v):
    return round(float(v or 0), 2)


def new_bucket():
    return {
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "total_pnl": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
    }


def add_trade(bucket, pnl):
    pnl = float(pnl or 0)
    bucket["trades"] += 1
    bucket["total_pnl"] += pnl
    if pnl > 0:
        bucket["wins"] += 1
        bucket["gross_profit"] += pnl
    elif pnl < 0:
        bucket["losses"] += 1
        bucket["gross_loss"] += abs(pnl)


def finalize_bucket(bucket):
    trades = bucket["trades"]
    wins = bucket["wins"]
    losses = bucket["losses"]
    total_pnl = bucket["total_pnl"]

    win_rate = pct(wins, trades)
    expectancy = total_pnl / trades if trades else 0.0

    if trades < MIN_TRADES_REQUIRED:
        recommendation = "observe"
        min_setup_score = 40
        reason = f"sample too small: {trades} closed trades"
    elif expectancy >= 2.00 and win_rate >= 55:
        recommendation = "favor"
        min_setup_score = 40
        reason = f"positive expectancy ${expectancy:.2f}/trade with {win_rate:.1f}% win rate"
    elif expectancy < -4.00 and win_rate < 35:
        recommendation = "avoid"
        min_setup_score = 80
        reason = f"poor expectancy ${expectancy:.2f}/trade with {win_rate:.1f}% win rate"
    elif expectancy < 0 and win_rate < 45:
        recommendation = "caution"
        min_setup_score = 70
        reason = f"negative expectancy ${expectancy:.2f}/trade with {win_rate:.1f}% win rate"
    else:
        recommendation = "neutral"
        min_setup_score = 55
        reason = f"mixed results: expectancy ${expectancy:.2f}/trade, win rate {win_rate:.1f}%"

    profit_factor = None
    if bucket["gross_loss"] > 0:
        profit_factor = round(bucket["gross_profit"] / bucket["gross_loss"], 2)
    elif bucket["gross_profit"] > 0:
        profit_factor = "inf"

    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": win_rate,
        "total_pnl": money(total_pnl),
        "expectancy": round(expectancy, 2),
        "gross_profit": money(bucket["gross_profit"]),
        "gross_loss": money(bucket["gross_loss"]),
        "profit_factor": profit_factor,
        "recommendation": recommendation,
        "min_setup_score": min_setup_score,
        "reason": reason,
    }


def new_pattern_bucket():
    return {
        "rows": 0,
        "forward_outcome_rows": 0,
        "forward_return_total": 0.0,
        "forward_mfe_total": 0.0,
        "forward_mae_total": 0.0,
        "long_score_total": 0.0,
        "sell_score_total": 0.0,
        "best_buy_windows": 0,
        "good_buy_windows": 0,
        "sell_or_avoid_windows": 0,
        "triple_profit_first": 0,
        "triple_stop_first": 0,
        "triple_timeout": 0,
        "candle_body_total": 0.0,
        "close_location_total": 0.0,
        "range_atr_total": 0.0,
        "volume_pressure_total": 0.0,
        "candle_rows": 0,
    }


def add_pattern_row(bucket, row):
    bucket["rows"] += 1
    opportunity_quality = row["opportunity_quality"] or "unknown"
    opportunity_action = row["opportunity_action"] or "unknown"
    if opportunity_quality == "best_buy_window":
        bucket["best_buy_windows"] += 1
    if opportunity_quality in ("best_buy_window", "good_buy_window"):
        bucket["good_buy_windows"] += 1
    if opportunity_action == "sell_or_avoid_candidate":
        bucket["sell_or_avoid_windows"] += 1

    forward_return = row["forward_return_pct"]
    forward_mfe = row["forward_mfe_pct"]
    forward_mae = row["forward_mae_pct"]
    if forward_return is not None:
        bucket["forward_outcome_rows"] += 1
        bucket["forward_return_total"] += float(forward_return or 0)
    if forward_mfe is not None:
        bucket["forward_mfe_total"] += float(forward_mfe or 0)
    if forward_mae is not None:
        bucket["forward_mae_total"] += float(forward_mae or 0)
    if row["long_opportunity_score"] is not None:
        bucket["long_score_total"] += float(row["long_opportunity_score"] or 0)
    if row["sell_opportunity_score"] is not None:
        bucket["sell_score_total"] += float(row["sell_opportunity_score"] or 0)
    triple = row["triple_barrier_label"]
    if triple is not None:
        try:
            triple_value = int(float(triple))
            if triple_value > 0:
                bucket["triple_profit_first"] += 1
            elif triple_value < 0:
                bucket["triple_stop_first"] += 1
            else:
                bucket["triple_timeout"] += 1
        except Exception:
            pass
    candle_values = [
        ("candle_body_total", row["candle_body_pct"]),
        ("close_location_total", row["close_location"]),
        ("range_atr_total", row["range_atr_ratio"]),
        ("volume_pressure_total", row["volume_weighted_pressure_3"]),
    ]
    if any(value is not None for _, value in candle_values):
        bucket["candle_rows"] += 1
        for key, value in candle_values:
            if value is not None:
                bucket[key] += float(value or 0)


def finalize_pattern_bucket(bucket):
    rows = bucket["rows"]
    outcome_rows = bucket["forward_outcome_rows"]
    if not rows:
        return {
            "rows": 0,
            "recommendation": "observe",
            "authority_ready": False,
            "runtime_effect": "observe_only_pattern_learning_no_live_authority",
            "reason": "no bar-pattern samples",
        }

    avg_return = bucket["forward_return_total"] / outcome_rows if outcome_rows else None
    avg_mfe = bucket["forward_mfe_total"] / outcome_rows if outcome_rows else None
    avg_mae = bucket["forward_mae_total"] / outcome_rows if outcome_rows else None
    avg_long = bucket["long_score_total"] / rows
    avg_sell = bucket["sell_score_total"] / rows
    best_buy_rate = pct(bucket["best_buy_windows"], rows)
    sell_or_avoid_rate = pct(bucket["sell_or_avoid_windows"], rows)
    triple_total = (
        bucket["triple_profit_first"] + bucket["triple_stop_first"] + bucket["triple_timeout"]
    )
    candle_rows = bucket["candle_rows"]

    if rows < 30:
        evidence_label = "thin_sample"
    elif best_buy_rate >= 25 and avg_return is not None and avg_return > 0:
        evidence_label = "constructive_buy_pattern"
    elif sell_or_avoid_rate >= 25 and avg_return is not None and avg_return < 0:
        evidence_label = "sell_or_avoid_pattern"
    else:
        evidence_label = "mixed_pattern"

    return {
        "rows": rows,
        "forward_outcome_rows": outcome_rows,
        "avg_forward_return_pct": round(avg_return, 4) if avg_return is not None else None,
        "avg_forward_mfe_pct": round(avg_mfe, 4) if avg_mfe is not None else None,
        "avg_forward_mae_pct": round(avg_mae, 4) if avg_mae is not None else None,
        "avg_long_opportunity_score": round(avg_long, 2),
        "avg_sell_opportunity_score": round(avg_sell, 2),
        "best_buy_window_rate_pct": best_buy_rate,
        "sell_or_avoid_window_rate_pct": sell_or_avoid_rate,
        "triple_barrier_profit_first_rate_pct": pct(bucket["triple_profit_first"], triple_total),
        "triple_barrier_stop_first_rate_pct": pct(bucket["triple_stop_first"], triple_total),
        "triple_barrier_timeout_rate_pct": pct(bucket["triple_timeout"], triple_total),
        "avg_candle_body_pct": (
            round(bucket["candle_body_total"] / candle_rows, 4) if candle_rows else None
        ),
        "avg_close_location": (
            round(bucket["close_location_total"] / candle_rows, 4) if candle_rows else None
        ),
        "avg_range_atr_ratio": (
            round(bucket["range_atr_total"] / candle_rows, 4) if candle_rows else None
        ),
        "avg_volume_weighted_pressure_3": (
            round(bucket["volume_pressure_total"] / candle_rows, 4) if candle_rows else None
        ),
        "evidence_label": evidence_label,
        "recommendation": "observe",
        "authority_ready": False,
        "runtime_effect": "observe_only_pattern_learning_no_live_authority",
        "reason": "bar-pattern memory is evidence-only until promotion guardrails pass",
    }


def load_report_memories():
    """Load machine-readable summaries from reports, if present."""
    out = {}
    for key, path in REPORT_MEMORY_FILES.items():
        if not path.exists():
            out[key] = {
                "available": False,
                "reason": f"{path.name} not found",
            }
            continue

        try:
            out[key] = {
                "available": True,
                "data": json.loads(path.read_text()),
            }
        except Exception as e:
            out[key] = {
                "available": False,
                "reason": f"failed to parse {path.name}: {e}",
            }

    return out


def apply_manual_overrides(memory):
    """Merge manual_strategy_overrides.json into generated strategy memory.

    Manual overrides are intentionally tightening/advisory only. They let the
    operator seed lessons before enough matched trades exist, and they survive
    every learner regeneration.
    """
    if not MANUAL_OVERRIDES_FILE.exists():
        memory["manual_overrides_applied"] = 0
        return memory

    try:
        manual = json.loads(MANUAL_OVERRIDES_FILE.read_text())
    except Exception as e:
        memory["manual_overrides_error"] = f"failed to parse manual overrides: {e}"
        memory["manual_overrides_applied"] = 0
        return memory

    overrides = manual.get("symbols") or {}
    symbols = memory.setdefault("symbols", {})

    applied = 0
    for sym, override in overrides.items():
        sym = str(sym).upper().strip()
        if not sym or not isinstance(override, dict):
            continue

        existing = symbols.get(sym, {})
        merged = dict(existing)

        merged.update(
            {
                "trades": existing.get("trades", 0),
                "wins": existing.get("wins", 0),
                "losses": existing.get("losses", 0),
                "win_rate_pct": existing.get("win_rate_pct", 0.0),
                "expectancy": existing.get("expectancy", 0.0),
                "recommendation": override.get(
                    "recommendation",
                    existing.get("recommendation", "observe"),
                ),
                "min_setup_score": override.get(
                    "min_setup_score",
                    existing.get("min_setup_score", 55),
                ),
                "reason": override.get(
                    "reason",
                    existing.get("reason", "manual override"),
                ),
                "manual_override": True,
                "automated_snapshot": existing,
            }
        )

        symbols[sym] = merged
        applied += 1

    memory["manual_overrides_applied"] = applied
    memory["manual_overrides"] = overrides
    return memory


def archive_strategy_memory(memory):
    """Write a timestamped copy of strategy_memory.json for audit/history."""
    try:
        MEMORY_HISTORY_DIR.mkdir(exist_ok=True)

        generated_at = memory.get("generated_at")
        if generated_at:
            safe_ts = generated_at.replace("-", "").replace(":", "").replace(" ", "_")
        else:
            safe_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        history_file = MEMORY_HISTORY_DIR / f"{safe_ts}_strategy_memory.json"
        atomic_write_json(history_file, memory)

        # Keep the last 60 snapshots to avoid unbounded growth.
        snapshots = sorted(
            MEMORY_HISTORY_DIR.glob("*_strategy_memory.json"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )

        for old in snapshots[60:]:
            try:
                old.unlink()
            except Exception:
                pass

        memory["history_snapshot"] = str(history_file)
        return str(history_file)

    except Exception as e:
        memory["history_snapshot_error"] = str(e)
        return None


def main():
    try:
        rebuild_matched_trades()
    except Exception as e:
        print(f"[WARN] rebuild_matched_trades failed: {e}")

    cutoff = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    by_symbol = defaultdict(new_bucket)
    by_trend = defaultdict(new_bucket)
    by_bias = defaultdict(new_bucket)
    by_entry_quality = defaultdict(new_bucket)
    by_risk_level = defaultdict(new_bucket)
    by_symbol_context = defaultdict(new_bucket)

    by_market_bias_effective = defaultdict(new_bucket)
    by_fundamental_score = defaultdict(new_bucket)
    by_session_trend_label = defaultdict(new_bucket)
    by_prediction_decision = defaultdict(new_bucket)
    by_setup_label = defaultdict(new_bucket)
    by_setup_policy_action = defaultdict(new_bucket)
    by_buy_opportunity_recommendation = defaultdict(new_bucket)

    by_symbol_setup_label = defaultdict(new_bucket)
    by_symbol_prediction_decision = defaultdict(new_bucket)
    by_symbol_buy_opportunity = defaultdict(new_bucket)
    by_symbol_session_trend = defaultdict(new_bucket)
    by_bar_pattern_label = defaultdict(new_pattern_bucket)
    by_bar_pattern_opportunity = defaultdict(new_pattern_bucket)
    by_symbol_bar_pattern_label = defaultdict(new_pattern_bucket)
    by_symbol_bar_pattern_opportunity = defaultdict(new_pattern_bucket)

    repo = ReportingRepository()
    rows = repo.strategy_learner_rows(cutoff)
    bar_pattern_rows = repo.bar_pattern_strategy_rows(cutoff)

    for r in rows:
        symbol = r["symbol"] or "UNKNOWN"
        pnl = float(r["realized_pnl"] or 0)

        trend_key = f"{r['trend_direction'] or 'unknown'}/{r['trend_strength'] or 'unknown'}"
        bias_key = r["market_bias"] or "unknown"
        entry_key = r["entry_quality"] or "unknown"
        risk_key = r["risk_level"] or "unknown"

        context_key = "|".join(
            [
                symbol,
                trend_key,
                bias_key,
                entry_key,
                risk_key,
            ]
        )

        market_bias_effective_key = r["market_bias_effective"] or "unknown"
        fundamental_score_key = r["fundamental_score"] or "unknown"
        session_trend_key = r["session_trend_label"] or "unknown"
        prediction_decision_key = r["prediction_decision"] or "unknown"
        setup_label_key = r["setup_label"] or "unknown"
        setup_policy_key = r["setup_policy_action"] or "unknown"
        buy_opp_key = r["buy_opportunity_recommendation"] or "unknown"

        symbol_setup_key = f"{symbol}|{setup_label_key}"
        symbol_prediction_key = f"{symbol}|{prediction_decision_key}"
        symbol_buy_opp_key = f"{symbol}|{buy_opp_key}"
        symbol_session_key = f"{symbol}|{session_trend_key}"

        add_trade(by_symbol[symbol], pnl)
        add_trade(by_trend[trend_key], pnl)
        add_trade(by_bias[bias_key], pnl)
        add_trade(by_entry_quality[entry_key], pnl)
        add_trade(by_risk_level[risk_key], pnl)
        add_trade(by_symbol_context[context_key], pnl)

        add_trade(by_market_bias_effective[market_bias_effective_key], pnl)
        add_trade(by_fundamental_score[fundamental_score_key], pnl)
        add_trade(by_session_trend_label[session_trend_key], pnl)
        add_trade(by_prediction_decision[prediction_decision_key], pnl)
        add_trade(by_setup_label[setup_label_key], pnl)
        add_trade(by_setup_policy_action[setup_policy_key], pnl)
        add_trade(by_buy_opportunity_recommendation[buy_opp_key], pnl)

        add_trade(by_symbol_setup_label[symbol_setup_key], pnl)
        add_trade(by_symbol_prediction_decision[symbol_prediction_key], pnl)
        add_trade(by_symbol_buy_opportunity[symbol_buy_opp_key], pnl)
        add_trade(by_symbol_session_trend[symbol_session_key], pnl)

    for r in bar_pattern_rows:
        symbol = r["symbol"] or "UNKNOWN"
        label = r["pattern_label"] or "unknown"
        opportunity = "|".join(
            [
                r["opportunity_action"] or "unknown",
                r["opportunity_quality"] or "unknown",
            ]
        )
        add_pattern_row(by_bar_pattern_label[label], r)
        add_pattern_row(by_bar_pattern_opportunity[opportunity], r)
        add_pattern_row(by_symbol_bar_pattern_label[f"{symbol}|{label}"], r)
        add_pattern_row(by_symbol_bar_pattern_opportunity[f"{symbol}|{opportunity}"], r)

    memory = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lookback_days": LOOKBACK_DAYS,
        "min_trades_required": MIN_TRADES_REQUIRED,
        "rules": {
            "favor": "positive expectancy and acceptable win rate; does not increase hard risk caps",
            "neutral": "mixed results; normal behavior",
            "caution": "negative expectancy; require stronger setup quality",
            "avoid": "poor recent expectancy; require premium setup quality",
            "observe": "not enough sample size to influence live gate",
        },
        "symbols": {k: finalize_bucket(v) for k, v in sorted(by_symbol.items())},
        "trend_context": {k: finalize_bucket(v) for k, v in sorted(by_trend.items())},
        "market_bias_context": {k: finalize_bucket(v) for k, v in sorted(by_bias.items())},
        "entry_quality_context": {
            k: finalize_bucket(v) for k, v in sorted(by_entry_quality.items())
        },
        "risk_level_context": {k: finalize_bucket(v) for k, v in sorted(by_risk_level.items())},
        "market_bias_effective_context": {
            k: finalize_bucket(v) for k, v in sorted(by_market_bias_effective.items())
        },
        "fundamental_score_context": {
            k: finalize_bucket(v) for k, v in sorted(by_fundamental_score.items())
        },
        "session_trend_context": {
            k: finalize_bucket(v) for k, v in sorted(by_session_trend_label.items())
        },
        "prediction_decision_context": {
            k: finalize_bucket(v) for k, v in sorted(by_prediction_decision.items())
        },
        "setup_label_context": {k: finalize_bucket(v) for k, v in sorted(by_setup_label.items())},
        "setup_policy_context": {
            k: finalize_bucket(v) for k, v in sorted(by_setup_policy_action.items())
        },
        "buy_opportunity_context": {
            k: finalize_bucket(v) for k, v in sorted(by_buy_opportunity_recommendation.items())
        },
        "symbol_setup_label_context": {
            k: finalize_bucket(v) for k, v in sorted(by_symbol_setup_label.items())
        },
        "symbol_prediction_context": {
            k: finalize_bucket(v) for k, v in sorted(by_symbol_prediction_decision.items())
        },
        "symbol_buy_opportunity_context": {
            k: finalize_bucket(v) for k, v in sorted(by_symbol_buy_opportunity.items())
        },
        "symbol_session_trend_context": {
            k: finalize_bucket(v) for k, v in sorted(by_symbol_session_trend.items())
        },
        "bar_pattern_label_context": {
            k: finalize_pattern_bucket(v) for k, v in sorted(by_bar_pattern_label.items())
        },
        "bar_pattern_opportunity_context": {
            k: finalize_pattern_bucket(v) for k, v in sorted(by_bar_pattern_opportunity.items())
        },
        "symbol_bar_pattern_label_context": {
            k: finalize_pattern_bucket(v) for k, v in sorted(by_symbol_bar_pattern_label.items())
        },
        "symbol_bar_pattern_opportunity_context": {
            k: finalize_pattern_bucket(v)
            for k, v in sorted(by_symbol_bar_pattern_opportunity.items())
        },
        "symbol_context": {k: finalize_bucket(v) for k, v in sorted(by_symbol_context.items())},
        "report_memories": load_report_memories(),
        "trade_count": len(rows),
        "bar_pattern_rows": len(bar_pattern_rows),
        "bar_pattern_runtime_effect": "observe_only_pattern_learning_no_live_authority",
    }

    memory = apply_manual_overrides(memory)

    snapshot_path = archive_strategy_memory(memory)

    atomic_write_json(OUT_FILE, memory)

    if snapshot_path:
        print(f"Archived strategy memory: {snapshot_path}")
    print(f"Wrote {OUT_FILE}")
    print(f"Closed trades analyzed: {len(rows)}")

    avoid = [
        (sym, data) for sym, data in memory["symbols"].items() if data["recommendation"] == "avoid"
    ]
    caution = [
        (sym, data)
        for sym, data in memory["symbols"].items()
        if data["recommendation"] == "caution"
    ]
    favor = [
        (sym, data) for sym, data in memory["symbols"].items() if data["recommendation"] == "favor"
    ]

    print(f"Favor symbols  : {[s for s, _ in favor]}")
    print(f"Caution symbols: {[s for s, _ in caution]}")
    print(f"Avoid symbols  : {[s for s, _ in avoid]}")


if __name__ == "__main__":
    main()
