"""Volume-clock VPIN research from 1-minute bar rows.

This estimates VPIN on equal-volume buckets using Bulk Volume Classification
over bar returns. It is a research/readiness layer, not true trade-level VPIN:
true aggressor-side VPIN still requires transaction-level data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any


VOLUME_CLOCK_VPIN_VERSION = "volume_clock_vpin_v1"
VOLUME_CLOCK_VPIN_RUNTIME_EFFECT = "research_report_only_no_live_authority"


@dataclass(frozen=True)
class VolumeClockBucket:
    bucket_id: int
    start_ts: str
    end_ts: str
    bars: int
    volume: float
    buy_volume: float
    sell_volume: float
    order_imbalance: float
    vpin: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VolumeClockVpinPayload:
    report_version: str
    runtime_effect: str
    symbol: str
    target_date: str
    source_rows: int
    bucket_volume: float
    window_buckets: int
    buckets: list[VolumeClockBucket]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "runtime_effect": self.runtime_effect,
            "symbol": self.symbol,
            "target_date": self.target_date,
            "source_rows": self.source_rows,
            "bucket_volume": self.bucket_volume,
            "window_buckets": self.window_buckets,
            "buckets": [bucket.to_dict() for bucket in self.buckets],
            "summary": self.summary,
        }


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _rolling_std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    if variance <= 0:
        return None
    return math.sqrt(variance)


def _bvc_buy_probability(
    *,
    prev_close: float | None,
    close: float | None,
    rolling_returns: list[float],
) -> float:
    if prev_close is None or close is None or prev_close <= 0:
        return 0.5
    ret = (close - prev_close) / prev_close
    vol = _rolling_std(rolling_returns[-20:])
    if vol is None or vol <= 0:
        if ret > 0:
            return 0.75
        if ret < 0:
            return 0.25
        return 0.5
    return max(0.0, min(1.0, _normal_cdf(ret / vol)))


def build_volume_clock_vpin_payload(
    *,
    rows: list[dict[str, Any]],
    symbol: str,
    target_date: str,
    bucket_volume: float = 500_000.0,
    window_buckets: int = 20,
    min_bucket_fill_ratio: float = 0.95,
) -> VolumeClockVpinPayload:
    sorted_rows = sorted(rows, key=lambda row: str(row.get("bar_timestamp") or ""))
    bucket_target = max(1.0, float(bucket_volume or 1.0))
    window = max(1, int(window_buckets or 1))
    min_fill = max(0.0, min(1.0, float(min_bucket_fill_ratio)))
    returns: list[float] = []
    buckets: list[VolumeClockBucket] = []
    current: dict[str, Any] | None = None
    prev_close: float | None = None

    def start_bucket(ts: str) -> dict[str, Any]:
        return {
            "start_ts": ts,
            "end_ts": ts,
            "bars": 0,
            "volume": 0.0,
            "buy_volume": 0.0,
            "sell_volume": 0.0,
        }

    def finish_bucket(bucket: dict[str, Any]) -> None:
        if bucket["volume"] < bucket_target * min_fill:
            return
        imbalance = abs(bucket["buy_volume"] - bucket["sell_volume"]) / max(bucket["volume"], 1.0)
        recent_imbalances = [item.order_imbalance for item in buckets[-(window - 1) :]]
        vpin_values = [*recent_imbalances, imbalance]
        vpin = sum(vpin_values) / len(vpin_values)
        buckets.append(
            VolumeClockBucket(
                bucket_id=len(buckets) + 1,
                start_ts=str(bucket["start_ts"]),
                end_ts=str(bucket["end_ts"]),
                bars=int(bucket["bars"]),
                volume=round(bucket["volume"], 4),
                buy_volume=round(bucket["buy_volume"], 4),
                sell_volume=round(bucket["sell_volume"], 4),
                order_imbalance=round(imbalance, 6),
                vpin=round(vpin, 6),
            )
        )

    for row in sorted_rows:
        ts = str(row.get("bar_timestamp") or "")
        close = _float(row.get("close"))
        volume = _float(row.get("volume")) or 0.0
        if volume <= 0:
            prev_close = close if close is not None else prev_close
            continue
        if prev_close is not None and close is not None and prev_close > 0:
            returns.append((close - prev_close) / prev_close)
        prob_buy = _bvc_buy_probability(
            prev_close=prev_close,
            close=close,
            rolling_returns=returns,
        )
        remaining = volume
        while remaining > 0:
            if current is None:
                current = start_bucket(ts)
            capacity = bucket_target - current["volume"]
            chunk = min(remaining, capacity)
            current["end_ts"] = ts
            current["bars"] += 1
            current["volume"] += chunk
            current["buy_volume"] += chunk * prob_buy
            current["sell_volume"] += chunk * (1.0 - prob_buy)
            remaining -= chunk
            if current["volume"] >= bucket_target:
                finish_bucket(current)
                current = None
        prev_close = close if close is not None else prev_close

    if current is not None:
        finish_bucket(current)

    vpin_values = [bucket.vpin for bucket in buckets if bucket.vpin is not None]
    latest_vpin = vpin_values[-1] if vpin_values else None
    max_vpin = max(vpin_values) if vpin_values else None
    avg_vpin = sum(vpin_values) / len(vpin_values) if vpin_values else None
    summary = {
        "bucket_count": len(buckets),
        "latest_vpin": round(latest_vpin, 6) if latest_vpin is not None else None,
        "max_vpin": round(max_vpin, 6) if max_vpin is not None else None,
        "avg_vpin": round(avg_vpin, 6) if avg_vpin is not None else None,
        "toxicity_bucket": (
            "severe"
            if latest_vpin is not None and latest_vpin >= 0.90
            else "elevated"
            if latest_vpin is not None and latest_vpin >= 0.70
            else "normal"
            if latest_vpin is not None
            else "insufficient_buckets"
        ),
        "method": "bulk_volume_classification_from_1m_bars",
        "true_trade_level": False,
    }
    return VolumeClockVpinPayload(
        report_version=VOLUME_CLOCK_VPIN_VERSION,
        runtime_effect=VOLUME_CLOCK_VPIN_RUNTIME_EFFECT,
        symbol=symbol.upper(),
        target_date=target_date,
        source_rows=len(sorted_rows),
        bucket_volume=bucket_target,
        window_buckets=window,
        buckets=buckets,
        summary=summary,
    )
