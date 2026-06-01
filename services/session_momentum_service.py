"""Session-aware intraday momentum computation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any
from zoneinfo import ZoneInfo

from repositories.session_momentum_repo import SessionMomentumRepository
from services.market_data_service import market_data_service


MIN_BARS = 5
LOOKBACK_MINUTES = 240
ET = ZoneInfo("America/New_York")


def _pct_change(start: float | None, end: float | None) -> float | None:
    if start is None or end is None:
        return None
    if start <= 0:
        return None
    return (end - start) / start * 100.0


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bar_close(bar: Any) -> float | None:
    return _safe_float(getattr(bar, "c", None))


def _bar_high(bar: Any) -> float | None:
    return _safe_float(getattr(bar, "h", None))


def _bar_low(bar: Any) -> float | None:
    return _safe_float(getattr(bar, "l", None))


def _bar_typical_price(bar: Any) -> float | None:
    """Typical price (H+L+C)/3, standard VWAP numerator."""
    h = _bar_high(bar)
    lo = _bar_low(bar)
    c = _bar_close(bar)
    if h is None or lo is None or c is None:
        return None
    return (h + lo + c) / 3.0


def _bar_volume(bar: Any) -> float:
    return _safe_float(getattr(bar, "v", None)) or 0.0


def _compute_vwap(bars: list[Any]) -> float | None:
    total_pv = 0.0
    total_v = 0.0

    for bar in bars:
        tp = _bar_typical_price(bar)
        volume = _bar_volume(bar)
        if tp is None or volume <= 0:
            continue
        total_pv += tp * volume
        total_v += volume

    if total_v <= 0:
        return None

    return total_pv / total_v


def _window_return(bars: list[Any], window: int) -> float | None:
    if len(bars) < 2:
        return None

    scoped = bars[-window:] if len(bars) >= window else bars
    first = _bar_close(scoped[0])
    last = _bar_close(scoped[-1])
    return _pct_change(first, last)


def _session_start_or_lookback(now_utc: datetime, lookback_minutes: int) -> datetime:
    """Use regular-session open once market hours have started; fallback before open."""
    now_et = now_utc.astimezone(ET)
    session_open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    if now_et >= session_open_et:
        return session_open_et.astimezone(timezone.utc)
    return now_utc - timedelta(minutes=lookback_minutes)


def classify_session_momentum(
    *,
    session_return_pct: float | None,
    momentum_5m_pct: float | None,
    momentum_15m_pct: float | None,
    momentum_30m_pct: float | None,
    momentum_60m_pct: float | None = None,
    momentum_120m_pct: float | None = None,
    distance_from_vwap_pct: float | None,
    bar_count: int,
) -> dict[str, Any]:
    if bar_count < MIN_BARS:
        return {
            "trend_label": "insufficient_data",
            "trend_score": 0,
            "reason": f"bar_count={bar_count} < {MIN_BARS}",
        }

    score = 0
    reasons = []

    def add(condition: bool, points: int, reason: str) -> None:
        nonlocal score
        if condition:
            score += points
            reasons.append(reason)

    sr = session_return_pct or 0.0
    m5 = momentum_5m_pct or 0.0
    m15 = momentum_15m_pct or 0.0
    m30 = momentum_30m_pct or 0.0
    m60 = momentum_60m_pct or 0.0
    m120 = momentum_120m_pct or 0.0
    vwap_dist = distance_from_vwap_pct or 0.0

    add(sr > 0.50, 2, "session_return_positive")
    add(sr < -0.50, -2, "session_return_negative")

    add(m5 > 0.10, 1, "5m_rising")
    add(m5 < -0.10, -1, "5m_falling")

    add(m15 > 0.20, 2, "15m_rising")
    add(m15 < -0.20, -2, "15m_falling")

    add(m30 > 0.35, 2, "30m_rising")
    add(m30 < -0.35, -2, "30m_falling")

    add(m60 > 0.50, 1, "60m_rising")
    add(m60 < -0.50, -1, "60m_falling")

    add(m120 > 0.75, 1, "120m_rising")
    add(m120 < -0.75, -1, "120m_falling")

    add(vwap_dist > 0.15, 1, "above_vwap")
    add(vwap_dist < -0.15, -1, "below_vwap")

    if score >= 6:
        label = "strong_uptrend"
    elif score >= 3:
        label = "developing_uptrend"
    elif score >= 1 and sr < 0 and m5 > 0 and m15 > 0:
        label = "reversal_attempt"
    elif score <= -5:
        label = "downtrend"
    elif score <= -2:
        label = "fading"
    else:
        label = "rangebound"

    return {
        "trend_label": label,
        "trend_score": score,
        "reason": ",".join(reasons) if reasons else "mixed_or_flat",
    }


def classify_momentum_regime(
    *,
    session_return_pct: float | None,
    momentum_5m_pct: float | None,
    momentum_15m_pct: float | None,
    momentum_30m_pct: float | None,
    momentum_60m_pct: float | None,
    momentum_120m_pct: float | None,
    distance_from_vwap_pct: float | None,
    pullback_from_session_high_pct: float | None = None,
) -> dict[str, Any]:
    """Return longer-horizon regime and maturity context for decisions.

    Fast windows still time entries. 60m/120m/session context answers whether a
    move is persistent, mature, pulling back constructively, or reversing.
    """
    sr = session_return_pct or 0.0
    m5 = momentum_5m_pct or 0.0
    m15 = momentum_15m_pct or 0.0
    m30 = momentum_30m_pct or 0.0
    m60 = momentum_60m_pct or 0.0
    m120 = momentum_120m_pct or 0.0
    vwap_dist = distance_from_vwap_pct or 0.0
    pullback = pullback_from_session_high_pct or 0.0

    aligned_up = sum(1 for v in (m15, m30, m60, m120) if v > 0)
    aligned_down = sum(1 for v in (m15, m30, m60, m120) if v < 0)
    trend_persistence_score = aligned_up - aligned_down
    if sr > 0.50:
        trend_persistence_score += 1
    elif sr < -0.50:
        trend_persistence_score -= 1

    pullback_with_trend_score = 0
    if m60 > 0.30 or m120 > 0.50 or sr > 0.75:
        if -1.20 <= pullback <= -0.15:
            pullback_with_trend_score += 2
        if -0.35 <= vwap_dist <= 0.75:
            pullback_with_trend_score += 1
        if m5 > 0 or m15 > 0:
            pullback_with_trend_score += 1

    late_chase_maturity_score = 0
    if sr >= 1.50:
        late_chase_maturity_score += 1
    if m60 >= 1.00:
        late_chase_maturity_score += 1
    if m120 >= 1.50:
        late_chase_maturity_score += 1
    if vwap_dist >= 1.50:
        late_chase_maturity_score += 1
    if pullback >= -0.10 and m5 <= 0:
        late_chase_maturity_score += 1

    reversal_attempt_score = 0
    if m60 < -0.30 or m120 < -0.50 or sr < -0.50:
        if m5 > 0:
            reversal_attempt_score += 1
        if m15 > 0:
            reversal_attempt_score += 1
        if vwap_dist > -0.30:
            reversal_attempt_score += 1

    if trend_persistence_score >= 4:
        regime = "persistent_uptrend"
    elif trend_persistence_score <= -4:
        regime = "persistent_downtrend"
    elif reversal_attempt_score >= 2:
        regime = "reversal_attempt"
    elif late_chase_maturity_score >= 3:
        regime = "mature_uptrend"
    elif pullback_with_trend_score >= 3:
        regime = "pullback_with_uptrend"
    else:
        regime = "mixed"

    return {
        "trend_regime": regime,
        "trend_persistence_score": trend_persistence_score,
        "pullback_with_trend_score": pullback_with_trend_score,
        "late_chase_maturity_score": late_chase_maturity_score,
        "reversal_attempt_score": reversal_attempt_score,
    }


def _is_strong_session(row: dict[str, Any]) -> bool:
    score = _safe_float(row.get("trend_score")) or 0.0
    session_return = _safe_float(row.get("session_return_pct")) or 0.0
    return score >= 6 or session_return >= 1.0


def _merge_retained_strength(
    row: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """Carry session-strength high-water marks across refreshes for one trading day."""
    previous = previous or {}
    merged = dict(row)

    now = row.get("updated_at")
    score = _safe_float(row.get("trend_score"))
    session_return = _safe_float(row.get("session_return_pct"))
    vwap_dist = _safe_float(row.get("distance_from_vwap_pct"))

    prev_best_score = _safe_float(previous.get("best_trend_score"))
    prev_best_return = _safe_float(previous.get("best_session_return_pct"))
    prev_best_vwap = _safe_float(previous.get("best_distance_from_vwap_pct"))
    prev_minutes_strong = int(previous.get("minutes_strong") or 0)
    prev_seen = int(previous.get("session_strength_seen") or 0)

    best_score = max(
        [v for v in (prev_best_score, score) if v is not None],
        default=None,
    )
    best_return = max(
        [v for v in (prev_best_return, session_return) if v is not None],
        default=None,
    )
    best_vwap = max(
        [v for v in (prev_best_vwap, vwap_dist) if v is not None],
        default=None,
    )

    strong_now = _is_strong_session(row)
    session_strength_seen = 1 if (prev_seen or strong_now) else 0

    first_seen = previous.get("strength_first_seen_at")
    last_seen = previous.get("strength_last_seen_at")

    if strong_now:
        if not first_seen:
            first_seen = now
        last_seen = now
        prev_minutes_strong += 1

    pullback_from_high = None
    if session_return is not None and best_return is not None:
        pullback_from_high = session_return - best_return

    merged.update(
        {
            "best_trend_score": int(best_score) if best_score is not None else None,
            "best_session_return_pct": round(best_return, 3)
            if best_return is not None
            else None,
            "best_distance_from_vwap_pct": round(best_vwap, 3)
            if best_vwap is not None
            else None,
            "minutes_strong": prev_minutes_strong,
            "strength_first_seen_at": first_seen,
            "strength_last_seen_at": last_seen,
            "pullback_from_session_high_pct": round(pullback_from_high, 3)
            if pullback_from_high is not None
            else None,
            "session_strength_seen": session_strength_seen,
        }
    )
    return merged


class SessionMomentumService:
    def __init__(
        self,
        *,
        repository: SessionMomentumRepository,
        market_data,
        logger: logging.Logger | None = None,
        lookback_minutes: int = LOOKBACK_MINUTES,
    ):
        self.repository = repository
        self.market_data = market_data
        self.logger = logger or logging.getLogger(__name__)
        self.lookback_minutes = lookback_minutes

    def init_table(self) -> None:
        self.repository.init_table()

    def build(self, symbol: str) -> dict[str, Any]:
        symbol = symbol.upper()
        start = _session_start_or_lookback(
            datetime.now(timezone.utc),
            self.lookback_minutes,
        ).isoformat()

        bars = self.market_data.get_bars_with_fallback(
            symbol,
            "1Min",
            start=start,
            feed="iex",
        )
        bars = [b for b in bars if _bar_close(b) is not None]

        if not bars:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return {
                "symbol": symbol,
                "updated_at": now,
                "bar_count": 0,
                "session_open_price": None,
                "latest_price": None,
                "session_return_pct": None,
                "momentum_5m_pct": None,
                "momentum_15m_pct": None,
                "momentum_30m_pct": None,
                "momentum_60m_pct": None,
                "momentum_120m_pct": None,
                "vwap": None,
                "distance_from_vwap_pct": None,
                "trend_regime": "insufficient_data",
                "trend_persistence_score": 0,
                "pullback_with_trend_score": 0,
                "late_chase_maturity_score": 0,
                "reversal_attempt_score": 0,
                "trend_label": "insufficient_data",
                "trend_score": 0,
                "reason": (
                    f"no 1Min IEX bars returned in last {self.lookback_minutes} minutes; "
                    "likely pre-market, closed market, or data unavailable"
                ),
            }

        session_open = _bar_close(bars[0])
        latest = _bar_close(bars[-1])
        session_return = _pct_change(session_open, latest)

        momentum_5m = _window_return(bars, 5)
        momentum_15m = _window_return(bars, 15)
        momentum_30m = _window_return(bars, 30)
        momentum_60m = _window_return(bars, 60) if len(bars) >= 60 else None
        momentum_120m = _window_return(bars, 120) if len(bars) >= 120 else None

        vwap = _compute_vwap(bars)
        distance_from_vwap = _pct_change(vwap, latest) if vwap and latest else None

        classification = classify_session_momentum(
            session_return_pct=session_return,
            momentum_5m_pct=momentum_5m,
            momentum_15m_pct=momentum_15m,
            momentum_30m_pct=momentum_30m,
            momentum_60m_pct=momentum_60m,
            momentum_120m_pct=momentum_120m,
            distance_from_vwap_pct=distance_from_vwap,
            bar_count=len(bars),
        )

        best_close = max(
            (_bar_close(bar) for bar in bars),
            default=None,
        )
        pullback_from_session_high = (
            _pct_change(best_close, latest)
            if best_close is not None and latest is not None
            else None
        )
        regime = classify_momentum_regime(
            session_return_pct=session_return,
            momentum_5m_pct=momentum_5m,
            momentum_15m_pct=momentum_15m,
            momentum_30m_pct=momentum_30m,
            momentum_60m_pct=momentum_60m,
            momentum_120m_pct=momentum_120m,
            distance_from_vwap_pct=distance_from_vwap,
            pullback_from_session_high_pct=pullback_from_session_high,
        )

        return {
            "symbol": symbol,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "bar_count": len(bars),
            "session_open_price": round(session_open, 4)
            if session_open is not None
            else None,
            "latest_price": round(latest, 4) if latest is not None else None,
            "session_return_pct": round(session_return, 3)
            if session_return is not None
            else None,
            "momentum_5m_pct": round(momentum_5m, 3)
            if momentum_5m is not None
            else None,
            "momentum_15m_pct": round(momentum_15m, 3)
            if momentum_15m is not None
            else None,
            "momentum_30m_pct": round(momentum_30m, 3)
            if momentum_30m is not None
            else None,
            "momentum_60m_pct": round(momentum_60m, 3)
            if momentum_60m is not None
            else None,
            "momentum_120m_pct": round(momentum_120m, 3)
            if momentum_120m is not None
            else None,
            "vwap": round(vwap, 4) if vwap is not None else None,
            "distance_from_vwap_pct": round(distance_from_vwap, 3)
            if distance_from_vwap is not None
            else None,
            "trend_regime": regime["trend_regime"],
            "trend_persistence_score": regime["trend_persistence_score"],
            "pullback_with_trend_score": regime["pullback_with_trend_score"],
            "late_chase_maturity_score": regime["late_chase_maturity_score"],
            "reversal_attempt_score": regime["reversal_attempt_score"],
            "trend_label": classification["trend_label"],
            "trend_score": classification["trend_score"],
            "reason": classification["reason"],
        }

    def refresh_symbol(self, symbol: str) -> dict[str, Any]:
        row = self.build(symbol)
        row = self.upsert(row)
        return self.repository.get_latest(symbol) or row

    def upsert(self, row: dict[str, Any]) -> dict[str, Any]:
        self.repository.init_table()
        symbol = str(row.get("symbol") or "").upper()
        previous = self.repository.get_latest(symbol)
        row = _merge_retained_strength(row, previous)
        self.repository.upsert(row)
        return row

    def get_latest(self, symbol: str) -> dict[str, Any] | None:
        return self.repository.get_latest(symbol)

    @staticmethod
    def print_row(row: dict[str, Any]) -> None:
        print(
            f"{row['symbol']:<6} "
            f"label={row['trend_label']:<20} "
            f"score={row['trend_score']:>3} "
            f"session={row['session_return_pct']}% "
            f"5m={row['momentum_5m_pct']}% "
            f"15m={row['momentum_15m_pct']}% "
            f"30m={row['momentum_30m_pct']}% "
            f"60m={row.get('momentum_60m_pct')}% "
            f"120m={row.get('momentum_120m_pct')}% "
            f"vwap_dist={row['distance_from_vwap_pct']}% "
            f"regime={row.get('trend_regime')} "
            f"maturity={row.get('late_chase_maturity_score')} "
            f"best_score={row.get('best_trend_score')} "
            f"best_return={row.get('best_session_return_pct')}% "
            f"minutes_strong={row.get('minutes_strong')} "
            f"pullback={row.get('pullback_from_session_high_pct')}% "
            f"bars={row['bar_count']} "
            f"reason={row['reason']}"
        )


_default_service: SessionMomentumService | None = None


def get_default_session_momentum_service() -> SessionMomentumService:
    global _default_service
    if _default_service is None:
        _default_service = SessionMomentumService(
            repository=SessionMomentumRepository(),
            market_data=market_data_service,
            logger=logging.getLogger("session_momentum"),
        )
    return _default_service
