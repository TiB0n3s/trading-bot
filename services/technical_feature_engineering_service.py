"""Technical feature engineering for ML research and live context.

The service provides dependency-light equivalents for common pandas-ta/TA-Lib
features so the bot can start capturing model inputs without requiring native
indicator packages in the trading loop.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


TECHNICAL_FEATURE_VERSION = "technical_feature_set_v1"


@dataclass(frozen=True)
class TechnicalFeatureSet:
    version: str
    close: float | None
    return_1: float | None
    return_5: float | None
    sma_5: float | None
    sma_20: float | None
    ema_12: float | None
    ema_26: float | None
    macd: float | None
    macd_signal: float | None
    rsi_14: float | None
    bollinger_mid_20: float | None
    bollinger_upper_20: float | None
    bollinger_lower_20: float | None
    bollinger_position_20: float | None
    target_next_close_up: int | None
    feature_columns: list[str]
    available: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _float_list(values: list[Any] | tuple[Any, ...] | None) -> list[float]:
    out = []
    for value in values or []:
        try:
            if value is not None:
                out.append(float(value))
        except Exception:
            continue
    return out


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return round(sum(values[-window:]) / window, 6)


def _ema_series(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (window + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append(value * alpha + out[-1] * (1.0 - alpha))
    return out


def _rsi(values: list[float], window: int = 14) -> float | None:
    if len(values) <= window:
        return None
    gains = []
    losses = []
    for prev, cur in zip(values[-window - 1 : -1], values[-window:]):
        change = cur - prev
        if change >= 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 6)


def _std(values: list[float]) -> float:
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return variance ** 0.5


def build_technical_feature_set(
    *,
    closes: list[Any] | tuple[Any, ...],
    next_close: Any | None = None,
) -> TechnicalFeatureSet:
    """Build a compact technical feature set from chronological closes."""
    values = _float_list(closes)
    feature_columns = [
        "return_1",
        "return_5",
        "sma_5",
        "sma_20",
        "ema_12",
        "ema_26",
        "macd",
        "macd_signal",
        "rsi_14",
        "bollinger_position_20",
    ]
    if len(values) < 20:
        return TechnicalFeatureSet(
            version=TECHNICAL_FEATURE_VERSION,
            close=values[-1] if values else None,
            return_1=None,
            return_5=None,
            sma_5=None,
            sma_20=None,
            ema_12=None,
            ema_26=None,
            macd=None,
            macd_signal=None,
            rsi_14=None,
            bollinger_mid_20=None,
            bollinger_upper_20=None,
            bollinger_lower_20=None,
            bollinger_position_20=None,
            target_next_close_up=None,
            feature_columns=feature_columns,
            available=False,
            reason="insufficient closes; need at least 20",
        )

    close = values[-1]
    ret_1 = ((values[-1] - values[-2]) / values[-2] * 100.0) if values[-2] else None
    ret_5 = ((values[-1] - values[-6]) / values[-6] * 100.0) if len(values) >= 6 and values[-6] else None
    ema_12_series = _ema_series(values, 12)
    ema_26_series = _ema_series(values, 26)
    ema_12 = ema_12_series[-1] if ema_12_series else None
    ema_26 = ema_26_series[-1] if ema_26_series else None
    macd_series = [
        fast - slow
        for fast, slow in zip(ema_12_series[-len(ema_26_series) :], ema_26_series)
    ]
    macd = macd_series[-1] if macd_series else None
    macd_signal_series = _ema_series(macd_series, 9)
    macd_signal = macd_signal_series[-1] if macd_signal_series else None
    mid = _sma(values, 20)
    band_values = values[-20:]
    band_std = _std(band_values)
    upper = mid + 2.0 * band_std if mid is not None else None
    lower = mid - 2.0 * band_std if mid is not None else None
    band_width = (upper - lower) if upper is not None and lower is not None else None
    band_position = (
        (close - lower) / band_width
        if lower is not None and band_width and band_width > 0
        else None
    )
    target = None
    try:
        if next_close is not None:
            target = 1 if float(next_close) > close else 0
    except Exception:
        target = None

    return TechnicalFeatureSet(
        version=TECHNICAL_FEATURE_VERSION,
        close=round(close, 6),
        return_1=round(ret_1, 6) if ret_1 is not None else None,
        return_5=round(ret_5, 6) if ret_5 is not None else None,
        sma_5=_sma(values, 5),
        sma_20=mid,
        ema_12=round(ema_12, 6) if ema_12 is not None else None,
        ema_26=round(ema_26, 6) if ema_26 is not None else None,
        macd=round(macd, 6) if macd is not None else None,
        macd_signal=round(macd_signal, 6) if macd_signal is not None else None,
        rsi_14=_rsi(values, 14),
        bollinger_mid_20=round(mid, 6) if mid is not None else None,
        bollinger_upper_20=round(upper, 6) if upper is not None else None,
        bollinger_lower_20=round(lower, 6) if lower is not None else None,
        bollinger_position_20=round(band_position, 6) if band_position is not None else None,
        target_next_close_up=target,
        feature_columns=feature_columns,
        available=True,
        reason="ok",
    )
