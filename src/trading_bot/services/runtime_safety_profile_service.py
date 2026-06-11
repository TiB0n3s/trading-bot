"""Runtime safety profile validation.

This service is intentionally small and deterministic so startup wrappers can
fail fast before unsafe live authority combinations reach the trading path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from trading_bot.config.authority_modes import normalize_config_authority_mode

SAFETY_PROFILE_VERSION = "runtime_safety_profile_v1"


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RuntimeSafetyProfile:
    execution_mode: str
    live_trading_enabled: bool
    ml_authority_mode: str
    decision_policy_authority_mode: str
    prediction_gate_authority_mode: str
    transformer_authority_enabled: bool
    transformer_model_id: str

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "version": SAFETY_PROFILE_VERSION,
            "execution_mode": self.execution_mode,
            "live_trading_enabled": self.live_trading_enabled,
            "ml_authority_mode": self.ml_authority_mode,
            "decision_policy_authority_mode": self.decision_policy_authority_mode,
            "prediction_gate_authority_mode": self.prediction_gate_authority_mode,
            "transformer_authority_enabled": self.transformer_authority_enabled,
            "transformer_model_id_configured": bool(self.transformer_model_id),
        }
        payload["safety_profile_hash"] = safety_profile_hash(payload)
        return payload


def safety_profile_hash(payload: dict[str, Any]) -> str:
    stable = json.dumps(
        {k: v for k, v in payload.items() if k != "safety_profile_hash"},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]


def build_runtime_safety_profile(env: dict[str, str]) -> RuntimeSafetyProfile:
    execution_mode = str(env.get("EXECUTION_MODE", "paper")).strip().lower()
    return RuntimeSafetyProfile(
        execution_mode=execution_mode,
        live_trading_enabled=_bool(env.get("LIVE_TRADING_ENABLED", "false")),
        ml_authority_mode=normalize_config_authority_mode(
            env.get("ML_AUTHORITY_MODE", "observe"),
            default="observe",
        ),
        decision_policy_authority_mode=normalize_config_authority_mode(
            env.get("DECISION_POLICY_AUTHORITY_MODE", "paper_block"),
            default="paper_block",
        ),
        prediction_gate_authority_mode=normalize_config_authority_mode(
            env.get("PREDICTION_GATE_MODE", "warn"),
            default="warn",
        ),
        transformer_authority_enabled=_bool(env.get("TRANSFORMER_AUTHORITY_ENABLED", "false")),
        transformer_model_id=str(env.get("TRANSFORMER_MODEL_ID", "")).strip(),
    )


def runtime_safety_warnings(profile: RuntimeSafetyProfile) -> list[str]:
    warnings: list[str] = []
    live_mode = profile.execution_mode in {"cash_safe", "cash_full"}
    if live_mode and not profile.live_trading_enabled:
        warnings.append("cash execution mode requires LIVE_TRADING_ENABLED=true")
    if profile.execution_mode == "cash_full":
        warnings.append("cash_full requires explicit operator startup approval")
    if live_mode and profile.ml_authority_mode == "live_block":
        warnings.append("live ML block authority requires current promotion evidence")
    if live_mode and profile.prediction_gate_authority_mode == "live_block":
        warnings.append("live prediction hard-block authority requires current promotion evidence")
    if profile.transformer_authority_enabled and not profile.transformer_model_id:
        warnings.append("transformer authority enabled without TRANSFORMER_MODEL_ID")
    return warnings


def validate_runtime_safety_profile(
    env: dict[str, str],
    *,
    fail_fast: bool | None = None,
) -> dict[str, Any]:
    profile = build_runtime_safety_profile(env)
    warnings = runtime_safety_warnings(profile)
    should_fail_fast = (
        _bool(env.get("RUNTIME_SAFETY_PROFILE_FAIL_FAST", "true"))
        if fail_fast is None
        else fail_fast
    )
    payload = profile.to_dict()
    payload.update(
        {
            "runtime_effect": "startup_validation_fail_fast"
            if should_fail_fast
            else "startup_validation_warn_only",
            "warnings": warnings,
            "ready": not warnings,
            "fail_fast": should_fail_fast,
        }
    )
    if should_fail_fast and warnings:
        raise RuntimeError("unsafe runtime safety profile: " + "; ".join(warnings))
    return payload
