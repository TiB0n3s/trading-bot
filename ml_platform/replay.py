"""Shadow replay for policy comparison.

replay_decisions_v1 reads decision_snapshots from the DB, re-runs
evaluate_decision_policy with the stored account_state, and reports where
the replayed policy differs from what was recorded.

This is read-only and observe-only. It does not change orders, risk controls,
broker behavior, or any live trading state.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from db import DB_PATH
from ml_platform.governance import BASELINE_POLICIES, FRICTION_ASSUMPTIONS


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
    changed: bool

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
    changed_rows: list[dict[str, Any]] = field(default_factory=list)
    note: str = (
        "Read-only replay. No orders, risk controls, or live decisions were changed. "
        "The replayed policy uses evaluate_decision_policy with stored account_state_json."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_snapshots(
    start_date: str,
    end_date: str,
    db_path: Path | str,
) -> list[sqlite3.Row]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "decision_snapshots" not in tables:
            return []
        return con.execute(
            """
            SELECT id, symbol, action, decision_time, final_decision, approved,
                   account_state_json
            FROM decision_snapshots
            WHERE action = 'buy'
              AND substr(decision_time, 1, 10) BETWEEN ? AND ?
            ORDER BY decision_time, id
            """,
            (start_date, end_date),
        ).fetchall()


def replay_decisions_v1(
    *,
    start_date: str,
    end_date: str,
    policy: str = "current",
    db_path: Path | str = DB_PATH,
    max_changed_rows: int = 50,
) -> dict[str, Any]:
    """Re-run evaluate_decision_policy against stored decision_snapshots.

    Read-only. Does not affect orders, risk gates, or broker state.
    """
    from decision_policy import evaluate_decision_policy

    rows = _load_snapshots(start_date, end_date, db_path)

    same = 0
    changed = 0
    changed_to_block = 0
    changed_to_allow = 0
    changed_to_size_down = 0
    skipped = 0
    changed_rows: list[dict[str, Any]] = []

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

        try:
            replayed = evaluate_decision_policy(
                symbol=symbol,
                action="buy",
                intelligence_context=intelligence_context,
                account_state=account_state,
            )
        except Exception:
            skipped += 1
            continue

        replayed_decision = replayed.get("decision")
        replay_row = ReplayRow(
            snapshot_id=int(row["id"]),
            symbol=symbol,
            action="buy",
            decision_time=row["decision_time"] or "",
            stored_policy_decision=stored_decision,
            stored_policy_reason=stored_dp.get("reason"),
            replayed_policy_decision=replayed_decision,
            replayed_policy_reason=replayed.get("reason"),
            replayed_policy_size_multiplier=replayed.get("size_multiplier"),
            final_decision=row["final_decision"],
            approved=bool(row["approved"]),
            changed=(stored_decision != replayed_decision),
        )

        if replay_row.changed:
            changed += 1
            if replayed_decision == "block":
                changed_to_block += 1
            elif replayed_decision == "allow":
                changed_to_allow += 1
            elif replayed_decision == "size_down":
                changed_to_size_down += 1
            if len(changed_rows) < max_changed_rows:
                changed_rows.append(replay_row.to_dict())
        else:
            same += 1

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
        changed_rows=changed_rows,
    )
    return result.to_dict()
