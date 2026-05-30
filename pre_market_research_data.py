#!/usr/bin/env python3
"""
No-Claude pre-market research.

Builds market_context.json-compatible research from Alpaca market data only.
No Anthropic calls. No web_search. No model dependency.

Designed for reliable cron use:
- deterministic
- fast
- conservative on missing data
- writes /tmp samples safely
- only writes live market_context.json when explicitly targeted or when no
  --build-output is provided
"""

import argparse
import json
import logging
import os
import time
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from symbols_config import APPROVED_SYMBOLS_LIST
from market_intelligence.raw_research_template import build_template
from market_intelligence.research_output import raw_research_summary
from market_intelligence.market_brief_builder import (
    build_market_brief,
    write_market_context,
    summary_for_brief,
)
from market_intelligence.intelligence_store import ingest_market_context
from alerts import send_alert
from db import DB_PATH, get_connection

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR / "market_context.json"

PRE_MARKET_ALPACA_SYMBOL_SLEEP_SECONDS = float(
    os.getenv("PRE_MARKET_ALPACA_SYMBOL_SLEEP_SECONDS", "0.35")
)
PRE_MARKET_ALPACA_MAX_SYMBOLS = int(
    os.getenv("PRE_MARKET_ALPACA_MAX_SYMBOLS", "0")
)

PRE_MARKET_ALPACA_FETCH_DAILY_BARS = os.getenv(
    "PRE_MARKET_ALPACA_FETCH_DAILY_BARS", "true"
).strip().lower() in ("1", "true", "yes", "on")
PRE_MARKET_ALPACA_FETCH_MINUTE_BARS = os.getenv(
    "PRE_MARKET_ALPACA_FETCH_MINUTE_BARS", "true"
).strip().lower() in ("1", "true", "yes", "on")
PRE_MARKET_ALPACA_SKIP_MINUTE_IF_DAILY_FAILS = os.getenv(
    "PRE_MARKET_ALPACA_SKIP_MINUTE_IF_DAILY_FAILS", "true"
).strip().lower() in ("1", "true", "yes", "on")
PRE_MARKET_ALPACA_DAILY_LOOKBACK_DAYS = int(
    os.getenv("PRE_MARKET_ALPACA_DAILY_LOOKBACK_DAYS", "7")
)
PRE_MARKET_ALPACA_MINUTE_LOOKBACK_HOURS = float(
    os.getenv("PRE_MARKET_ALPACA_MINUTE_LOOKBACK_HOURS", "3")
)
ENV_FILE = Path("/etc/trading-bot.env")

SYMBOLS = APPROVED_SYMBOLS_LIST
INDEX_SYMBOLS = ("SPY", "QQQ", "IWM", "GLD")

SECTOR_GROUPS = {
    "mega_cap_tech": ("AAPL", "MSFT", "NVDA", "META", "AMD", "GOOGL", "AVGO", "ASML"),
    "semiconductors": ("NVDA", "AMD", "AVGO", "ASML", "CRDO", "TSM"),
    "cloud_software": ("CRM", "OKTA", "ZS", "SNPS", "ADSK", "MDB", "ORCL", "NTAP", "DELL"),
    "energy": ("CVX", "XOM"),
    "industrials": ("CAT", "LIN", "GE", "GEV", "HWM", "VRT", "BE"),
    "defense": ("RKLB", "RTX", "LMT", "HWM"),
    "healthcare_biotech": ("VRTX", "MRNA", "CRSP", "LLY", "ABBV", "MRK", "UNH", "PFE"),
    "consumer_retail": ("TSCO", "TSLA", "NFLX", "COST", "KO", "DKS", "BURL", "AMZN"),
    "payments": ("V", "MA", "PYPL"),
    "fintech_banking": ("SOFI", "JPM"),
    "telecom_media": ("T", "VZ", "CMCSA"),
    # SPY, QQQ, IWM, GLD are index/commodity ETFs — intentionally excluded from sector groups
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("pre_market_research_data")


def load_env_if_needed():
    if os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_SECRET_KEY"):
        return

    if not ENV_FILE.exists():
        raise SystemExit(f"ERROR: Alpaca env vars missing and {ENV_FILE} not found")

    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    logger.info(f"Loaded env from {ENV_FILE}")


load_env_if_needed()

from services.market_data_service import market_data_service  # noqa: E402


def pct_change(old, new):
    try:
        old = float(old)
        new = float(new)
        if old <= 0:
            return None
        return (new - old) / old * 100
    except Exception:
        return None


def safe_round(v, digits=3):
    return None if v is None else round(float(v), digits)


def unique_price_levels(levels, digits=2, limit=3):
    seen = set()
    out = []
    for level in levels:
        if level is None:
            continue
        rounded = round(float(level), digits)
        if rounded <= 0 or rounded in seen:
            continue
        seen.add(rounded)
        out.append(rounded)
        if len(out) >= limit:
            break
    return out


def get_recent_bars(symbol):
    """Return lightweight recent data from Alpaca IEX feed."""
    out = {
        "symbol": symbol,
        "daily_pct": None,
        "intraday_pct": None,
        "momentum_30m_pct": None,
        "last_price": None,
        "support_levels": [],
        "resistance_levels": [],
        "bar_count_1m": 0,
        "error": None,
    }

    now = datetime.now(timezone.utc)

    daily_failed = False

    if PRE_MARKET_ALPACA_FETCH_DAILY_BARS:
        try:
            daily_start = (now - timedelta(days=PRE_MARKET_ALPACA_DAILY_LOOKBACK_DAYS)).isoformat()
            daily_bars = market_data_service.get_bars_with_fallback(
                symbol, "1Day", start=daily_start, feed="iex"
            )
            if len(daily_bars) >= 2:
                prev = daily_bars[-2]
                last = daily_bars[-1]
                out["daily_pct"] = pct_change(float(prev.c), float(last.c))
                out["last_price"] = float(last.c)
            elif len(daily_bars) == 1:
                out["last_price"] = float(daily_bars[-1].c)

            recent_daily = daily_bars[-5:]
            daily_supports = sorted((float(b.l) for b in recent_daily), reverse=True)
            daily_resistances = sorted((float(b.h) for b in recent_daily))
            out["support_levels"] = unique_price_levels(daily_supports)
            out["resistance_levels"] = unique_price_levels(daily_resistances)
        except Exception as e:
            daily_failed = True
            out["error"] = f"daily bars failed: {e}"

    should_fetch_minute = PRE_MARKET_ALPACA_FETCH_MINUTE_BARS and not (
        daily_failed and PRE_MARKET_ALPACA_SKIP_MINUTE_IF_DAILY_FAILS
    )

    if should_fetch_minute:
        try:
            minute_start = (now - timedelta(hours=PRE_MARKET_ALPACA_MINUTE_LOOKBACK_HOURS)).isoformat()
            minute_bars = market_data_service.get_bars_with_fallback(
                symbol, "1Min", start=minute_start, feed="iex"
            )
            minute_bars = minute_bars[-120:]
            out["bar_count_1m"] = len(minute_bars)

            if len(minute_bars) >= 2:
                first = float(minute_bars[0].c)
                last = float(minute_bars[-1].c)
                out["intraday_pct"] = pct_change(first, last)
                out["last_price"] = last

            if len(minute_bars) >= 30:
                first_30 = float(minute_bars[-30].c)
                last_30 = float(minute_bars[-1].c)
                out["momentum_30m_pct"] = pct_change(first_30, last_30)

            if minute_bars:
                minute_support = min(float(b.l) for b in minute_bars)
                minute_resistance = max(float(b.h) for b in minute_bars)
                out["support_levels"] = unique_price_levels(
                    [minute_support] + out["support_levels"]
                )
                out["resistance_levels"] = unique_price_levels(
                    [minute_resistance] + out["resistance_levels"]
                )

        except Exception as e:
            if out["error"]:
                out["error"] += f"; minute bars failed: {e}"
            else:
                out["error"] = f"minute bars failed: {e}"
    elif PRE_MARKET_ALPACA_FETCH_MINUTE_BARS and daily_failed:
        out["minute_fetch_skipped"] = "daily_failed"

    if out["last_price"]:
        last_price = float(out["last_price"])
        supports = [level for level in out["support_levels"] if level <= last_price]
        resistances = [level for level in out["resistance_levels"] if level >= last_price]
        out["support_levels"] = unique_price_levels(supports + [last_price * 0.99])
        out["resistance_levels"] = unique_price_levels(resistances + [last_price * 1.01])
        if not out["support_levels"]:
            out["support_levels"] = unique_price_levels([last_price * 0.99])
        if not out["resistance_levels"]:
            out["resistance_levels"] = unique_price_levels([last_price * 1.01])

    return out


def classify_macro(market):
    spy = market.get("SPY", {})
    qqq = market.get("QQQ", {})
    iwm = market.get("IWM", {})
    gld = market.get("GLD", {})

    spy_mom = spy.get("intraday_pct")
    qqq_mom = qqq.get("intraday_pct")
    iwm_mom = iwm.get("intraday_pct")
    gld_mom = gld.get("intraday_pct")

    risk_assets = [v for v in (spy_mom, qqq_mom, iwm_mom) if v is not None]
    risk_avg = sum(risk_assets) / len(risk_assets) if risk_assets else 0.0

    if risk_avg >= 0.35 and (gld_mom is None or gld_mom < 0.5):
        return "risk-on", "risk_on", 1.0, 8, False, "Index momentum is positive across risk assets."
    if risk_avg <= -0.35:
        return "risk-off", "defensive", 0.5, 4, False, "Index momentum is negative; using defensive sizing."
    if risk_avg <= -0.15:
        return "mixed", "caution", 0.75, 6, False, "Index momentum is mildly negative/mixed; using caution sizing."

    return "mixed", "caution", 0.75, 6, False, "Index context is mixed or incomplete; using caution defaults."


def trend_from_pct(pct):
    if pct is None:
        return "mixed"
    if pct >= 0.35:
        return "up"
    if pct <= -0.35:
        return "down"
    return "mixed"


def average_present(values):
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present) / len(present)


def describe_snapshot(data):
    bits = []
    daily = data.get("daily_pct")
    intra = data.get("intraday_pct")
    mom30 = data.get("momentum_30m_pct")
    bars = data.get("bar_count_1m", 0)

    if daily is not None:
        bits.append(f"daily={daily:+.2f}%")
    if intra is not None:
        bits.append(f"intraday={intra:+.2f}%")
    if mom30 is not None:
        bits.append(f"30m={mom30:+.2f}%")
    bits.append(f"1m_bars={bars}")
    return ", ".join(bits)


def build_index_state(market_data):
    index_state = {}
    for symbol in INDEX_SYMBOLS:
        data = market_data.get(symbol, {})
        reference_pct = data.get("intraday_pct")
        if reference_pct is None:
            reference_pct = data.get("daily_pct")

        index_state[symbol] = {
            "trend": trend_from_pct(reference_pct),
            "premarket_gap_pct": safe_round(data.get("intraday_pct")),
            "above_vwap": None,
            "key_levels": [],
            "notes": f"Data-only Alpaca context: {describe_snapshot(data)}.",
        }

    return index_state


def build_sector_state(market_data):
    sector_state = {}
    for sector, symbols in SECTOR_GROUPS.items():
        snapshots = [market_data.get(sym, {}) for sym in symbols if sym in market_data]
        daily_avg = average_present(s.get("daily_pct") for s in snapshots)
        intra_avg = average_present(s.get("intraday_pct") for s in snapshots)
        mom_avg = average_present(s.get("momentum_30m_pct") for s in snapshots)

        reference_pct = intra_avg if intra_avg is not None else daily_avg
        trend = trend_from_pct(reference_pct)
        risk = "medium"
        if reference_pct is not None and reference_pct <= -0.75:
            risk = "high"
        elif reference_pct is not None and reference_pct >= 0.75:
            risk = "low"

        coverage = sum(1 for s in snapshots if s.get("daily_pct") is not None or s.get("intraday_pct") is not None)
        note_bits = [f"coverage={coverage}/{len(symbols)}"]
        if daily_avg is not None:
            note_bits.append(f"avg_daily={daily_avg:+.2f}%")
        if intra_avg is not None:
            note_bits.append(f"avg_intraday={intra_avg:+.2f}%")
        if mom_avg is not None:
            note_bits.append(f"avg_30m={mom_avg:+.2f}%")

        sector_state[sector] = {
            "trend": trend,
            "risk": risk,
            "notes": "Data-only Alpaca context: " + ", ".join(note_bits) + ".",
        }

    return sector_state


def classify_symbol(symbol, data, macro_sentiment):
    daily = data.get("daily_pct")
    intra = data.get("intraday_pct")
    mom30 = data.get("momentum_30m_pct")
    bars = data.get("bar_count_1m", 0)

    reason_bits = []

    if data.get("error") and daily is None and intra is None:
        return {
            "bias": "neutral",
            "reason": f"No reliable Alpaca market-data read; {data.get('error')}",
            "confidence": "low",
            "fundamental_score": "neutral",
            "risk_level": "medium",
            "entry_quality": "conditional",
            "avoid_type": None,
        }

    if daily is not None:
        reason_bits.append(f"daily={daily:+.2f}%")
    if intra is not None:
        reason_bits.append(f"intraday={intra:+.2f}%")
    if mom30 is not None:
        reason_bits.append(f"30m={mom30:+.2f}%")

    reason = ", ".join(reason_bits) if reason_bits else "Limited Alpaca data; conservative neutral."

    # Conservative avoid rules.
    if intra is not None and intra <= -1.0:
        return {
            "bias": "avoid",
            "reason": f"Negative pre-market/intraday tape: {reason}",
            "confidence": "medium",
            "fundamental_score": "neutral",
            "risk_level": "high",
            "entry_quality": "conditional",
            "avoid_type": "soft",
        }

    if daily is not None and daily <= -2.0:
        return {
            "bias": "avoid",
            "reason": f"Weak recent daily trend: {reason}",
            "confidence": "medium",
            "fundamental_score": "neutral",
            "risk_level": "high",
            "entry_quality": "conditional",
            "avoid_type": "soft",
        }

    # Chase-prevention: big move up but short-term momentum fading.
    if daily is not None and daily >= 3.0 and mom30 is not None and mom30 < 0:
        return {
            "bias": "avoid",
            "reason": f"Extended daily move with fading short-term tape: {reason}",
            "confidence": "medium",
            "fundamental_score": "neutral",
            "risk_level": "high",
            "entry_quality": "avoid_chasing",
            "avoid_type": "soft",
        }

    # Buy rules: only if broader tape is not risk-off.
    if macro_sentiment != "risk-off":
        if intra is not None and intra >= 0.45 and (mom30 is None or mom30 >= 0.10):
            return {
                "bias": "buy",
                "reason": f"Positive live tape and short-term momentum: {reason}",
                "confidence": "medium" if bars >= 20 else "low",
                "fundamental_score": "neutral",
                "risk_level": "medium",
                "entry_quality": "good_if_holds_gap",
                "avoid_type": None,
            }

        if daily is not None and daily >= 1.25 and (intra is None or intra >= -0.20):
            return {
                "bias": "buy",
                "reason": f"Positive recent trend without major tape weakness: {reason}",
                "confidence": "low",
                "fundamental_score": "neutral",
                "risk_level": "medium",
                "entry_quality": "good_on_pullbacks",
                "avoid_type": None,
            }

        # Weak-buy: modest positive daily trend, tape not negative.
        # Stays bias=neutral but upgrades entry_quality from conditional to
        # good_on_pullbacks, reducing false hits from the conditional entry gate.
        if daily is not None and daily >= 0.75 and (intra is None or intra >= -0.10):
            return {
                "bias": "neutral",
                "reason": f"Modest positive trend — neutral bias, wait for pullback entry: {reason}",
                "confidence": "low",
                "fundamental_score": "neutral",
                "risk_level": "medium",
                "entry_quality": "good_on_pullbacks",
                "avoid_type": None,
            }

    return {
        "bias": "neutral",
        "reason": f"No decisive data-only edge: {reason}",
        "confidence": "low",
        "fundamental_score": "neutral",
        "risk_level": "medium",
        "entry_quality": "conditional",
        "avoid_type": None,
    }


def build_symbol_evidence(data, classification, macro_sentiment, macro_regime):
    daily = data.get("daily_pct")
    intra = data.get("intraday_pct")
    mom30 = data.get("momentum_30m_pct")
    bars = data.get("bar_count_1m", 0)
    bias = classification.get("bias")

    catalysts = []
    risks = []

    if daily is not None and daily >= 1.25:
        catalysts.append(f"Positive recent daily trend ({daily:+.2f}%).")
    if intra is not None and intra >= 0.35:
        catalysts.append(f"Positive premarket/intraday tape ({intra:+.2f}%).")
    if mom30 is not None and mom30 >= 0.10:
        catalysts.append(f"Positive 30-minute momentum ({mom30:+.2f}%).")
    if bias == "buy":
        catalysts.append(f"Data-only classifier bias is buy: {classification.get('entry_quality')}.")
    if not catalysts:
        catalysts.append("No strong data-only catalyst; waiting for live confirmation.")

    if daily is not None and daily <= -2.0:
        risks.append(f"Weak recent daily trend ({daily:+.2f}%).")
    if intra is not None and intra <= -0.35:
        risks.append(f"Negative premarket/intraday tape ({intra:+.2f}%).")
    if mom30 is not None and mom30 < 0:
        risks.append(f"Short-term momentum fading ({mom30:+.2f}%).")
    if bars < 10:
        risks.append(f"Limited premarket 1-minute bar coverage ({bars} bars).")
    if macro_sentiment != "risk-on":
        risks.append(f"Macro context is {macro_sentiment}/{macro_regime}; use confirmation.")
    if bias == "avoid":
        risks.append(f"Data-only classifier bias is avoid: {classification.get('reason')}.")
    if not risks:
        risks.append("No major data-only risk flagged before open.")

    return {
        "key_catalysts": catalysts[:4],
        "key_risks": risks[:4],
        "support_levels": data.get("support_levels") or [],
        "resistance_levels": data.get("resistance_levels") or [],
    }


def load_event_enrichment(market_date: str) -> dict:
    """Read event-aggregated daily_symbol_context rows for market_date.

    This is read-only. It enriches market_context.json with already-computed
    intelligence scores but does not create events or affect trading directly.
    """
    try:
        from db import DB_PATH, get_connection
        from market_intelligence.intelligence_store import init_intelligence_tables

        init_intelligence_tables()
        with get_connection(DB_PATH) as con:
            rows = con.execute(
                """
                SELECT symbol,
                       catalyst_score,
                       consumer_appetite_score,
                       revenue_impact_score,
                       profit_potential_score,
                       margin_risk_score,
                       supply_chain_risk_score,
                       materials_risk_score,
                       competitive_risk_score,
                       execution_risk_score
                FROM daily_symbol_context
                WHERE market_date = ?
                """,
                (market_date,),
            ).fetchall()

        out = {}
        for r in rows:
            out[r["symbol"]] = {
                "catalyst_score": r["catalyst_score"],
                "consumer_appetite_score": r["consumer_appetite_score"],
                "revenue_impact_score": r["revenue_impact_score"],
                "profit_potential_score": r["profit_potential_score"],
                "margin_risk_score": r["margin_risk_score"],
                "supply_chain_risk_score": r["supply_chain_risk_score"],
                "materials_risk_score": r["materials_risk_score"],
                "competitive_risk_score": r["competitive_risk_score"],
                "execution_risk_score": r["execution_risk_score"],
            }
        return out
    except Exception as e:
        logger.warning(f"Event enrichment load failed for {market_date}: {e}")
        return {}


def apply_event_enrichment(symbol_entry: dict, enrichment: dict) -> None:
    """Overlay event aggregate scores onto one market-context symbol entry."""
    if not enrichment:
        return

    applied = False
    for key, value in enrichment.items():
        if value is None:
            continue

        if key == "catalyst_score":
            try:
                raw_score = float(value)
                symbol_entry["event_catalyst_score_raw"] = round(raw_score, 2)
                # market_context catalyst_score is normalized/clamped to 0-10.
                symbol_entry["catalyst_score"] = round(max(0.0, min(10.0, raw_score / 10.0)), 2)
            except Exception:
                symbol_entry["event_catalyst_score_raw"] = value
            applied = True
            continue

        symbol_entry[key] = value
        applied = True

    if not applied:
        return

    catalyst_score = enrichment.get("catalyst_score")
    if catalyst_score is not None:
        try:
            catalyst_f = float(catalyst_score)
            catalysts = symbol_entry.setdefault("key_catalysts", [])
            note = f"Event-enriched catalyst score {catalyst_f:.2f} from daily_symbol_context."
            if note not in catalysts:
                catalysts.insert(0, note)
            symbol_entry["notes"] = "event_enriched"
        except Exception:
            pass



def should_write_live(build_output):
    if not build_output:
        return True

    requested = Path(build_output)
    if not requested.is_absolute():
        requested = SCRIPT_DIR / requested

    return requested.resolve() == OUTPUT_FILE.resolve()


def backup_live_context():
    if not OUTPUT_FILE.exists():
        return None

    backup = OUTPUT_FILE.with_name(
        f"{OUTPUT_FILE.name}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    backup.write_text(OUTPUT_FILE.read_text())
    return backup


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return path



def latest_session_momentum(symbol: str) -> dict:
    """Return latest intraday session momentum row for a symbol."""
    try:
        with get_connection(DB_PATH) as con:
            row = con.execute(
                """
                SELECT symbol, updated_at, trend_label, trend_score,
                       session_return_pct, momentum_5m_pct,
                       momentum_15m_pct, momentum_30m_pct,
                       distance_from_vwap_pct, reason
                FROM session_momentum
                WHERE symbol = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}


def get_latest_prediction(symbol: str, market_date: str) -> dict:
    """Return latest daily prediction row for a symbol/date."""
    try:
        with get_connection(DB_PATH) as con:
            row = con.execute(
                """
                SELECT symbol, prediction_score, probability_of_profit,
                       expected_pnl, expected_win_rate, confidence,
                       sample_size, timing_score, recommended_entry_timing,
                       recommended_exit_timing,
                       trend_score, trend_label, trend_regime,
                       trend_confidence, trend_similarity_sample_size,
                       reason, raw_json, updated_at
                FROM daily_symbol_predictions
                WHERE market_date = ?
                  AND symbol = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (market_date, symbol),
            ).fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}


def get_prior_session_context(symbol: str, market_date: str) -> dict:
    """Return most recent prior-session strong-day participation row."""
    try:
        with get_connection(DB_PATH) as con:
            row = con.execute(
                """
                SELECT *
                FROM strong_day_participation
                WHERE symbol = ?
                  AND market_date < ?
                ORDER BY market_date DESC
                LIMIT 1
                """,
                (symbol, market_date),
            ).fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}


def get_strategy_memory_context(symbol: str) -> dict:
    """Return lightweight current strategy-memory/performance context from matched trades."""
    try:
        with get_connection(DB_PATH) as con:
            row = con.execute(
                """
                SELECT
                    COUNT(*) AS trades,
                    SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) AS losses,
                    SUM(COALESCE(realized_pnl, 0)) AS pnl,
                    AVG(realized_pnl) AS expectancy,
                    AVG(realized_pnl_pct) AS avg_pnl_pct
                FROM matched_trades
                WHERE symbol = ?
                """,
                (symbol,),
            ).fetchone()

        trades = int(row["trades"] or 0) if row else 0
        wins = int(row["wins"] or 0) if row else 0
        losses = int(row["losses"] or 0) if row else 0
        pnl = float(row["pnl"] or 0.0) if row else 0.0
        expectancy = float(row["expectancy"] or 0.0) if row else 0.0
        avg_pnl_pct = float(row["avg_pnl_pct"] or 0.0) if row else 0.0
        win_rate = wins / trades if trades else 0.0

        return {
            "trades": trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 4),
            "pnl": round(pnl, 2),
            "expectancy": round(expectancy, 2),
            "avg_pnl_pct": round(avg_pnl_pct, 4),
        }
    except Exception:
        return {}


def enrich_with_session_context(symbol: str, classification: dict, market_date: str) -> dict:
    """Add learning/context fields to one market-context symbol entry.

    This is enrichment, not hard override logic. Core fields remain generated by
    classify_symbol(). The only behavioral adjustment is a narrow confidence
    upgrade from low to medium when live session momentum confirms strength.
    """
    enriched = dict(classification)

    prior = get_prior_session_context(symbol, market_date)
    if prior:
        enriched["prior_session_market_date"] = prior.get("market_date")
        for key in (
            "session_return_pct",
            "mfe_pct",
            "max_favorable_excursion_pct",
            "participated",
            "participation_quality",
            "prediction_score",
            "trend_label",
            "timing_score",
        ):
            if key in prior:
                enriched[f"prior_session_{key}"] = prior.get(key)

    sm = latest_session_momentum(symbol)
    if sm:
        label = sm.get("trend_label")
        session_return = sm.get("session_return_pct")

        enriched["session_momentum_label"] = label
        enriched["session_momentum_score"] = sm.get("trend_score")
        enriched["session_return_pct"] = session_return
        enriched["session_momentum_5m_pct"] = sm.get("momentum_5m_pct")
        enriched["session_momentum_15m_pct"] = sm.get("momentum_15m_pct")
        enriched["session_momentum_30m_pct"] = sm.get("momentum_30m_pct")
        enriched["session_distance_from_vwap_pct"] = sm.get("distance_from_vwap_pct")
        enriched["session_momentum_reason"] = sm.get("reason")

        try:
            session_return_f = float(session_return or 0)
        except Exception:
            session_return_f = 0.0

        if (
            enriched.get("bias") == "neutral"
            and enriched.get("confidence") == "low"
            and label in ("strong_uptrend", "developing_uptrend")
            and session_return_f >= 0.75
        ):
            enriched["confidence"] = "medium"
            enriched["session_momentum_upgrade"] = True
            enriched["session_momentum_upgrade_reason"] = (
                f"Neutral symbol upgraded to medium confidence due to "
                f"{label} session momentum and session_return_pct={session_return_f:.2f}."
            )

    pred = get_latest_prediction(symbol, market_date)
    if pred:
        enriched["prediction_score"] = pred.get("prediction_score")
        enriched["prediction_confidence"] = pred.get("confidence")
        enriched["prediction_expected_pnl"] = pred.get("expected_pnl")
        enriched["prediction_expected_win_rate"] = pred.get("expected_win_rate")
        enriched["prediction_sample_size"] = pred.get("sample_size")
        enriched["prediction_timing_score"] = pred.get("timing_score")
        enriched["prediction_recommended_entry_timing"] = pred.get("recommended_entry_timing")
        enriched["prediction_recommended_exit_timing"] = pred.get("recommended_exit_timing")
        enriched["prediction_trend_score"] = pred.get("trend_score")
        enriched["prediction_trend_label"] = pred.get("trend_label")
        enriched["prediction_trend_regime"] = pred.get("trend_regime")
        enriched["prediction_trend_confidence"] = pred.get("trend_confidence")
        enriched["prediction_reason"] = pred.get("reason")

    mem = get_strategy_memory_context(symbol)
    if mem:
        enriched["strategy_memory_trades"] = mem.get("trades")
        enriched["strategy_memory_wins"] = mem.get("wins")
        enriched["strategy_memory_losses"] = mem.get("losses")
        enriched["strategy_memory_win_rate"] = mem.get("win_rate")
        enriched["strategy_memory_pnl"] = mem.get("pnl")
        enriched["strategy_memory_expectancy"] = mem.get("expectancy")
        enriched["strategy_memory_avg_pnl_pct"] = mem.get("avg_pnl_pct")

    return enriched

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Market date YYYY-MM-DD, default today")
    parser.add_argument("--raw-output", help="Optional raw research output path")
    parser.add_argument("--build-output", help="Optional built market context output path")
    parser.add_argument("--max-symbols", type=int, help="Debug: limit symbols processed")
    parser.add_argument("--ingest-context", action="store_true", help="Store built context in daily_symbol_context")
    args = parser.parse_args()

    started = datetime.now()
    today = args.date or date.today().isoformat()

    symbols = SYMBOLS[: args.max_symbols] if args.max_symbols else SYMBOLS
    if PRE_MARKET_ALPACA_MAX_SYMBOLS > 0:
        symbols = symbols[:PRE_MARKET_ALPACA_MAX_SYMBOLS]
    event_enrichment = load_event_enrichment(today)

    logger.info(f"Running no-Claude data research for {len(symbols)} symbols")
    logger.info(f"Loaded event enrichment for {len(event_enrichment)} symbols")

    market_data = {}
    for i, sym in enumerate(symbols):
        if i > 0 and PRE_MARKET_ALPACA_SYMBOL_SLEEP_SECONDS > 0:
            time.sleep(PRE_MARKET_ALPACA_SYMBOL_SLEEP_SECONDS)
        market_data[sym] = get_recent_bars(sym)

    macro_sentiment, macro_regime, risk_multiplier, max_new_positions, block_new_buys, macro_summary = classify_macro(market_data)

    template = build_template(today)
    template["source"] = "pre_market_research_data_only"
    template["format"] = "raw_research_v1"
    template["generated_at"] = datetime.now().isoformat(timespec="seconds")
    template["macro_sentiment"] = macro_sentiment
    template["macro_regime"] = macro_regime
    template["risk_multiplier"] = risk_multiplier
    template["max_new_positions"] = max_new_positions
    template["block_new_buys"] = block_new_buys
    template["macro_summary"] = macro_summary
    template["index_state"] = build_index_state(market_data)
    template["sector_state"] = build_sector_state(market_data)
    template["data_only"] = len(event_enrichment) == 0
    template["source_quality"] = "event_enriched" if event_enrichment else "data_only"
    template["event_enrichment_count"] = len(event_enrichment)

    symbols_out = template.get("symbols", {})

    for sym in SYMBOLS:
        if sym in market_data:
            classification = classify_symbol(sym, market_data[sym], macro_sentiment)
            classification = enrich_with_session_context(sym, classification, today)
            symbols_out[sym].update(classification)
            symbols_out[sym].update(
                build_symbol_evidence(
                    market_data[sym],
                    classification,
                    macro_sentiment,
                    macro_regime,
                )
            )
            symbols_out[sym]["data_snapshot"] = {
                "daily_pct": safe_round(market_data[sym].get("daily_pct")),
                "intraday_pct": safe_round(market_data[sym].get("intraday_pct")),
                "momentum_30m_pct": safe_round(market_data[sym].get("momentum_30m_pct")),
                "last_price": safe_round(market_data[sym].get("last_price"), 4),
                "bar_count_1m": market_data[sym].get("bar_count_1m", 0),
            }
            apply_event_enrichment(symbols_out[sym], event_enrichment.get(sym) or {})
        else:
            symbols_out[sym].update({
                "bias": "neutral",
                "reason": "Not processed in debug-limited data run.",
                "confidence": "low",
                "fundamental_score": "neutral",
                "risk_level": "medium",
                "entry_quality": "conditional",
                "avoid_type": None,
            })

    template["symbols"] = symbols_out

    raw_path = None
    if args.raw_output:
        raw_path = write_json(args.raw_output, template)
        logger.info(f"Wrote raw data-only research {raw_path}")

    brief = build_market_brief(template)

    built_path = None
    if args.build_output:
        built_path = Path(args.build_output)
        if not built_path.is_absolute():
            built_path = SCRIPT_DIR / built_path
        built_path.parent.mkdir(parents=True, exist_ok=True)
        write_market_context(brief, built_path)
        logger.info(f"Wrote built data-only market context {built_path}")

    live_written = False
    ingest_summary = None
    if should_write_live(args.build_output):
        backup = backup_live_context()
        if backup:
            logger.info(f"Backed up live context to {backup}")
        write_market_context(brief, OUTPUT_FILE)
        logger.info(f"Wrote live market context {OUTPUT_FILE}")
        live_written = True
    else:
        logger.info(f"Skipped live {OUTPUT_FILE} write because --build-output targets {args.build_output}")

    if args.ingest_context:
        ingest_target = built_path if built_path else OUTPUT_FILE
        ingest_summary = ingest_market_context(ingest_target)
        logger.info(
            f"Ingested market context into daily_symbol_context: "
            f"{ingest_summary['symbols']} symbols for {ingest_summary['market_date']}"
        )

    try:
        if args.ingest_context and ingest_summary:
            send_alert(
                title="Pre-market research complete",
                message=(
                    f"Built market context for {today}: "
                    f"{ingest_summary.get('symbols')} symbols ingested."
                ),
                severity="info",
                source="pre_market_research_data.py",
                payload={
                    "market_date": today,
                    "macro_sentiment": macro_sentiment,
                    "macro_regime": macro_regime,
                    "risk_multiplier": risk_multiplier,
                    "max_new_positions": max_new_positions,
                    "block_new_buys": block_new_buys,
                    "raw_output": str(raw_path) if raw_path else None,
                    "built_output": str(built_path) if built_path else None,
                    "live_written": live_written,
                    "ingest_summary": ingest_summary,
                },
            )
    except Exception:
        pass

    elapsed = (datetime.now() - started).total_seconds()
    bias_counts = Counter((e or {}).get("bias", "missing") for e in template["symbols"].values())

    print()
    print("=== No-Claude pre-market research complete ===")
    print(f"  Date        : {today}")
    print(f"  Elapsed     : {elapsed:.1f}s")
    print(f"  Macro       : {macro_sentiment} / {macro_regime}")
    print(f"  Risk mult   : {risk_multiplier}")
    print(f"  Max pos     : {max_new_positions}")
    print(f"  Bias counts : {dict(bias_counts)}")
    print(f"  Raw output  : {raw_path or '(not written)'}")
    print(f"  Raw summary : {raw_research_summary(template)}")
    print(f"  Built output: {built_path or '(not written)'}")
    print(f"  Built summary: {summary_for_brief(brief)}")
    print(f"  Live output : {OUTPUT_FILE if live_written else '(not modified)'}")
    print(f"  DB ingest   : {ingest_summary if ingest_summary else '(not requested)'}")
    print()
    print(f"  {'Symbol':<7} {'Bias':<8} {'Conf':<7} {'Risk':<10} {'Entry':<22} Reason")
    print(f"  {'-'*7} {'-'*8} {'-'*7} {'-'*10} {'-'*22} {'-'*60}")

    for sym in SYMBOLS:
        e = template["symbols"].get(sym, {})
        print(
            f"  {sym:<7} "
            f"{e.get('bias', '-'):<8} "
            f"{e.get('confidence', '-'):<7} "
            f"{str(e.get('risk_level') or '-'):<10} "
            f"{str(e.get('entry_quality') or '-'):<22} "
            f"{(e.get('reason') or '')[:80]}"
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        try:
            send_alert(
                title="Pre-market research failed",
                message=str(exc),
                severity="error",
                source="pre_market_research_data.py",
                payload={"error": str(exc)},
            )
        except Exception:
            pass
        raise
