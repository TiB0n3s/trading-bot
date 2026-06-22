"""Paper-only meta-label authority from historical-bar ensemble evidence."""

from __future__ import annotations

from typing import Any

from services.historical_bar_paper_strategy_service import build_historical_bar_paper_strategy

from trading_bot.learning.labels import (
    DEFAULT_HISTORICAL_BAR_TRAINING_LABELS,
    META_LABEL_AUTHORITY_MIN_TIER,
    labels_support_meta_label_authority,
)
from trading_bot.runtime.authority import AuthorityMatrix


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def evaluate_historical_bar_meta_label_authority(
    *,
    symbol: str | None,
    action: str,
    decision: dict[str, Any],
    account_state: dict[str, Any],
    execution_mode: str,
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return paper-only meta-label approval, veto, or size-lift guidance.

    Layer 1 is the existing incoming buy candidate. This Layer 2 adapter uses
    the historical-bar ensemble to estimate whether that candidate should be
    accepted. It has no broker side effects and is bounded by AuthorityMatrix.
    """
    cfg = _dict(config)
    if action != "buy" or not cfg.get("enabled") or execution_mode not in {"paper", "dry_run"}:
        return {"allowed": False, "effect": "none", "reason": "meta-label authority disabled"}

    # Label-tier authority enforcement (#10): a model may not hold more authority
    # than its weakest primary training label supports. The historical-bar
    # ensemble trains on Tier-4 observe_only_ranking labels (triple_barrier /
    # trend_scan), so it is restricted to ranking/observation and may NOT veto,
    # approve, or size a trade until retrained on higher-tier (realized,
    # cost-aware) labels. A caller can declare actual training labels via
    # cfg["training_labels"]; the default reflects today's Tier-4 reality.
    training_labels = cfg.get("training_labels") or DEFAULT_HISTORICAL_BAR_TRAINING_LABELS
    if not labels_support_meta_label_authority(training_labels):
        return {
            "allowed": False,
            "effect": "none",
            "label_tier_enforced": True,
            "training_labels": list(training_labels),
            "reason": (
                "label_tier_authority_block: meta-label trained on observe-only "
                f"labels {list(training_labels)} (weakest tier > "
                f"{META_LABEL_AUTHORITY_MIN_TIER}); ranking/observation only, no "
                "veto/approve/size authority"
            ),
        }

    matrix = AuthorityMatrix()
    strategy = _dict(account_state.get("historical_bar_paper_strategy"))
    if not strategy and cfg.get("lazy_build_strategy"):
        strategy = build_historical_bar_paper_strategy(
            symbol=symbol,
            action=action,
            account_state=account_state,
        ).to_dict()
        account_state["historical_bar_paper_strategy"] = strategy
    if not strategy:
        return {
            "allowed": False,
            "effect": "none",
            "reason": "historical-bar meta-label not ready: missing historical_bar_paper_strategy",
        }

    score = _float(strategy.get("master_confidence_score"))
    status = str(strategy.get("status") or "").lower()
    recommendation = str(strategy.get("paper_recommendation") or "").lower()
    liquidity_bucket = str(strategy.get("liquidity_stress_bucket") or "").lower()
    baseline_delta = _float(strategy.get("baseline_delta"))

    min_veto_score = float(cfg.get("min_veto_score") or 65.0)
    min_approve_score = float(cfg.get("min_approve_score") or 65.0)
    min_size_increase_score = float(cfg.get("min_size_increase_score") or 75.0)
    min_baseline_delta = float(cfg.get("min_baseline_delta") or 0.0)
    max_position_size_pct = float(cfg.get("max_position_size_pct") or 1.5)
    severe_liquidity_blocks = bool(cfg.get("severe_liquidity_blocks", True))
    can_veto = bool(cfg.get("can_veto", True))

    common = {
        "version": "historical_bar_meta_label_authority_v1",
        "authority_scope": "paper_only_meta_label_after_hard_gates",
        "strategy": strategy,
        "master_confidence_score": score,
        "paper_recommendation": recommendation,
        "baseline_delta": baseline_delta,
        "liquidity_stress_bucket": liquidity_bucket,
    }

    if status != "paper_ready" or score is None:
        return {
            **common,
            "allowed": False,
            "effect": "none",
            "reason": f"historical-bar meta-label not ready: status={status or 'unknown'}",
        }

    veto_reasons: list[str] = []
    if score < min_veto_score:
        veto_reasons.append(f"score={score:.2f} < min_veto_score={min_veto_score:.2f}")
    if baseline_delta is not None and baseline_delta < min_baseline_delta:
        veto_reasons.append(
            f"baseline_delta={baseline_delta:.2f} < min_baseline_delta={min_baseline_delta:.2f}"
        )
    if severe_liquidity_blocks and liquidity_bucket == "severe":
        veto_reasons.append("liquidity_stress_bucket=severe")

    if veto_reasons and can_veto:
        if not matrix.can("historical_bar_meta_label", "block", execution_mode):
            return {
                **common,
                "allowed": False,
                "effect": "none",
                "reason": "authority_matrix_denied_meta_label_veto",
            }
        return {
            **common,
            "allowed": True,
            "effect": "veto",
            "position_size_pct": 0.0,
            "reason": "historical-bar meta-label veto: " + "; ".join(veto_reasons),
            "can_block_trades": True,
            "can_approve_trades": False,
            "can_increase_size": False,
        }

    trade_candidate = recommendation in {"paper_trade_candidate", "paper_size_candidate"}
    if score < min_approve_score or not trade_candidate:
        return {
            **common,
            "allowed": False,
            "effect": "none",
            "reason": (
                "historical-bar meta-label below approval threshold: "
                f"score={score:.2f}; recommendation={recommendation or 'unknown'}"
            ),
        }

    requested_size = _float(decision.get("position_size_pct"))
    if requested_size is None or requested_size <= 0:
        requested_size = _float(account_state.get("position_size_pct")) or 1.0
    strategy_size = _float(strategy.get("paper_position_size_pct"))
    if strategy_size is None or strategy_size <= 0:
        strategy_size = requested_size
    final_size = round(max(0.0, min(max_position_size_pct, max(requested_size, strategy_size))), 4)

    approved = bool(decision.get("approved"))
    if not approved:
        if not matrix.can("historical_bar_meta_label", "approve", execution_mode):
            return {
                **common,
                "allowed": False,
                "effect": "none",
                "reason": "authority_matrix_denied_meta_label_approval",
            }
        return {
            **common,
            "allowed": True,
            "effect": "paper_approval",
            "position_size_pct": final_size,
            "reason": (
                "historical-bar meta-label approved Layer-1 candidate: "
                f"score={score:.2f}; recommendation={recommendation}; "
                f"baseline_delta={baseline_delta}"
            ),
            "can_block_trades": True,
            "can_approve_trades": True,
            "can_increase_size": True,
        }

    if score >= min_size_increase_score and final_size > requested_size:
        if not matrix.can("historical_bar_meta_label", "increase_size", execution_mode):
            return {
                **common,
                "allowed": False,
                "effect": "none",
                "reason": "authority_matrix_denied_meta_label_size_increase",
            }
        return {
            **common,
            "allowed": True,
            "effect": "size_increase",
            "position_size_pct": final_size,
            "original_position_size_pct": requested_size,
            "reason": (
                "historical-bar meta-label increased paper size: "
                f"score={score:.2f}; strategy_size={strategy_size:.2f}; "
                f"max_position_size_pct={max_position_size_pct:.2f}"
            ),
            "can_block_trades": True,
            "can_approve_trades": True,
            "can_increase_size": True,
        }

    return {
        **common,
        "allowed": False,
        "effect": "none",
        "reason": f"historical-bar meta-label clear without override: score={score:.2f}",
    }
