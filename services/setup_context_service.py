"""Setup observation and recent-favorable setup context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


@dataclass(frozen=True)
class SetupContextDeps:
    build_snapshot: Callable[[str], dict[str, Any]]
    evaluate_setup_policy: Callable[[str | None], dict[str, Any]]
    upsert_recent_favorable_setup: Callable[..., None]
    get_recent_favorable_setup: Callable[..., Any]
    now: Callable[[], datetime]
    recent_favorable_setup_ttl_minutes: int
    log: Any
    setup_engine: Any | None = None


FAVORABLE_SETUP_LABELS = {
    "confirmed_near_vwap_recovery",
    "near_vwap_weak_strength_followthrough",
    "oversold_weak_bounce_watch",
}


def observe_setup_policy(setup_label: str | None, deps: SetupContextDeps) -> dict[str, Any]:
    try:
        return deps.evaluate_setup_policy(setup_label)
    except Exception as exc:
        deps.log.warning(f"setup policy evaluation failed for label={setup_label!r}: {exc}")
        return {
            "setup_policy_action": "error",
            "setup_confidence_adjustment": 0,
            "setup_size_multiplier": 1.0,
            "reason": "setup_policy:error",
        }


def build_setup_observation(
    symbol: str,
    action: str,
    price,
    account_state: dict[str, Any],
    deps: SetupContextDeps,
) -> dict[str, Any]:
    if action != "buy":
        return {
            "setup_label": None,
            "setup_policy_action": "not_applicable",
            "setup_policy_reason": "setup_policy:not_applicable:sell",
            "setup_confidence_adjustment": 0,
            "setup_size_multiplier": 1.0,
            "setup_score": None,
            "setup_confidence": None,
            "setup_key": None,
            "setup_rationale": None,
            "setup_unknown_reason": None,
        }

    try:
        snapshot = deps.build_snapshot(symbol)
        setup_quality = build_setup_quality(snapshot, deps)
        setup_label = setup_quality.get("label") or snapshot.get("setup_label")
        setup_policy = observe_setup_policy(setup_label, deps)
        account_state["setup_quality"] = setup_quality

        deps.log.info(
            "Setup policy evaluated: "
            f"symbol={symbol} "
            f"setup_label={setup_label} "
            f"policy_action={setup_policy.get('setup_policy_action')} "
            f"confidence_adjustment={setup_policy.get('setup_confidence_adjustment')} "
            f"size_multiplier={setup_policy.get('setup_size_multiplier')} "
            f"reason={setup_policy.get('reason')}"
        )

        return {
            "setup_label": setup_label,
            "setup_policy_action": setup_policy.get("setup_policy_action"),
            "setup_policy_reason": setup_policy.get("reason"),
            "setup_confidence_adjustment": setup_policy.get("setup_confidence_adjustment"),
            "setup_size_multiplier": setup_policy.get("setup_size_multiplier"),
            "setup_score": setup_quality.get("score"),
            "setup_confidence": setup_quality.get("confidence"),
            "setup_key": setup_quality.get("key"),
            "setup_rationale": setup_quality.get("rationale"),
            "setup_unknown_reason": setup_policy.get("setup_unknown_reason"),
            "setup_quality": setup_quality,
        }
    except Exception as exc:
        unknown_reason = f"{type(exc).__name__}:{str(exc)[:200]}"
        deps.log.warning(f"setup observe-only snapshot failed for {symbol}: {unknown_reason}")
        return {
            "setup_label": None,
            "setup_policy_action": "error",
            "setup_policy_reason": f"setup_policy:error:{exc}",
            "setup_confidence_adjustment": 0,
            "setup_size_multiplier": 1.0,
            "setup_score": None,
            "setup_confidence": None,
            "setup_key": None,
            "setup_rationale": None,
            "setup_unknown_reason": unknown_reason,
        }


def build_setup_quality(snapshot: dict[str, Any], deps: SetupContextDeps) -> dict[str, Any]:
    """Build the live setup-quality object consumed by the decision prompt.

    The feature snapshot is still sourced from the live feature path, but final
    setup classification is owned by SetupEngineService when it is injected.
    """
    result = None
    if deps.setup_engine is not None:
        try:
            result = deps.setup_engine.classify(snapshot)
        except Exception as exc:
            deps.log.warning(f"setup engine classification failed: {exc}")

    if result is not None:
        label = getattr(result, "setup_label", None)
        recommendation = getattr(result, "recommendation", None)
        score = getattr(result, "setup_score", None)
        confidence = getattr(result, "confidence", None)
        key = getattr(result, "setup_key", None)
        rationale = getattr(result, "rationale", None)
        return {
            "label": label,
            "recommendation": recommendation,
            "score": score,
            "confidence": confidence,
            "key": key,
            "rationale": rationale,
            "reasons": rationale,
            "trend_bucket": getattr(result, "trend_bucket", None),
            "vwap_bucket": getattr(result, "vwap_bucket", None),
            "rs_bucket": getattr(result, "rs_bucket", None),
            "sample_basis": getattr(result, "sample_basis", None),
            "source": "setup_engine",
            "snapshot_id": snapshot.get("id"),
            "snapshot_timestamp": snapshot.get("timestamp"),
        }

    return {
        "label": snapshot.get("setup_label"),
        "recommendation": snapshot.get("setup_recommendation"),
        "score": snapshot.get("setup_score"),
        "confidence": snapshot.get("setup_confidence"),
        "key": snapshot.get("setup_key"),
        "rationale": snapshot.get("setup_rationale"),
        "reasons": snapshot.get("setup_rationale"),
        "trend_bucket": None,
        "vwap_bucket": None,
        "rs_bucket": None,
        "sample_basis": None,
        "source": "feature_snapshot",
        "snapshot_id": snapshot.get("id"),
        "snapshot_timestamp": snapshot.get("timestamp"),
    }


def is_favorable_setup_label(setup_label: str | None) -> bool:
    return setup_label in FAVORABLE_SETUP_LABELS


def remember_favorable_setup(
    symbol: str,
    setup_obs: dict[str, Any] | None,
    deps: SetupContextDeps,
) -> None:
    if not symbol or not setup_obs:
        return

    setup_label = setup_obs.get("setup_label")
    setup_policy_action = setup_obs.get("setup_policy_action")

    if setup_policy_action == "boost" or is_favorable_setup_label(setup_label):
        deps.upsert_recent_favorable_setup(
            symbol=symbol,
            observed_at=deps.now().strftime("%Y-%m-%d %H:%M:%S"),
            setup_label=setup_label,
            setup_policy_action=setup_policy_action,
        )


def get_recent_favorable_setup(symbol: str, deps: SetupContextDeps) -> dict[str, Any] | None:
    row = deps.get_recent_favorable_setup(
        symbol=symbol,
        ttl_minutes=deps.recent_favorable_setup_ttl_minutes,
    )
    if not row:
        return None

    observed_at_raw = row["observed_at"]
    try:
        observed_at = datetime.strptime(observed_at_raw, "%Y-%m-%d %H:%M:%S")
        age_minutes = round((deps.now() - observed_at).total_seconds() / 60.0, 2)
    except Exception:
        age_minutes = None

    return {
        "setup_label": row["setup_label"],
        "setup_policy_action": row["setup_policy_action"],
        "observed_at": observed_at_raw,
        "age_minutes": age_minutes,
    }


def is_degraded_setup(setup_obs: dict[str, Any] | None) -> bool:
    setup_obs = setup_obs or {}
    return (
        setup_obs.get("setup_policy_action") == "error"
        or (setup_obs.get("setup_unknown_reason") or "").startswith("unrecognized_label:")
        or (
            setup_obs.get("setup_label") is None
            and setup_obs.get("setup_policy_action") not in ("not_applicable",)
        )
    )


def is_unrecognized_setup_label(setup_obs: dict[str, Any] | None) -> bool:
    return ((setup_obs or {}).get("setup_unknown_reason") or "").startswith("unrecognized_label:")
