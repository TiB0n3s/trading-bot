"""Decision snapshot row construction and persistence."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repositories.decision_snapshot_repo import DecisionSnapshotRepository
from symbols_config import SYMBOL_UNIVERSE_VERSION


ENV_PROFILE_KEYS = (
    "EXECUTION_MODE",
    "LIVE_TRADING_ENABLED",
    "PREDICTION_GATE_MODE",
    "ML_PLATFORM_ENABLED",
    "ML_PREDICTION_PROVIDER_ENABLED",
    "AUTO_BUY_LIVE_BUYS",
    "AUTO_BUY_MIN_SCORE",
    "AUTO_BUY_MAX_ORDERS_PER_RUN",
    "AUTO_BUY_MAX_DAILY_ORDERS",
    "POSITION_MOMENTUM_AUTO_SELL",
    "POLICY_ARTIFACTS_ENABLED",
)


SNAPSHOT_CONTEXT_FIELDS = (
    "macro_regime",
    "risk_multiplier",
    "market_bias",
    "market_bias_effective",
    "market_bias_override_reason",
    "fundamental_score",
    "risk_level",
    "entry_quality",
    "trend_direction",
    "trend_strength",
    "momentum_direction",
    "momentum_pct",
    "momentum_acceleration_pct",
    "momentum_state",
    "volume_surge_ratio",
    "volume_state",
    "extension_from_recent_base_pct",
    "rolling_special_labels",
    "prior_session_return_pct",
    "prior_session_participated",
    "tape_label_at_signal",
    "tape_bar_age_seconds",
    "session_trend_label",
    "session_trend_score",
    "session_return_pct",
    "session_momentum_5m_pct",
    "session_momentum_15m_pct",
    "session_momentum_30m_pct",
    "session_distance_from_vwap_pct",
    "session_momentum_reason",
    "correlation_cluster",
    "cluster_exposure_pct",
)


def json_dumps(value: Any) -> str:
    return json.dumps(value or {}, sort_keys=True, default=str)


def file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DecisionSnapshotService:
    def __init__(
        self,
        *,
        repository: DecisionSnapshotRepository,
        base_dir: Path,
        market_context_path: Path | None = None,
    ):
        self.repository = repository
        self.base_dir = Path(base_dir)
        self.market_context_path = market_context_path or self.base_dir / "market_context.json"

    def git_sha(self) -> str | None:
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=self.base_dir,
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).strip()
        except Exception:
            return None

    def market_context_metadata(self, path: Path | None = None) -> dict[str, Any]:
        path = path or self.market_context_path
        meta: dict[str, Any] = {
            "market_context_date": None,
            "market_context_hash": file_sha256(path),
            "market_context_mtime": None,
        }
        if not path.exists():
            return meta

        try:
            stat = path.stat()
            meta["market_context_mtime"] = datetime.fromtimestamp(
                stat.st_mtime,
                timezone.utc,
            ).isoformat()
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                meta["market_context_date"] = data.get("market_date")
        except Exception:
            pass

        return meta

    def env_profile_hash(self) -> str:
        values = {key: os.getenv(key) for key in ENV_PROFILE_KEYS}
        return hashlib.sha256(json_dumps(values).encode("utf-8")).hexdigest()

    def record_decision_snapshot(
        self,
        *,
        trade_id: int | None,
        timestamp: str,
        source: str,
        symbol: str | None,
        action: str | None,
        signal_price: float | None,
        decision: dict[str, Any] | None,
        order: dict[str, Any] | None,
        context: dict[str, Any] | None,
        account_state: dict[str, Any] | None = None,
        raw_signal: dict[str, Any] | None = None,
        rejection_reason: str | None = None,
    ) -> int:
        decision = decision or {}
        order = order or {}
        context = context or {}
        account_state = account_state or {}
        setup_obs = account_state.get("setup_observation") or {}
        prediction_gate = account_state.get("prediction_gate") or {}
        strategy_observation = account_state.get("strategy_observation") or {}
        trader_brain = strategy_observation.get("trader_brain") or {}
        buy_opportunity = account_state.get("buy_opportunity") or {}

        approved = bool(decision.get("approved"))
        final_decision = (
            "approved"
            if approved
            else decision.get("decision")
            or decision.get("status")
            or "rejected"
        )

        row = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "decision_time": timestamp,
            "trade_id": trade_id,
            "source": source,
            "symbol": symbol,
            "action": action,
            "signal_price": signal_price,
            "final_decision": final_decision,
            "approved": 1 if approved else 0,
            "rejection_reason": rejection_reason if not approved else None,
            "order_id": order.get("order_id"),
            "order_status": order.get("status"),
            "confidence": decision.get("confidence"),
            "position_size_pct": decision.get("position_size_pct"),
            "stop_loss_pct": decision.get("stop_loss_pct"),
            "take_profit_pct": decision.get("take_profit_pct"),
            "prediction_score": prediction_gate.get("prediction_score"),
            "prediction_decision": prediction_gate.get("prediction_decision"),
            "prediction_reason": prediction_gate.get("prediction_reason"),
            "setup_label": setup_obs.get("setup_label"),
            "setup_policy_action": setup_obs.get("setup_policy_action"),
            "setup_policy_reason": setup_obs.get("setup_policy_reason"),
            "setup_confidence_adjustment": setup_obs.get("setup_confidence_adjustment"),
            "setup_size_multiplier": setup_obs.get("setup_size_multiplier"),
            "setup_score": setup_obs.get("setup_score"),
            "setup_rationale": setup_obs.get("setup_rationale"),
            "buy_opportunity_score": buy_opportunity.get("buy_opportunity_score"),
            "buy_opportunity_recommendation": buy_opportunity.get("buy_opportunity_recommendation"),
            "buy_opportunity_reason": buy_opportunity.get("buy_opportunity_reason"),
            "trader_brain_score": trader_brain.get("score"),
            "trader_brain_setup_type": trader_brain.get("setup_type"),
            "trader_brain_approved": (
                1
                if trader_brain.get("approved_by_scorer") is True
                else 0
                if trader_brain.get("approved_by_scorer") is False
                else None
            ),
            "trader_brain_reason": trader_brain.get("reason"),
            "symbol_universe_version": SYMBOL_UNIVERSE_VERSION,
            "env_profile_hash": self.env_profile_hash(),
            "git_sha": self.git_sha(),
            "raw_signal_json": json_dumps(raw_signal),
            "decision_json": json_dumps(decision),
            "order_json": json_dumps(order),
            "account_state_json": json_dumps(account_state),
            **self.market_context_metadata(),
        }
        for field in SNAPSHOT_CONTEXT_FIELDS:
            row[field] = context.get(field)

        return self.repository.insert_snapshot(row)

    def summarize_snapshots(self, target_date: str) -> dict[str, Any]:
        return self.repository.summarize_snapshots(target_date)


def build_default_decision_snapshot_service(
    *,
    db_path: Path | str | None = None,
    base_dir: Path,
) -> DecisionSnapshotService:
    return DecisionSnapshotService(
        repository=DecisionSnapshotRepository(db_path),
        base_dir=base_dir,
    )
