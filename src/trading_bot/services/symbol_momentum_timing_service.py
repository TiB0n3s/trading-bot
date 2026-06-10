"""Analyze intraday symbol momentum timing from feature snapshots."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime
from typing import Any

import pytz
from repositories.symbol_momentum_timing_repo import SymbolMomentumTimingRepository

ET = pytz.timezone("America/New_York")


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def rounded(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def avg(values: list[float | None]) -> float:
    vals = [float(v) for v in values if v is not None]
    return statistics.mean(vals) if vals else 0.0


def pct(n: int, d: int) -> float:
    return round(n / d * 100.0, 1) if d else 0.0


def _time_bucket(timestamp: str | None) -> str:
    if not timestamp:
        return "unknown"
    try:
        dt = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return "unknown"
    hour_min = dt.hour * 60 + dt.minute
    if hour_min < 10 * 60:
        return "open_0930_1000"
    if hour_min < 11 * 60:
        return "morning_1000_1100"
    if hour_min < 13 * 60 + 30:
        return "midday_1100_1330"
    if hour_min < 15 * 60:
        return "afternoon_1330_1500"
    return "late_1500_close"


def long_state_score(row: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    ret5 = safe_float(row.get("ret_5m"), 0.0) or 0.0
    ret15 = safe_float(row.get("ret_15m"), 0.0) or 0.0
    vwap = safe_float(row.get("distance_from_vwap"), 0.0) or 0.0
    range_pos = safe_float(row.get("range_pos_15m"))
    volume = safe_float(row.get("volume_ratio_5m"), 0.0) or 0.0
    rel_strength = safe_float(row.get("relative_strength_5m"), 0.0) or 0.0
    setup_label = str(row.get("setup_label") or "").lower()

    if ret5 > 0:
        score += 1
        reasons.append("ret5_positive")
    if ret15 > 0:
        score += 2
        reasons.append("ret15_positive")
    if 0.0 <= vwap <= 1.50:
        score += 2
        reasons.append("constructive_vwap")
    elif -0.35 <= vwap < 0:
        score += 1
        reasons.append("near_vwap_reclaim_zone")
    elif vwap > 2.0:
        score -= 2
        reasons.append("extended_above_vwap")
    elif vwap < -2.0:
        score -= 1
        reasons.append("far_below_vwap")

    if range_pos is not None and 0.45 <= range_pos <= 0.90:
        score += 1
        reasons.append("healthy_15m_range_position")
    elif range_pos is not None and range_pos > 0.95:
        score -= 1
        reasons.append("near_15m_high_chase")

    if volume >= 1.20:
        score += 1
        reasons.append("volume_confirmation")
    if rel_strength > 0.05:
        score += 1
        reasons.append("relative_strength")
    if setup_label.startswith("avoid"):
        score -= 2
        reasons.append("setup_avoid_label")

    return score, reasons


def short_state_score(row: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    ret5 = safe_float(row.get("ret_5m"), 0.0) or 0.0
    ret15 = safe_float(row.get("ret_15m"), 0.0) or 0.0
    vwap = safe_float(row.get("distance_from_vwap"), 0.0) or 0.0
    range_pos = safe_float(row.get("range_pos_15m"))
    volume = safe_float(row.get("volume_ratio_5m"), 0.0) or 0.0
    rel_strength = safe_float(row.get("relative_strength_5m"), 0.0) or 0.0

    if ret5 < 0:
        score += 1
        reasons.append("ret5_negative")
    if ret15 < 0:
        score += 2
        reasons.append("ret15_negative")
    if -1.50 <= vwap <= -0.05:
        score += 2
        reasons.append("below_vwap_pressure")
    elif vwap < -2.0:
        score -= 1
        reasons.append("extended_below_vwap")
    elif vwap > 0.75:
        score -= 1
        reasons.append("above_vwap_strength")

    if range_pos is not None and 0.10 <= range_pos <= 0.55:
        score += 1
        reasons.append("weak_15m_range_position")
    elif range_pos is not None and range_pos < 0.05:
        score -= 1
        reasons.append("near_15m_low_chase")

    if volume >= 1.20:
        score += 1
        reasons.append("volume_confirmation")
    if rel_strength < -0.05:
        score += 1
        reasons.append("relative_weakness")

    return score, reasons


def _hindsight_return(row: dict[str, Any]) -> float | None:
    ret30 = safe_float(row.get("ret_fwd_30m"))
    if ret30 is not None:
        return ret30
    return safe_float(row.get("ret_fwd_15m"))


def _window_payload(row: dict[str, Any], *, direction: str) -> dict[str, Any]:
    if direction == "long":
        state_score, reasons = long_state_score(row)
    else:
        state_score, reasons = short_state_score(row)
    return {
        "timestamp": row.get("timestamp"),
        "time_bucket": _time_bucket(row.get("timestamp")),
        "symbol": row.get("symbol"),
        "last_price": rounded(safe_float(row.get("last_price")), 4),
        "setup_label": row.get("setup_label"),
        "setup_score": row.get("setup_score"),
        "state_score": state_score,
        "state_reasons": reasons,
        "ret_5m": rounded(safe_float(row.get("ret_5m"))),
        "ret_15m": rounded(safe_float(row.get("ret_15m"))),
        "distance_from_vwap": rounded(safe_float(row.get("distance_from_vwap"))),
        "range_pos_15m": rounded(safe_float(row.get("range_pos_15m"))),
        "volume_ratio_5m": rounded(safe_float(row.get("volume_ratio_5m"))),
        "relative_strength_5m": rounded(safe_float(row.get("relative_strength_5m"))),
        "ret_fwd_5m": rounded(safe_float(row.get("ret_fwd_5m"))),
        "ret_fwd_15m": rounded(safe_float(row.get("ret_fwd_15m"))),
        "ret_fwd_30m": rounded(safe_float(row.get("ret_fwd_30m"))),
        "max_up_15m": rounded(safe_float(row.get("max_up_15m"))),
        "max_down_15m": rounded(safe_float(row.get("max_down_15m"))),
        "outcome_label": row.get("outcome_label"),
        "label_horizon_status": row.get("label_horizon_status"),
    }


def _bucket(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    long_wins = sum(1 for r in rows if (safe_float(r.get("ret_fwd_15m")) or 0.0) >= 0.10)
    short_wins = sum(1 for r in rows if (safe_float(r.get("ret_fwd_15m")) or 0.0) <= -0.10)
    return {
        "rows": n,
        "avg_ret_fwd_15m": rounded(avg([safe_float(r.get("ret_fwd_15m")) for r in rows])),
        "avg_ret_fwd_30m": rounded(avg([safe_float(r.get("ret_fwd_30m")) for r in rows])),
        "avg_distance_from_vwap": rounded(
            avg([safe_float(r.get("distance_from_vwap")) for r in rows])
        ),
        "long_win_rate_15m_pct": pct(long_wins, n),
        "short_win_rate_15m_pct": pct(short_wins, n),
    }


def _recommendation(
    *,
    avg_fwd15: float,
    long_windows: int,
    short_windows: int,
    complete_rows: int,
) -> tuple[str, str]:
    if complete_rows < 20:
        return "observe", f"sample too small: {complete_rows} complete rows"
    if avg_fwd15 >= 0.12 and long_windows >= short_windows * 1.2:
        return "favor_long_pullbacks", f"positive avg_fwd15={avg_fwd15:.3f}% with more long windows"
    if avg_fwd15 <= -0.08 and short_windows >= long_windows * 1.2:
        return (
            "favor_short_or_sell_rallies",
            f"negative avg_fwd15={avg_fwd15:.3f}% with more short windows",
        )
    if long_windows >= 40 and short_windows >= 40:
        return (
            "two_sided_timing_required",
            "both long and short windows appeared; require local confirmation",
        )
    return "neutral", f"mixed timing profile avg_fwd15={avg_fwd15:.3f}%"


class SymbolMomentumTimingService:
    def __init__(self, *, repository: SymbolMomentumTimingRepository):
        self.repository = repository

    def load_rows(
        self,
        target_date: str,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.repository.load_feature_label_rows(target_date, symbol=symbol, limit=limit)

    def analyze_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        target_date: str,
        top_n: int = 5,
    ) -> dict[str, Any]:
        by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_setup: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_time_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
        complete_rows = []

        for row in rows:
            symbol = str(row.get("symbol") or "UNKNOWN").upper()
            setup = row.get("setup_label") or "unknown"
            by_symbol[symbol].append(row)
            by_setup[setup].append(row)
            by_time_bucket[_time_bucket(row.get("timestamp"))].append(row)
            if row.get("label_horizon_status") == "complete":
                complete_rows.append(row)

        symbol_memory: dict[str, Any] = {}
        all_best_longs: list[dict[str, Any]] = []
        all_best_shorts: list[dict[str, Any]] = []

        for symbol, sym_rows in sorted(by_symbol.items()):
            labeled = [r for r in sym_rows if _hindsight_return(r) is not None]
            complete = [r for r in sym_rows if r.get("label_horizon_status") == "complete"]
            if not sym_rows:
                continue

            first = safe_float(sym_rows[0].get("last_price"))
            last = safe_float(sym_rows[-1].get("last_price"))
            session_return = None
            if first and last:
                session_return = (last - first) / first * 100.0

            long_state_rows = [r for r in sym_rows if long_state_score(r)[0] >= 5]
            short_state_rows = [r for r in sym_rows if short_state_score(r)[0] >= 5]
            avg_fwd15 = avg([safe_float(r.get("ret_fwd_15m")) for r in labeled])
            recommendation, reason = _recommendation(
                avg_fwd15=avg_fwd15,
                long_windows=len(long_state_rows),
                short_windows=len(short_state_rows),
                complete_rows=len(complete),
            )

            best_longs = sorted(
                labeled,
                key=lambda r: _hindsight_return(r) if _hindsight_return(r) is not None else -999.0,
                reverse=True,
            )[:top_n]
            best_shorts = sorted(
                labeled,
                key=lambda r: _hindsight_return(r) if _hindsight_return(r) is not None else 999.0,
            )[:top_n]

            long_payloads = [_window_payload(r, direction="long") for r in best_longs]
            short_payloads = [_window_payload(r, direction="short") for r in best_shorts]
            all_best_longs.extend(long_payloads)
            all_best_shorts.extend(short_payloads)

            symbol_memory[symbol] = {
                "rows": len(sym_rows),
                "complete_rows": len(complete),
                "session_return_pct": rounded(session_return),
                "avg_ret_15m": rounded(avg([safe_float(r.get("ret_15m")) for r in sym_rows])),
                "avg_ret_fwd_15m": rounded(avg_fwd15),
                "avg_ret_fwd_30m": rounded(
                    avg([safe_float(r.get("ret_fwd_30m")) for r in labeled])
                ),
                "long_state_windows": len(long_state_rows),
                "short_state_windows": len(short_state_rows),
                "max_long_state_score": max((long_state_score(r)[0] for r in sym_rows), default=0),
                "max_short_state_score": max(
                    (short_state_score(r)[0] for r in sym_rows), default=0
                ),
                "recommendation": recommendation,
                "reason": reason,
                "best_long_windows": long_payloads,
                "best_short_windows": short_payloads,
            }

        setup_memory = {
            setup: _bucket(setup_rows) for setup, setup_rows in sorted(by_setup.items())
        }
        time_bucket_memory = {
            bucket: _bucket(bucket_rows) for bucket, bucket_rows in sorted(by_time_bucket.items())
        }

        top_long_windows = sorted(
            all_best_longs,
            key=lambda r: (
                safe_float(r.get("ret_fwd_30m"), safe_float(r.get("ret_fwd_15m"), -999.0)) or -999.0
            ),
            reverse=True,
        )[:25]
        top_short_windows = sorted(
            all_best_shorts,
            key=lambda r: (
                safe_float(r.get("ret_fwd_30m"), safe_float(r.get("ret_fwd_15m"), 999.0)) or 999.0
            ),
        )[:25]

        return {
            "generated_at": datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S"),
            "date": target_date,
            "source": "feature_snapshots+labeled_setups",
            "row_count": len(rows),
            "complete_row_count": len(complete_rows),
            "symbol_count": len(by_symbol),
            "method": {
                "long_state_threshold": 5,
                "short_state_threshold": 5,
                "hindsight_target": "ret_fwd_30m_with_ret_fwd_15m_fallback",
                "purpose": "post-session timing intelligence for future predictions; not a same-session execution signal",
            },
            "symbol_memory": symbol_memory,
            "setup_memory": setup_memory,
            "time_bucket_memory": time_bucket_memory,
            "top_long_windows": top_long_windows,
            "top_short_windows": top_short_windows,
        }

    def analyze(
        self,
        *,
        target_date: str,
        symbol: str | None = None,
        limit: int | None = None,
        top_n: int = 5,
    ) -> dict[str, Any]:
        rows = self.load_rows(target_date, symbol=symbol, limit=limit)
        return self.analyze_rows(rows, target_date=target_date, top_n=top_n)


def build_default_symbol_momentum_timing_service(db_path=None) -> SymbolMomentumTimingService:
    repository = (
        SymbolMomentumTimingRepository(db_path=db_path)
        if db_path is not None
        else SymbolMomentumTimingRepository()
    )
    return SymbolMomentumTimingService(repository=repository)
