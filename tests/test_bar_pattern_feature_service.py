#!/usr/bin/env python3
"""Tests for observe-only advanced per-bar learning features."""

from __future__ import annotations

import io
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.bar_pattern_feature_repo import BarPatternFeatureRepository  # noqa: E402
from services.bar_pattern_feature_service import (  # noqa: E402
    BAR_PATTERN_RUNTIME_EFFECT,
    BarPatternFeatureService,
)
from services.ops_checks.bar_pattern_checks import run_bar_pattern_backfill  # noqa: E402


def _fixture_bars() -> list[dict[str, float | str]]:
    start = datetime(2026, 6, 2, 13, 30, tzinfo=timezone.utc)
    bars: list[dict[str, float | str]] = []
    close = 100.0
    for idx in range(48):
        if idx < 24:
            close += 0.02 if idx % 4 else -0.01
            volume = 1500 + idx * 10
        elif idx < 32:
            close += 0.42
            volume = 6500 + idx * 200
        else:
            close += 0.10 if idx % 3 else -0.03
            volume = 4200 + idx * 30
        bars.append(
            {
                "timestamp": (start + timedelta(minutes=5 * idx)).isoformat(),
                "open": close - 0.08,
                "high": close + 0.12,
                "low": close - 0.16,
                "close": round(close, 4),
                "volume": float(volume),
                "vwap": round(close - 0.02, 4),
            }
        )
    return bars


def test_bar_pattern_service_builds_efi_pvt_forward_features():
    service = BarPatternFeatureService()
    rows = service.build_features(_fixture_bars(), symbol="aapl", horizon_bars=6)

    assert rows
    labels = {row["pattern_label"] for row in rows}
    assert "volume_confirmed_breakout" in labels or "constructive_continuation" in labels
    first = rows[0]
    assert first["symbol"] == "AAPL"
    assert first["bar_source"] == "unknown_bar_source"
    assert first["bar_adjusted"] is None
    assert first["bar_trade_count"] is None
    assert first["bar_interval_start_ts"] == first["bar_timestamp"]
    assert first["bar_interval_semantics"] == "inclusive_start_1m"
    assert first["open"] is not None
    assert first["high"] is not None
    assert first["low"] is not None
    assert first["vwap"] is not None
    assert first["ema_12"] is not None
    assert first["ema_26"] is not None
    assert first["macd"] is not None
    assert first["macd_signal"] is not None
    assert first["rsi_14"] is not None
    assert first["efi"] is not None
    assert first["efi_ema_13"] is not None
    assert first["pvt"] is not None
    assert first["pvt_slope_5"] is not None
    assert first["runtime_effect"] == BAR_PATTERN_RUNTIME_EFFECT
    assert any(row["opportunity_action"] == "buy_candidate" for row in rows)
    assert any(row["opportunity_quality"] == "best_buy_window" for row in rows)
    assert any(row["long_opportunity_score"] is not None for row in rows)
    assert any(row["sell_opportunity_score"] is not None for row in rows)
    assert any(row["forward_mfe_pct"] is not None for row in rows)
    assert any(row["forward_mae_pct"] is not None for row in rows)
    assert any(row["candle_body_pct"] is not None for row in rows)
    assert any(row["upper_wick_pct"] is not None for row in rows)
    assert any(row["lower_wick_pct"] is not None for row in rows)
    assert any(row["range_atr_ratio"] is not None for row in rows)
    assert any(row["pressure_return_3"] is not None for row in rows)
    assert any(row["volume_weighted_pressure_3"] is not None for row in rows)
    assert any(row["triple_barrier_label"] in {-1, 0, 1} for row in rows)
    assert any(row["triple_barrier_reason"] for row in rows)
    assert any(row["cvd_price_corr_20"] is not None for row in rows)
    assert any(row["vpin_toxicity_20"] is not None for row in rows)
    assert any(row["fractional_diff_zscore_20"] is not None for row in rows)
    assert any(row["trend_scan_label"] in {-1, 0, 1} for row in rows)
    assert any(row["trend_scan_reason"] for row in rows)


def test_bar_pattern_repository_persists_and_summarizes(tmp_path: Path):
    repo = BarPatternFeatureRepository(tmp_path / "trades.db")
    service = BarPatternFeatureService(repo)

    result = service.persist_features(
        _fixture_bars(),
        symbol="AAPL",
        target_date="2026-06-02",
        horizon_bars=6,
    )
    summary = service.summary("2026-06-02", symbol="AAPL")

    assert result.persisted_rows == result.feature_rows
    assert summary["rows"] == result.feature_rows
    assert summary["symbols"] == 1
    assert summary["rows_with_raw_bar_contract"] == result.feature_rows
    assert summary["rows_with_source"] == result.feature_rows
    assert summary["rows_with_technical_indicators"] == result.feature_rows
    assert summary["rows_with_forward_outcome"] > 0
    assert summary["labels"]
    assert summary["opportunities"]
    assert summary["triple_barriers"]
    assert summary["trend_scans"]
    assert summary["cvd_divergences"]
    assert summary["rows_with_order_flow"] > 0
    assert summary["rows_with_fractional_memory"] > 0
    assert any(
        row["opportunity_action"] == "buy_candidate"
        for row in summary["opportunities"]
    )


def test_bar_pattern_service_preserves_source_feed_adjustment_and_trade_count():
    bars = []
    for idx, bar in enumerate(_fixture_bars()):
        item = dict(bar)
        item["source"] = "alpaca_live_bar_stream"
        item["feed"] = "iex"
        item["adjusted"] = False
        item["trade_count"] = 10 + idx
        item["interval_semantics"] = "inclusive_start_live_closed_1m"
        bars.append(item)

    service = BarPatternFeatureService()
    rows = service.build_features(
        bars,
        symbol="AAPL",
        timeframe="1m",
        horizon_bars=6,
        bar_source="fallback_source",
        bar_feed="fallback_feed",
        adjusted=True,
        interval_semantics="fallback_semantics",
    )

    assert rows
    first = rows[0]
    assert first["bar_source"] == "alpaca_live_bar_stream"
    assert first["bar_feed"] == "iex"
    assert first["bar_adjusted"] == 0
    assert first["bar_trade_count"] is not None
    assert first["bar_interval_semantics"] == "inclusive_start_live_closed_1m"
    assert first["feature_json"]["bar_source"] == "alpaca_live_bar_stream"


class _FakePolygon:
    configured = True

    def aggregate_bar_dicts(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        return _fixture_bars()


def test_bar_pattern_ops_backfill_uses_polygon_and_reports(tmp_path: Path):
    with sqlite3.connect(tmp_path / "trades.db"):
        pass
    fake = _FakePolygon()

    buf = io.StringIO()
    with redirect_stdout(buf):
        ok = run_bar_pattern_backfill(
            "2026-06-02",
            base_dir=tmp_path,
            symbol="AAPL",
            polygon_market_data=fake,
            horizon_bars=6,
        )

    out = buf.getvalue()
    assert ok is True
    assert "EFI/PVT Bar Pattern Backfill" in out
    assert "observe_only_pattern_learning_no_live_authority" in out
    assert "feature_rows" in out
    assert "Hindsight opportunity summary" in out
    assert "Triple-barrier label summary" in out
    assert "Trend-scanning label summary" in out
    assert "CVD divergence summary" in out
    assert "buy_candidate" in out
    assert fake.kwargs["multiplier"] == 5


def main():
    tests = [
        test_bar_pattern_service_builds_efi_pvt_forward_features,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    with tempfile.TemporaryDirectory() as tmp:
        test_bar_pattern_repository_persists_and_summarizes(Path(tmp))
        print("[OK] test_bar_pattern_repository_persists_and_summarizes")

    with tempfile.TemporaryDirectory() as tmp:
        test_bar_pattern_ops_backfill_uses_polygon_and_reports(Path(tmp))
        print("[OK] test_bar_pattern_ops_backfill_uses_polygon_and_reports")

    print("\nAll 3 bar-pattern feature service tests passed.")


if __name__ == "__main__":
    main()
