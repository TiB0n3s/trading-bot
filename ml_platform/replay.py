"""Shadow replay for policy comparison.

replay_decisions_v1 reads decision_snapshots from the DB, re-runs
evaluate_decision_policy with the stored account_state, and reports where
the replayed policy differs from what was recorded.

This is read-only and observe-only. It does not change orders, risk controls,
broker behavior, or any live trading state.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ml_platform.config import DEFAULT_DB_PATH
from ml_platform.governance import BASELINE_POLICIES, FRICTION_ASSUMPTIONS
from ml_platform.pit_context import get_archive_root, select_pit_context
from repositories.training_data_repo import TrainingDataRepository

DEFAULT_ROUND_TRIP_FRICTION_BPS = 10.0
POLICY_ALLOW_DECISIONS = {"allow", "size_down"}
POLICY_BLOCK_DECISIONS = {"block"}


@dataclass(frozen=True)
class ReplayDecisionSummary:
    start_date: str
    end_date: str
    policy: str
    candidate_model: str
    status: str = "scaffold_only_no_runtime_effect"
    same_decision_count: int | None = None
    changed_decision_count: int | None = None
    approved_fewer: int | None = None
    approved_more: int | None = None
    avoided_losers: int | None = None
    missed_winners: int | None = None
    net_simulated_delta: float | None = None
    worst_changed_decision: dict[str, Any] | None = None
    best_changed_decision: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["required_baselines"] = BASELINE_POLICIES
        data["required_friction_assumptions"] = FRICTION_ASSUMPTIONS
        data["note"] = (
            "This command defines the replay output contract only. It does not "
            "load models, change orders, or alter runtime decisions."
        )
        return data


def replay_decisions_scaffold(
    *,
    start_date: str,
    end_date: str,
    policy: str,
    candidate_model: str,
) -> dict[str, Any]:
    return ReplayDecisionSummary(
        start_date=start_date,
        end_date=end_date,
        policy=policy,
        candidate_model=candidate_model,
    ).to_dict()


@dataclass
class ReplayRow:
    snapshot_id: int
    trade_id: int | None
    symbol: str
    action: str
    decision_time: str
    stored_policy_decision: str | None
    stored_policy_reason: str | None
    replayed_policy_decision: str | None
    replayed_policy_reason: str | None
    replayed_policy_size_multiplier: float | None
    final_decision: str | None
    approved: bool
    rejection_reason: str | None
    rejection_bucket: str | None
    outcome_source: str | None
    outcome_status: str | None
    outcome_horizon: str | None
    gross_outcome_pct: float | None
    friction_bps: float
    net_simulated_delta_pct: float | None
    delta_classification: str | None
    changed: bool
    pit_archive_id: str | None       # archive used for strategy_memory injection
    pit_strategy_memory_source: str  # "archived" | "live_fallback" | "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReplayDecisionsV1Result:
    start_date: str
    end_date: str
    policy: str
    status: str
    snapshots_evaluated: int
    snapshots_skipped_no_account_state: int
    same_decision_count: int
    changed_decision_count: int
    changed_to_block: int
    changed_to_allow: int
    changed_to_size_down: int
    realized_outcomes_available: int
    rejected_outcomes_available: int
    evaluated_rows_with_joined_outcome: int
    approved_fewer: int
    approved_more: int
    avoided_losers: int
    missed_winners: int
    recovered_missed_winners: int
    introduced_losers: int
    hard_gate_reject_changes: int
    policy_relevant_reject_changes: int
    changed_rows_with_outcomes: int
    net_simulated_delta_pct: float
    gross_simulated_delta_pct: float
    friction_bps_per_changed_trade: float
    friction_assumptions: dict[str, Any]
    worst_changed_decision: dict[str, Any] | None
    best_changed_decision: dict[str, Any] | None
    changed_rows: list[dict[str, Any]] = field(default_factory=list)
    pit_archive_coverage: dict[str, Any] = field(default_factory=dict)
    pit_rows_with_archived_memory: int = 0
    pit_rows_using_live_fallback: int = 0
    note: str = (
        "Read-only replay. No orders, risk controls, or live decisions were changed. "
        "The replayed policy uses evaluate_decision_policy with stored account_state_json. "
        "When a point-in-time archive with full policy artifacts exists for the decision date, "
        "archived strategy_memory is injected so replay uses the version from that time. "
        "Decision deltas are audit estimates only and use fixed friction assumptions."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_snapshots(
    start_date: str,
    end_date: str,
    db_path: Path | str,
) -> list[Any]:
    return TrainingDataRepository(db_path).replay_snapshot_rows(start_date, end_date)


def _load_realized_outcomes(
    start_date: str,
    end_date: str,
    db_path: Path | str,
) -> dict[int, dict[str, Any]]:
    """Load realized outcomes for approved BUY trades.

    matched_trades does not carry trade_id today, so this joins through the
    exact FIFO entry timestamp/symbol recorded by the trade matcher.
    """
    rows = TrainingDataRepository(db_path).replay_realized_outcome_rows(
        start_date,
        end_date,
    )

    outcomes: dict[int, dict[str, Any]] = {}
    for row in rows:
        capital = _to_float(row["capital_at_risk"]) or 0.0
        pnl = _to_float(row["realized_pnl"]) or 0.0
        pct = (pnl / capital * 100.0) if capital > 0 else None
        outcomes[int(row["trade_id"])] = {
            "source": "matched_trades",
            "status": "realized",
            "horizon": "realized_exit",
            "gross_outcome_pct": round(pct, 6) if pct is not None else None,
            "realized_pnl": round(pnl, 2),
            "matched_exit_count": int(row["matched_exit_count"] or 0),
            "first_exit_timestamp": row["first_exit_timestamp"],
            "last_exit_timestamp": row["last_exit_timestamp"],
        }
    return outcomes


def _load_rejected_outcomes(
    start_date: str,
    end_date: str,
    db_path: Path | str,
) -> dict[int, dict[str, Any]]:
    rows = TrainingDataRepository(db_path).replay_rejected_outcome_rows(
        start_date,
        end_date,
    )

    outcomes: dict[int, dict[str, Any]] = {}
    for row in rows:
        horizon, gross = _best_rejected_return(row)
        outcomes[int(row["trade_id"])] = {
            "source": "rejected_signal_outcomes",
            "status": row["label_status"],
            "partial_reason": row["partial_reason"],
            "horizon": horizon,
            "gross_outcome_pct": gross,
            "max_favorable_60m": _to_float(row["max_favorable_60m"]),
            "max_adverse_60m": _to_float(row["max_adverse_60m"]),
        }
    return outcomes


def _best_rejected_return(row: Any | dict[str, Any]) -> tuple[str | None, float | None]:
    for horizon in ("return_60m", "return_30m", "return_15m", "return_5m", "return_eod"):
        value = _to_float(row[horizon])
        if value is not None:
            return horizon, value
    return None, None


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _is_policy_allow(decision: str | None) -> bool:
    return (decision or "").lower() in POLICY_ALLOW_DECISIONS


def _is_policy_block(decision: str | None) -> bool:
    return (decision or "").lower() in POLICY_BLOCK_DECISIONS


def _reject_bucket(rejection_reason: str | None, stored_reason: str | None = None) -> str | None:
    reason = f"{rejection_reason or ''} {stored_reason or ''}".lower()
    if not reason.strip():
        return None
    hard_markers = (
        "hard gate",
        "circuit_breaker",
        "daily_loss",
        "market_closed",
        "macro_position_limit",
        "max_positions",
        "disabled",
        "cooldown",
        "recent_sell",
        "duplicate",
        "ghost_sell",
        "correlation_cluster",
        "no open alpaca position",
    )
    if any(marker in reason for marker in hard_markers):
        return "hard_gate_reject"
    return "policy_relevant_reject"


def _decision_delta(
    *,
    approved: bool,
    replayed_decision: str | None,
    outcome: dict[str, Any] | None,
    friction_bps: float,
) -> tuple[float | None, float | None, str | None]:
    """Return gross outcome pct, net simulated delta pct, and classification."""
    if not outcome:
        return None, None, None

    gross = _to_float(outcome.get("gross_outcome_pct"))
    if gross is None:
        return None, None, None

    friction_pct = friction_bps / 100.0
    if approved and _is_policy_block(replayed_decision):
        net = -gross - friction_pct
        if gross < 0:
            classification = "avoided_loser"
        elif gross > 0:
            classification = "missed_winner"
        else:
            classification = "avoided_flat_trade"
        return gross, round(net, 6), classification

    if (not approved) and _is_policy_allow(replayed_decision):
        net = gross - friction_pct
        if gross > 0:
            classification = "recovered_missed_winner"
        elif gross < 0:
            classification = "introduced_loser"
        else:
            classification = "introduced_flat_trade"
        return gross, round(net, 6), classification

    return gross, None, None


def replay_decisions_v1(
    *,
    start_date: str,
    end_date: str,
    policy: str = "current",
    db_path: Path | str = DEFAULT_DB_PATH,
    max_changed_rows: int = 50,
    friction_bps: float = DEFAULT_ROUND_TRIP_FRICTION_BPS,
) -> dict[str, Any]:
    """Re-run evaluate_decision_policy against stored decision_snapshots.

    Read-only. Does not affect orders, risk gates, or broker state.

    When a point-in-time archive exists for a decision's date and contains full
    policy artifact content, the archived strategy_memory is injected into
    evaluate_decision_policy so the replay uses the version from that time rather
    than the current live strategy_memory.json.
    """
    from decision_policy import evaluate_decision_policy

    rows = _load_snapshots(start_date, end_date, db_path)
    realized_outcomes = _load_realized_outcomes(start_date, end_date, db_path)
    rejected_outcomes = _load_rejected_outcomes(start_date, end_date, db_path)

    # Pre-cache date → PIT archive for the replay window. Each unique decision
    # date gets one archive lookup; cache by date string to avoid repeated reads.
    archive_root = get_archive_root(Path(db_path).parent)
    _date_archive_cache: dict[str, Any] = {}

    def _get_archive_for_date(date_str: str):
        if date_str not in _date_archive_cache:
            _date_archive_cache[date_str] = select_pit_context(date_str, archive_root)
        return _date_archive_cache[date_str]

    pit_archive_coverage: dict[str, str | None] = {}

    same = 0
    changed = 0
    changed_to_block = 0
    changed_to_allow = 0
    changed_to_size_down = 0
    evaluated_rows_with_joined_outcome = 0
    approved_fewer = 0
    approved_more = 0
    avoided_losers = 0
    missed_winners = 0
    recovered_missed_winners = 0
    introduced_losers = 0
    hard_gate_reject_changes = 0
    policy_relevant_reject_changes = 0
    changed_rows_with_outcomes = 0
    gross_simulated_delta_pct = 0.0
    net_simulated_delta_pct = 0.0
    skipped = 0
    pit_rows_with_archived_memory = 0
    pit_rows_using_live_fallback = 0
    changed_rows: list[dict[str, Any]] = []
    scored_changed_rows: list[dict[str, Any]] = []

    for row in rows:
        account_state_json = row["account_state_json"]
        if not account_state_json:
            skipped += 1
            continue

        try:
            account_state = json.loads(account_state_json)
        except Exception:
            skipped += 1
            continue

        symbol = row["symbol"] or ""
        intelligence_context = account_state.get("intelligence_context") or {}
        stored_dp = account_state.get("decision_policy") or {}
        stored_decision = stored_dp.get("decision")

        # Look up the PIT archive for this decision's date.
        decision_date = (row["decision_time"] or "")[:10]
        pit_record = _get_archive_for_date(decision_date) if decision_date else None
        archived_strategy_memory = None
        pit_archive_id = None
        pit_memory_source = "none"

        if pit_record is not None:
            pit_archive_id = pit_record.archive_id
            pit_archive_coverage[decision_date] = pit_record.archive_id
            if pit_record.strategy_memory is not None:
                archived_strategy_memory = pit_record.strategy_memory
                pit_memory_source = "archived"
                pit_rows_with_archived_memory += 1
            else:
                pit_memory_source = "live_fallback"
                pit_rows_using_live_fallback += 1
        else:
            pit_archive_coverage[decision_date] = None
            pit_memory_source = "live_fallback"
            pit_rows_using_live_fallback += 1

        try:
            replayed = evaluate_decision_policy(
                symbol=symbol,
                action="buy",
                intelligence_context=intelligence_context,
                account_state=account_state,
                strategy_memory_override=archived_strategy_memory,
            )
        except Exception:
            skipped += 1
            continue

        replayed_decision = replayed.get("decision")
        trade_id = _to_int(row["trade_id"])
        approved = bool(row["approved"])
        outcome = None
        if trade_id is not None:
            if approved:
                outcome = realized_outcomes.get(trade_id)
            else:
                outcome = rejected_outcomes.get(trade_id)
        if outcome is not None:
            evaluated_rows_with_joined_outcome += 1
        gross_outcome_pct, net_delta_pct, delta_classification = _decision_delta(
            approved=approved,
            replayed_decision=replayed_decision,
            outcome=outcome,
            friction_bps=friction_bps,
        )
        rejection_bucket = None
        if not approved:
            rejection_bucket = _reject_bucket(row["rejection_reason"], stored_dp.get("reason"))

        replay_row = ReplayRow(
            snapshot_id=int(row["id"]),
            trade_id=trade_id,
            symbol=symbol,
            action="buy",
            decision_time=row["decision_time"] or "",
            stored_policy_decision=stored_decision,
            stored_policy_reason=stored_dp.get("reason"),
            replayed_policy_decision=replayed_decision,
            replayed_policy_reason=replayed.get("reason"),
            replayed_policy_size_multiplier=replayed.get("size_multiplier"),
            final_decision=row["final_decision"],
            approved=approved,
            rejection_reason=row["rejection_reason"],
            rejection_bucket=rejection_bucket,
            outcome_source=(outcome or {}).get("source"),
            outcome_status=(outcome or {}).get("status"),
            outcome_horizon=(outcome or {}).get("horizon"),
            gross_outcome_pct=gross_outcome_pct,
            friction_bps=friction_bps,
            net_simulated_delta_pct=net_delta_pct,
            delta_classification=delta_classification,
            changed=(stored_decision != replayed_decision),
            pit_archive_id=pit_archive_id,
            pit_strategy_memory_source=pit_memory_source,
        )

        if replay_row.changed:
            changed += 1
            if replayed_decision == "block":
                changed_to_block += 1
            elif replayed_decision == "allow":
                changed_to_allow += 1
            elif replayed_decision == "size_down":
                changed_to_size_down += 1

            if approved and _is_policy_block(replayed_decision):
                approved_fewer += 1
            if (not approved) and _is_policy_allow(replayed_decision):
                approved_more += 1
            if (not approved) and rejection_bucket == "hard_gate_reject":
                hard_gate_reject_changes += 1
            if (not approved) and rejection_bucket == "policy_relevant_reject":
                policy_relevant_reject_changes += 1

            if delta_classification == "avoided_loser":
                avoided_losers += 1
            elif delta_classification == "missed_winner":
                missed_winners += 1
            elif delta_classification == "recovered_missed_winner":
                recovered_missed_winners += 1
            elif delta_classification == "introduced_loser":
                introduced_losers += 1

            replay_dict = replay_row.to_dict()
            if net_delta_pct is not None:
                changed_rows_with_outcomes += 1
                gross_simulated_delta_pct += gross_outcome_pct or 0.0
                net_simulated_delta_pct += net_delta_pct
                scored_changed_rows.append(replay_dict)
            if len(changed_rows) < max_changed_rows:
                changed_rows.append(replay_dict)
        else:
            same += 1

    worst_changed_decision = None
    best_changed_decision = None
    if scored_changed_rows:
        worst_changed_decision = min(
            scored_changed_rows,
            key=lambda r: r["net_simulated_delta_pct"],
        )
        best_changed_decision = max(
            scored_changed_rows,
            key=lambda r: r["net_simulated_delta_pct"],
        )

    result = ReplayDecisionsV1Result(
        start_date=start_date,
        end_date=end_date,
        policy=policy,
        status="complete",
        snapshots_evaluated=len(rows) - skipped,
        snapshots_skipped_no_account_state=skipped,
        same_decision_count=same,
        changed_decision_count=changed,
        changed_to_block=changed_to_block,
        changed_to_allow=changed_to_allow,
        changed_to_size_down=changed_to_size_down,
        realized_outcomes_available=len(realized_outcomes),
        rejected_outcomes_available=len(rejected_outcomes),
        evaluated_rows_with_joined_outcome=evaluated_rows_with_joined_outcome,
        approved_fewer=approved_fewer,
        approved_more=approved_more,
        avoided_losers=avoided_losers,
        missed_winners=missed_winners,
        recovered_missed_winners=recovered_missed_winners,
        introduced_losers=introduced_losers,
        hard_gate_reject_changes=hard_gate_reject_changes,
        policy_relevant_reject_changes=policy_relevant_reject_changes,
        changed_rows_with_outcomes=changed_rows_with_outcomes,
        net_simulated_delta_pct=round(net_simulated_delta_pct, 6),
        gross_simulated_delta_pct=round(gross_simulated_delta_pct, 6),
        friction_bps_per_changed_trade=friction_bps,
        friction_assumptions={
            "round_trip_friction_bps": friction_bps,
            "round_trip_friction_pct_points": round(friction_bps / 100.0, 6),
            "components_required_for_promotion": FRICTION_ASSUMPTIONS,
            "note": "Applied only to changed decisions with joined outcomes.",
        },
        worst_changed_decision=worst_changed_decision,
        best_changed_decision=best_changed_decision,
        changed_rows=changed_rows,
        pit_archive_coverage={
            "per_date": pit_archive_coverage,
            "covered_dates": [d for d, v in pit_archive_coverage.items() if v],
            "missing_dates": [d for d, v in pit_archive_coverage.items() if not v],
            "strategy_memory_source_counts": {
                "archived": pit_rows_with_archived_memory,
                "live_fallback": pit_rows_using_live_fallback,
            },
        },
        pit_rows_with_archived_memory=pit_rows_with_archived_memory,
        pit_rows_using_live_fallback=pit_rows_using_live_fallback,
    )
    return result.to_dict()
