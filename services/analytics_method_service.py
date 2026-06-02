"""Analytics-method coverage for canonical decision intelligence.

This module maps existing bot inputs into the common analytics families used
by trading systems. It is intentionally descriptive: it does not fetch data,
approve trades, reject trades, size orders, train models, or submit orders.
"""

from __future__ import annotations

from typing import Any

from services.async_ai_pipeline_architecture_service import async_pipeline_contract
from services.optional_dependency_service import optional_dependency_status
from services.portfolio_ai_toolkit_service import symbol_ai_tool_profile
from services.regime_risk_protocol_service import crash_risk_protocol, reentry_protocol
from services.regime_switching_service import model_routing_matrix


ANALYTICS_METHOD_STATE_VERSION = "analytics_method_state_v1"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _has_any(container: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(_present(container.get(key)) for key in keys)


def _status(active: bool, partial: bool = False) -> str:
    if active:
        return "active"
    if partial:
        return "partial"
    return "not_integrated"


def build_analytics_method_state(
    *,
    symbol: str | None = None,
    context: dict[str, Any] | None = None,
    account_state: dict[str, Any] | None = None,
    compact: bool = True,
) -> dict[str, Any]:
    """Return analytics-family coverage from already-built decision context."""
    context = _dict(context)
    account_state = _dict(account_state)

    prediction = _dict(account_state.get("prediction_gate"))
    event_context = _dict(account_state.get("event_context"))
    session = _dict(account_state.get("session_momentum"))
    momentum = _dict(account_state.get("momentum"))
    setup = _dict(account_state.get("setup_observation"))
    setup_quality = _dict(account_state.get("setup_quality"))
    strategy_memory = _dict(account_state.get("strategy_memory"))
    policy_artifacts = _dict(
        account_state.get("policy_artifacts")
        or account_state.get("policy_artifact_status")
    )
    market_microstructure = _dict(account_state.get("market_microstructure"))
    regime_observation = _dict(account_state.get("regime_observation"))
    market_participation = _dict(account_state.get("market_participation"))
    volatility = _dict(account_state.get("volatility_normalization"))
    downside = _dict(account_state.get("downside_asymmetry"))
    portfolio = _dict(account_state.get("portfolio_decision"))
    execution = _dict(account_state.get("execution_quality"))
    utility = _dict(
        account_state.get("utility_estimate")
        or _dict(account_state.get("decision_policy")).get("utility_estimate")
    )

    predictive_active = _has_any(
        prediction,
        (
            "ml_prediction_score",
            "prediction_score",
            "ml_prediction_bucket",
            "prediction_decision",
        ),
    )
    descriptive_active = any(
        (
            _has_any(
                context,
                (
                    "momentum_pct",
                    "session_return_pct",
                    "session_momentum_30m_pct",
                    "session_momentum_60m_pct",
                    "session_momentum_120m_pct",
                    "volume_surge_ratio",
                ),
            ),
            _has_any(
                session,
                (
                    "session_return_pct",
                    "momentum_30m_pct",
                    "momentum_60m_pct",
                    "momentum_120m_pct",
                    "distance_from_vwap_pct",
                ),
            ),
            _has_any(momentum, ("momentum_pct", "volume_surge_ratio")),
        )
    )
    sentiment_active = _present(event_context.get("available")) or _has_any(
        event_context,
        (
            "event_signal",
            "source_tiers",
            "trusted_source_count",
            "catalyst_score",
        ),
    )
    diagnostic_active = any(
        (
            _present(strategy_memory.get("available")),
            _present(strategy_memory.get("context_matches")),
            _present(policy_artifacts.get("state_hash")),
            _has_any(
                account_state,
                (
                    "decision_policy_outcome",
                    "session_gate_outcome",
                    "setup_quality_outcome",
                    "ml_outcome",
                ),
            ),
        )
    )
    prescriptive_active = any(
        (
            _has_any(account_state, ("decision_policy_outcome", "session_gate_outcome")),
            _has_any(portfolio, ("decision", "size_multiplier")),
            _has_any(execution, ("decision", "net_execution_cost_pct")),
            _has_any(utility, ("utility_decision", "expected_value_pct")),
        )
    )
    risk_active = any(
        (
            _has_any(portfolio, ("incremental_var_pct", "duplicate_risk_score")),
            _has_any(downside, ("downside_score", "downside_state")),
            _has_any(volatility, ("volatility_adjusted_score", "chase_risk")),
            _has_any(execution, ("spread_pct", "net_execution_cost_pct")),
        )
    )
    microstructure_active = _has_any(
        market_microstructure,
        (
            "microstructure_score",
            "liquidity_state",
            "breakout_quality",
            "reversion_risk",
        ),
    )
    pattern_active = _has_any(
        setup,
        ("setup_label", "setup_score", "setup_policy_action"),
    ) or _has_any(
        setup_quality,
        ("label", "score", "structure"),
    )

    analytics_families = {
        "predictive": {
            "status": _status(predictive_active),
            "sources": ["daily_symbol_predictions", "deterministic_prediction_gate"],
            "model_type": prediction.get("ml_prediction_provider") or "deterministic_or_cached_ml",
            "runtime_effect": prediction.get("ml_prediction_runtime_effect"),
        },
        "descriptive": {
            "status": _status(descriptive_active),
            "sources": ["feature_snapshots", "session_momentum", "market_context"],
            "long_horizon_momentum": _has_any(
                context,
                ("session_momentum_60m_pct", "session_momentum_120m_pct"),
            ) or _has_any(session, ("momentum_60m_pct", "momentum_120m_pct")),
        },
        "diagnostic": {
            "status": _status(diagnostic_active),
            "sources": ["strategy_memory", "policy_artifacts", "post_session_reports"],
            "artifact_state_hash": policy_artifacts.get("state_hash"),
        },
        "prescriptive": {
            "status": _status(prescriptive_active),
            "sources": ["decision_policy", "sizing_policy", "portfolio_decision", "execution_quality"],
            "authority": "policy_gated_runtime",
        },
        "sentiment_nlp": {
            "status": _status(sentiment_active),
            "sources": ["daily_symbol_events", "news_event_model", "market_brief"],
            "trusted_source_count": event_context.get("trusted_source_count"),
            "source_tiers": event_context.get("source_tiers") or [],
        },
        "pattern_recognition": {
            "status": _status(pattern_active),
            "sources": ["setup_engine", "setup_structure_service"],
        },
        "risk_analytics": {
            "status": _status(risk_active),
            "sources": ["portfolio_decision", "downside_asymmetry", "volatility_normalization", "execution_quality"],
            "var_proxy_available": _present(portfolio.get("incremental_var_pct")),
        },
        "high_frequency_microstructure": {
            "status": _status(microstructure_active, partial=_has_any(execution, ("spread_pct",))),
            "sources": ["market_microstructure_service", "execution_quality"],
            "order_book_depth_available": False,
            "order_flow_toxicity_available": False,
        },
        "alternative_data": {
            "status": "not_integrated",
            "sources": [],
            "supported_inputs": [],
            "note": "satellite, card, and shipping-manifest feeds are not wired into this bot",
        },
        "reinforcement_learning": {
            "status": "not_integrated",
            "sources": [],
            "runtime_effect": "none",
        },
    }

    active_families = [
        name
        for name, item in analytics_families.items()
        if item.get("status") in {"active", "partial"}
    ]
    gaps = [
        name
        for name, item in analytics_families.items()
        if item.get("status") == "not_integrated"
    ]

    deps = optional_dependency_status()
    dependency_payload = (
        {
            "runtime_effect": deps.get("runtime_effect"),
            "available_count": deps.get("available_count"),
            "missing_count": deps.get("missing_count"),
            "available": deps.get("available") or [],
            "missing": deps.get("missing") or [],
        }
        if compact
        else deps
    )
    pipeline = async_pipeline_contract()
    pipeline_payload = (
        {
            "version": pipeline.get("version"),
            "runtime_effect": pipeline.get("runtime_effect"),
            "flow": pipeline.get("flow"),
            "storage": {
                "preferred": (pipeline.get("storage") or {}).get("preferred"),
                "current_repo_default": (pipeline.get("storage") or {}).get("current_repo_default"),
                "status": (pipeline.get("storage") or {}).get("status"),
            },
            "task_queue": {
                "preferred": (pipeline.get("task_queue") or {}).get("preferred"),
                "status": (pipeline.get("task_queue") or {}).get("status"),
            },
            "guardrails": pipeline.get("guardrails"),
        }
        if compact
        else pipeline
    )

    return {
        "version": ANALYTICS_METHOD_STATE_VERSION,
        "runtime_effect": "canonical_audit_and_ml_context_only",
        "optional_dependency_status": dependency_payload,
        "portfolio_toolkit": symbol_ai_tool_profile(symbol),
        "model_router": {
            "status": "contract_defined",
            "current_regime_id": regime_observation.get("regime_id"),
            "current_regime_label": regime_observation.get("regime_label"),
            "routing_matrix": model_routing_matrix(),
        },
        "async_pipeline": pipeline_payload,
        "risk_protocols": {
            "crash": crash_risk_protocol(
                regime_history=account_state.get("regime_history") or [],
                lockout_active=bool(account_state.get("risk_lockout_active")),
            ).to_dict(),
            "reentry": reentry_protocol(
                current_regime=regime_observation.get("regime_id"),
                stability_counter=int(account_state.get("regime_stability_counter") or 0),
                current_status=str(account_state.get("system_status") or "normal"),
            ).to_dict(),
        },
        "active_family_count": len(active_families),
        "active_families": active_families,
        "gaps": gaps,
        "families": analytics_families,
        "guardrails": {
            "no_new_trade_authority": True,
            "no_unverified_alternative_data": True,
            "model_type_not_inferred_from_marketing_terms": True,
        },
    }
