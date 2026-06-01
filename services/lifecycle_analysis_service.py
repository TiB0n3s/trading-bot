"""Analysis service for canonical entry/exit lifecycle rows."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository


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
    def _path(data: dict[str, Any], *path: str) -> Any:
        cur: Any = data
        for key in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(key)
        return cur

    def _add_analysis_fields(self, row: dict[str, Any]) -> None:
        canonical = self._canonical(row)
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
        rows = []
        summary: dict[str, Any] = {
            "rows": 0,
            "approved_with_exit": 0,
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
            summary["rejected_with_counterfactual"]
            + summary["rejected_without_counterfactual"]
        )
        approved_rows = (
            summary["approved_with_exit"]
            + summary["approved_open_or_unlinked_exit"]
        )
        summary["rejected_counterfactual_coverage_rate"] = (
            round(summary["rejected_with_counterfactual"] / rejected_trade_backed, 4)
            if rejected_trade_backed
            else None
        )
        summary["approved_exit_link_rate"] = (
            round(summary["approved_with_exit"] / approved_rows, 4)
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
