"""Observe-only runtime regime observation and model-routing context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from repositories.regime_repo import fetch_spy_closes
from services.regime_model_router_service import route_to_model
from services.regime_switching_service import (
    detect_regime,
    infer_regime_from_artifact,
    load_regime_state,
    save_regime_state,
)


@dataclass(frozen=True)
class RegimeObservationService:
    """Build the current regime/router payload for decision snapshots.

    This service is intentionally observe-only. It does not approve, reject,
    size, submit orders, or mutate risk lockout state.
    """

    base_dir: Path
    artifact_path: Path | None = None
    state_path: Path | None = None
    fetch_closes: Callable[[int], list[float]] = fetch_spy_closes
    save_state: bool = True
    log: Any | None = None

    def observe(self, *, closes_limit: int = 60) -> dict[str, Any]:
        artifact = self.artifact_path or (
            self.base_dir / "ml" / "models" / "regime_hmm_v1" / "model.joblib"
        )
        state_file = self.state_path or self.base_dir / "runtime_state" / "regime_state.json"
        closes = self.fetch_closes(int(closes_limit))
        state = load_regime_state(state_file)
        history = state.get("history") if isinstance(state, dict) else []
        history = history if isinstance(history, list) else []

        try:
            if artifact.exists():
                observation = infer_regime_from_artifact(
                    closes=closes,
                    artifact_path=artifact,
                    regime_history=history,
                )
                source = "hmm_artifact"
            else:
                observation = detect_regime(closes=closes, regime_history=history)
                source = "deterministic_fallback"
        except Exception as exc:
            observation = detect_regime(closes=closes, regime_history=history)
            source = "deterministic_fallback_after_error"
            if self.log is not None:
                self.log.warning(f"regime observation fallback after error: {exc}")

        if self.save_state:
            try:
                save_regime_state(state_file, observation)
            except Exception as exc:
                if self.log is not None:
                    self.log.warning(f"regime state persistence failed: {exc}")

        routing = route_to_model(observation)
        return {
            "regime_observation": observation.to_dict(),
            "regime_routing_decision": routing.to_dict(),
            "regime_observation_source": source,
            "regime_artifact_path": str(artifact),
            "regime_artifact_exists": artifact.exists(),
            "regime_state_path": str(state_file),
            "regime_closes_available": len(closes),
            "runtime_effect": "observe_only_no_order_authority",
        }


def build_default_regime_observation_service(
    *,
    base_dir: Path,
    log: Any | None = None,
) -> RegimeObservationService:
    return RegimeObservationService(base_dir=base_dir, log=log)
