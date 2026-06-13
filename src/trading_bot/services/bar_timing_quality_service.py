"""Derive best/good entry and exit timing labels from bar-path outcomes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from repositories.bar_timing_quality_repo import BarTimingQualityRepository

BAR_TIMING_QUALITY_LABEL_VERSION = "bar_timing_quality_v1"
BAR_TIMING_QUALITY_RUNTIME_EFFECT = "observe_only_timing_pattern_learning_no_live_authority"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _score_clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 3)


class BarTimingQualityService:
    def __init__(self, *, repository: BarTimingQualityRepository):
        self.repository = repository

    def classify_row(self, row: dict[str, Any]) -> dict[str, Any]:
        forward = _float(row.get("forward_return_pct"))
        mfe = _float(row.get("forward_mfe_pct"))
        mae = _float(row.get("forward_mae_pct"))
        long_score = _float(row.get("long_opportunity_score"))
        sell_score = _float(row.get("sell_opportunity_score"))
        trend_tstat = _float(row.get("trend_scan_tstat"))

        entry_score = _score_clamp(
            50.0
            + (forward * 9.0)
            + (mfe * 7.0)
            + (mae * 5.0)
            + ((long_score - 50.0) * 0.35)
            - max(0.0, sell_score - 55.0) * 0.25
            + max(0.0, trend_tstat) * 2.0
        )
        exit_score = _score_clamp(
            50.0
            - (forward * 8.0)
            - (mfe * 3.0)
            - (mae * 7.0)
            + ((sell_score - 50.0) * 0.4)
            - max(0.0, long_score - 65.0) * 0.2
            + max(0.0, -trend_tstat) * 2.0
        )

        entry_label, entry_reason = self._entry_label(
            entry_score=entry_score,
            forward=forward,
            mfe=mfe,
            mae=mae,
            long_score=long_score,
            sell_score=sell_score,
        )
        exit_label, exit_reason = self._exit_label(
            exit_score=exit_score,
            forward=forward,
            mfe=mfe,
            mae=mae,
            long_score=long_score,
            sell_score=sell_score,
        )
        reason = (
            f"entry={entry_reason}; exit={exit_reason}; "
            f"fwd={forward:.3f}; mfe={mfe:.3f}; mae={mae:.3f}; "
            f"long_score={long_score:.1f}; sell_score={sell_score:.1f}"
        )
        return {
            "bar_pattern_feature_id": row["bar_pattern_feature_id"],
            "symbol": row["symbol"],
            "bar_timestamp": row["bar_timestamp"],
            "timeframe": row["timeframe"],
            "bar_source": row.get("bar_source"),
            "feature_version": row.get("feature_version"),
            "entry_timing_label": entry_label,
            "entry_timing_score": entry_score,
            "exit_timing_label": exit_label,
            "exit_timing_score": exit_score,
            "forward_return_pct": row.get("forward_return_pct"),
            "forward_mfe_pct": row.get("forward_mfe_pct"),
            "forward_mae_pct": row.get("forward_mae_pct"),
            "long_opportunity_score": row.get("long_opportunity_score"),
            "sell_opportunity_score": row.get("sell_opportunity_score"),
            "horizon_bars": row.get("horizon_bars"),
            "label_version": BAR_TIMING_QUALITY_LABEL_VERSION,
            "runtime_effect": BAR_TIMING_QUALITY_RUNTIME_EFFECT,
            "reason": reason,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "feature_json": {
                "pattern_label": row.get("pattern_label"),
                "opportunity_action": row.get("opportunity_action"),
                "opportunity_quality": row.get("opportunity_quality"),
                "triple_barrier_label": row.get("triple_barrier_label"),
                "trend_scan_label": row.get("trend_scan_label"),
                "trend_scan_tstat": row.get("trend_scan_tstat"),
            },
        }

    @staticmethod
    def _entry_label(
        *,
        entry_score: float,
        forward: float,
        mfe: float,
        mae: float,
        long_score: float,
        sell_score: float,
    ) -> tuple[str, str]:
        if entry_score >= 76.0 and mfe >= 0.75 and forward >= 0.20 and mae > -0.90:
            return "best_entry", "strong_forward_path_with_limited_adverse_excursion"
        if entry_score >= 62.0 and mfe >= 0.45 and forward >= -0.10 and mae > -1.25:
            return "good_entry", "favorable_or_recoverable_forward_path"
        if sell_score >= 70.0 or (forward <= -0.35 and mae <= -0.75) or long_score <= 35.0:
            return "avoid_entry", "forward_path_or_existing_bar_score_penalizes_entry"
        return "neutral_entry", "mixed_or_insufficient_forward_entry_edge"

    @staticmethod
    def _exit_label(
        *,
        exit_score: float,
        forward: float,
        mfe: float,
        mae: float,
        long_score: float,
        sell_score: float,
    ) -> tuple[str, str]:
        if exit_score >= 76.0 and forward <= -0.25 and mae <= -0.75:
            return "best_exit", "future_path_deteriorates_after_this_bar"
        if exit_score >= 62.0 and (forward <= 0.05 or mae <= -1.0 or sell_score >= 65.0):
            return "good_exit", "future_reward_risk_favors_reducing_exposure"
        if long_score >= 70.0 and mfe >= 0.60 and forward >= 0.10:
            return "hold_preferred", "future_path_still_rewards_patience"
        return "neutral_exit", "mixed_or_insufficient_forward_exit_edge"

    def materialize(
        self,
        *,
        target_date: str | None = None,
        limit: int | None = None,
        timeframe: str = "1m",
    ) -> dict[str, Any]:
        source_rows = self.repository.source_rows(
            target_date=target_date,
            limit=limit,
            timeframe=timeframe,
        )
        labels = [self.classify_row(row) for row in source_rows]
        rows_written = self.repository.upsert_labels(labels)
        summary = self.repository.summary(target_date=target_date)
        return {
            "ok": True,
            "target_date": target_date,
            "timeframe": timeframe,
            "source_rows": len(source_rows),
            "rows_written": rows_written,
            "label_version": BAR_TIMING_QUALITY_LABEL_VERSION,
            "runtime_effect": BAR_TIMING_QUALITY_RUNTIME_EFFECT,
            "summary": summary,
        }


def build_default_bar_timing_quality_service(db_path=None) -> BarTimingQualityService:
    repository = (
        BarTimingQualityRepository(db_path=db_path)
        if db_path is not None
        else BarTimingQualityRepository()
    )
    return BarTimingQualityService(repository=repository)
