"""Webull-compatible RSI calibration reads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repositories.bar_pattern_feature_repo import BarPatternFeatureRepository


@dataclass(frozen=True)
class WebullRsiCalibrationSnapshot:
    found: bool
    symbol: str
    bar_timestamp: str | None = None
    timeframe: str | None = None
    close: float | None = None
    webull_rsi_14: float | None = None
    webull_rsi_zone: str | None = None
    webull_rsi_exit_signal: str | None = None
    webull_rsi_bearish_divergence: int | None = None
    reason: str | None = None


def latest_webull_rsi_snapshot(
    symbol: str,
    *,
    db_path: Path | str | None = None,
) -> WebullRsiCalibrationSnapshot:
    if db_path is not None and not Path(db_path).exists():
        normalized_symbol = str(symbol or "").upper().strip()
        return WebullRsiCalibrationSnapshot(
            found=False,
            symbol=normalized_symbol,
            reason=f"database_not_found:{Path(db_path)}",
        )
    repository = (
        BarPatternFeatureRepository(db_path)
        if db_path is not None
        else BarPatternFeatureRepository()
    )
    row = repository.latest_webull_rsi_snapshot(symbol)
    if not row.get("found"):
        return WebullRsiCalibrationSnapshot(
            found=False,
            symbol=str(row.get("symbol") or ""),
            reason=str(row.get("reason") or "webull_rsi_snapshot_unavailable"),
        )

    return WebullRsiCalibrationSnapshot(
        found=True,
        symbol=str(row["symbol"]),
        bar_timestamp=str(row["bar_timestamp"]),
        timeframe=str(row["timeframe"]),
        close=float(row["close"]) if row.get("close") is not None else None,
        webull_rsi_14=float(row["webull_rsi_14"]),
        webull_rsi_zone=str(row["webull_rsi_zone"] or ""),
        webull_rsi_exit_signal=str(row["webull_rsi_exit_signal"] or ""),
        webull_rsi_bearish_divergence=(
            int(row["webull_rsi_bearish_divergence"])
            if row.get("webull_rsi_bearish_divergence") is not None
            else None
        ),
    )
