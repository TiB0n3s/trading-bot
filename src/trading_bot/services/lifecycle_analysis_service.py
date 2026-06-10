"""Analysis service for canonical entry/exit lifecycle rows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from services.symbol_pattern_backfill_service import canonical_symbol_pattern_state


@dataclass(frozen=True)
class LifecycleAnalysisPayload:
    rows: list[dict[str, Any]]
    start_date: str
    end_date: str
    symbol: str | None
    summary: dict[str, int]


class LifecycleAnalysisService:
    def __init__(self, repository: LifecycleAnalysisRepository):
        self.repository = repository

    @staticmethod
    def _classify(row: dict[str, Any]) -> str:
        if row.get("approved") and row.get("exit_snapshot_id"):
            return "approved_with_exit"
        if row.get("approved"):
            try:
                matched_exit_count = int(row.get("matched_exit_count") or 0)
            except Exception:
                matched_exit_count = 0
            if matched_exit_count > 0:
                return "approved_matched_exit_missing_snapshot"
            return "approved_open_or_unlinked_exit"
        if row.get("rejected_outcome_id"):
            return "rejected_with_counterfactual"
        if row.get("trade_id") is None:
            return "rejected_snapshot_only_no_trade"
        return "rejected_without_counterfactual"

    @staticmethod
    def _canonical(row: dict[str, Any]) -> dict[str, Any]:
        raw = row.get("canonical_intelligence_json")
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            loaded = json.loads(str(raw))
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _candidate_payload(row: dict[str, Any]) -> dict[str, Any]:
        raw = row.get("candidate_json")
        if isinstance(raw, dict):
            loaded = raw
        elif not raw:
            return {}
        else:
            try:
                parsed = json.loads(str(raw))
                loaded = parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        candidate = loaded.get("candidate")
        return candidate if isinstance(candidate, dict) else loaded

    @staticmethod
    def _synthesize_auto_buy_canonical(
        row: dict[str, Any], candidate: dict[str, Any]
    ) -> dict[str, Any]:
        """Compatibility canonical state for direct auto-buy trade rows.

        Auto-buy entries can bypass decision_snapshots.  They still carry the
        decision evidence in candidate_universe/auto_buy payloads, so expose the
        normalized authority fields for learning/readiness reports.
        """
        if not candidate:
            return {}
        learned_applied = bool(candidate.get("learned_tiebreaker_applied"))
        learned_outcome = {
            "advisory_decision": "allow"
            if candidate.get("decision") == "strong_buy_candidate"
            else candidate.get("decision"),
            "authority_mode": "paper_only",
            "enforced": learned_applied,
            "effect_on_size": "none",
            "effect_on_execution": "allow" if learned_applied else "none",
            "reason": candidate.get("learned_tiebreaker_reason") or candidate.get("reason"),
            "source": "auto_buy_manager_candidate_payload",
            "runtime_effect": candidate.get("learned_tiebreaker_runtime_effect")
            or "observe_only_no_live_authority",
        }
        return {
            "advisory_authority_state": {
                "decision_policy_outcome": learned_outcome,
                "setup_quality_outcome": {
                    "label": candidate.get("setup_label"),
                    "recommendation": candidate.get("setup_recommendation"),
                    "source": "auto_buy_manager_candidate_payload",
                },
                "ml_outcome": {
                    "bucket": candidate.get("ml_prediction_bucket"),
                    "score": candidate.get("ml_prediction_score"),
                    "source": "auto_buy_manager_candidate_payload",
                },
            },
            "pattern_state": {
                "pattern_label": candidate.get("symbol_pattern"),
                "directional_bias": candidate.get("pattern_directional_bias"),
                "confidence_quality": candidate.get("pattern_confidence_quality"),
                "runtime_effect": candidate.get("pattern_runtime_effect"),
                "source": "auto_buy_manager_candidate_payload",
            },
            "momentum_state": {
                "session_label": candidate.get("session_trend_label"),
                "session_score": candidate.get("session_trend_score"),
            },
            "prediction_state": {
                "ml_bucket": candidate.get("ml_prediction_bucket"),
                "ml_score": candidate.get("ml_prediction_score"),
            },
            "setup_state": {
                "label": candidate.get("setup_label"),
                "recommendation": candidate.get("setup_recommendation"),
                "score": candidate.get("setup_score"),
            },
        }

    @staticmethod
    def _path(data: dict[str, Any], *path: str) -> Any:
        cur: Any = data
        for key in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(key)
        return cur

    @staticmethod
    def _historical_symbol_pattern_state(row: dict[str, Any]) -> dict[str, Any]:
        """Derive a conservative pattern label from pre-pattern snapshot columns."""
        session = str(row.get("session_trend_label") or "").strip().lower()
        momentum = str(row.get("momentum_state") or "").strip().lower()
        direction = str(row.get("momentum_direction") or "").strip().lower()
        prediction = str(row.get("prediction_decision") or "").strip().lower()

        if not any((session, momentum, direction, prediction)):
            return {}

        base = {
            "version": "historical_symbol_pattern_backfill_v1",
            "runtime_effect": "observe_only_no_live_authority",
            "authority": "observe_only_no_live_authority",
            "confidence_quality": "historical_row_derived",
            "provider": "deterministic_historical_backfill",
            "source": "derived_from_historical_snapshot_columns",
        }
        if (
            session in {"strong_uptrend", "developing_uptrend"}
            and momentum == "accelerating"
            and direction in {"rising", "bullish", "up"}
            and prediction in {"pass", "watch", "allow"}
        ):
            return {
                **base,
                "pattern_label": "constructive_momentum_prediction_alignment",
                "directional_bias": "constructive",
                "failure_mode": "momentum_deceleration_or_prediction_deterioration",
                "expected_horizon": "15m_to_60m",
                "confidence": "medium",
            }
        if (
            session in {"fading", "downtrend", "reversal_attempt"}
            or momentum == "decelerating"
            or direction in {"falling", "bearish", "down"}
            or prediction == "block"
        ):
            return {
                **base,
                "pattern_label": "momentum_prediction_risk",
                "directional_bias": "risk_negative",
                "failure_mode": "failed_follow_through_or_prediction_block",
                "expected_horizon": "5m_to_60m",
                "confidence": "medium",
            }
        if session == "rangebound" or momentum == "flat" or direction == "flat":
            return {
                **base,
                "pattern_label": "rangebound_mixed_momentum",
                "directional_bias": "neutral",
                "failure_mode": "chop_or_false_breakout",
                "expected_horizon": "15m_to_60m",
                "confidence": "low",
            }
        return {}

    def _add_analysis_fields(self, row: dict[str, Any]) -> None:
        canonical = self._canonical(row)
        candidate = self._candidate_payload(row)
        if not canonical:
            canonical = self._synthesize_auto_buy_canonical(row, candidate)
            if canonical:
                row["canonical_intelligence_json"] = json.dumps(
                    canonical,
                    sort_keys=True,
                    default=str,
                )
        mappings = {
            "setup_label": ("setup_state", "label"),
            "market_regime": ("regime_state", "market_regime"),
            "session_phase": ("regime_state", "session_phase"),
            "spread_bucket": ("regime_state", "spread_bucket"),
            "participation_state": ("regime_state", "participation_state"),
            "volatility_chase_risk": ("regime_state", "volatility_chase_risk"),
            "execution_quality_decision": (
                "regime_state",
                "execution_quality_decision",
            ),
            "portfolio_decision": ("regime_state", "portfolio_decision"),
            "downside_state": ("regime_state", "downside_state"),
            "utility_decision": (
                "advisory_authority_state",
                "utility_estimate",
                "utility_decision",
            ),
            "confidence_quality": (
                "advisory_authority_state",
                "calibrated_confidence",
                "confidence_quality",
            ),
            "symbol_pattern": ("pattern_state", "pattern_label"),
            "pattern_directional_bias": ("pattern_state", "directional_bias"),
            "pattern_confidence_quality": ("pattern_state", "confidence_quality"),
            "pattern_runtime_effect": ("pattern_state", "runtime_effect"),
            "net_execution_cost_pct": (
                "regime_state",
                "net_execution_cost_pct",
            ),
            "portfolio_duplicate_risk_score": (
                "regime_state",
                "portfolio_duplicate_risk_score",
            ),
            "incremental_var_pct": (
                "regime_state",
                "incremental_var_pct",
            ),
            "beta_contribution_delta": (
                "regime_state",
                "beta_contribution_delta",
            ),
            "crowded_theme": (
                "regime_state",
                "crowded_theme",
            ),
        }
        for output, path in mappings.items():
            if row.get(output) in (None, ""):
                row[output] = self._path(canonical, *path)
        candidate_mappings = {
            "setup_label": "setup_label",
            "session_trend_label": "session_trend_label",
            "session_trend_score": "session_trend_score",
            "session_return_pct": "session_return_pct",
            "session_momentum_5m_pct": "momentum_5m_pct",
            "session_momentum_15m_pct": "momentum_15m_pct",
            "session_momentum_30m_pct": "momentum_30m_pct",
            "session_distance_from_vwap_pct": "distance_from_vwap_pct",
            "symbol_pattern": "symbol_pattern",
            "pattern_runtime_effect": "pattern_runtime_effect",
            "pattern_directional_bias": "pattern_directional_bias",
        }
        for output, key in candidate_mappings.items():
            if row.get(output) in (None, "", "unknown", "mixed_or_unclassified_pattern"):
                value = candidate.get(key)
                if value not in (None, ""):
                    row[output] = value
        pattern = canonical_symbol_pattern_state(canonical)
        if pattern.get("pattern_label") in {
            None,
            "",
            "unknown",
            "mixed_or_unclassified_pattern",
        }:
            pattern = self._historical_symbol_pattern_state(row) or pattern
        pattern_mappings = {
            "symbol_pattern": "pattern_label",
            "pattern_directional_bias": "directional_bias",
            "pattern_confidence_quality": "confidence_quality",
            "pattern_runtime_effect": "runtime_effect",
            "pattern_source": "source",
        }
        for output, key in pattern_mappings.items():
            if row.get(output) in (None, ""):
                row[output] = pattern.get(key)
        decision_time = str(row.get("decision_time") or "")
        row["decision_hour"] = (
            decision_time[11:13]
            if len(decision_time) >= 13 and decision_time[11:13].isdigit()
            else "unknown"
        )
        try:
            cost = float(row.get("net_execution_cost_pct"))
        except Exception:
            cost = None
        if cost is None:
            row["execution_cost_bucket"] = "unknown"
        elif cost <= 0.05:
            row["execution_cost_bucket"] = "low_cost"
        elif cost <= 0.15:
            row["execution_cost_bucket"] = "moderate_cost"
        else:
            row["execution_cost_bucket"] = "high_cost"

    def payload(
        self,
        *,
        start_date: str,
        end_date: str | None = None,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> LifecycleAnalysisPayload:
        end = end_date or start_date
        raw_rows = self.repository.lifecycle_rows(
            start_date=start_date,
            end_date=end,
            symbol=symbol,
            limit=limit,
        )
        if limit is None:
            raw_rows = list(raw_rows) + list(
                self.repository.approved_trade_rows_without_snapshots(
                    start_date=start_date,
                    end_date=end,
                    symbol=symbol,
                )
            )
            raw_rows.sort(
                key=lambda row: (
                    str(dict(row).get("decision_time") or ""),
                    int(dict(row).get("decision_snapshot_id") or 0),
                    int(dict(row).get("trade_id") or 0),
                )
            )
        rows = []
        summary: dict[str, Any] = {
            "rows": 0,
            "approved_with_exit": 0,
            "approved_matched_exit_missing_snapshot": 0,
            "approved_open_or_unlinked_exit": 0,
            "rejected_with_counterfactual": 0,
            "rejected_snapshot_only_no_trade": 0,
            "rejected_without_counterfactual": 0,
        }
        for raw in raw_rows:
            row = dict(raw)
            lifecycle_status = self._classify(row)
            row["lifecycle_status"] = lifecycle_status
            self._add_analysis_fields(row)
            rows.append(row)
            summary["rows"] += 1
            summary[lifecycle_status] += 1

        rejected_trade_backed = (
            summary["rejected_with_counterfactual"] + summary["rejected_without_counterfactual"]
        )
        approved_rows = (
            summary["approved_with_exit"]
            + summary["approved_matched_exit_missing_snapshot"]
            + summary["approved_open_or_unlinked_exit"]
        )
        summary["rejected_counterfactual_coverage_rate"] = (
            round(summary["rejected_with_counterfactual"] / rejected_trade_backed, 4)
            if rejected_trade_backed
            else None
        )
        summary["approved_exit_link_rate"] = (
            round(summary["approved_with_exit"] / approved_rows, 4) if approved_rows else None
        )
        summary["approved_matched_exit_coverage_rate"] = (
            round(
                (summary["approved_with_exit"] + summary["approved_matched_exit_missing_snapshot"])
                / approved_rows,
                4,
            )
            if approved_rows
            else None
        )
        summary["analysis_ready"] = (
            summary["rejected_without_counterfactual"] == 0
            and summary["approved_open_or_unlinked_exit"] == 0
        )

        return LifecycleAnalysisPayload(
            rows=rows,
            start_date=start_date,
            end_date=end,
            symbol=symbol.upper() if symbol else None,
            summary=summary,
        )


def build_default_lifecycle_analysis_service(db_path=None) -> LifecycleAnalysisService:
    repository = (
        LifecycleAnalysisRepository(db_path=db_path)
        if db_path is not None
        else LifecycleAnalysisRepository()
    )
    return LifecycleAnalysisService(repository)
