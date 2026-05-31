"""Advisory-vs-authority decision audit."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from repositories.ops_check_repo import OpsCheckRepository


def _load_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _is_approved(row: dict[str, Any]) -> bool:
    return bool(row.get("approved"))


def _increment_if(counter: Counter, key: str, condition: bool) -> None:
    if condition:
        counter[key] += 1


def run_advisory_authority_report(target_date: str, *, base_dir: Path) -> bool:
    print()
    print("=" * 72)
    print(f"  Advisory vs Authority Report - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    repo = OpsCheckRepository(db_path)
    rows = [dict(row) for row in repo.decision_authority_rows(target_date)]
    if not rows:
        print("[WARN] no decision snapshot rows found")
        return False

    counts = Counter()
    mode_counts = Counter()
    examples: list[dict[str, Any]] = []

    for row in rows:
        account_state = _load_json(row.get("account_state_json"))
        approved = _is_approved(row)
        action = (row.get("action") or "").lower()
        counts["rows"] += 1
        _increment_if(counts, "buy_rows", action == "buy")
        _increment_if(counts, "approved_rows", approved)

        authority = account_state.get("decision_policy_authority") or {}
        mode = authority.get("authority_mode") or "unknown"
        mode_counts[mode] += 1

        decision_policy = account_state.get("decision_policy") or {}
        decision_policy_decision = decision_policy.get("decision")
        dp_block = action == "buy" and decision_policy_decision == "block"
        dp_size_down = action == "buy" and decision_policy_decision == "size_down"
        dp_size_down_applied = bool(account_state.get("decision_policy_size_down"))

        prediction_gate = account_state.get("prediction_gate") or {}
        ml_runtime_effect = prediction_gate.get("ml_prediction_runtime_effect")
        ml_compare = prediction_gate.get("ml_prediction_compare_decision")
        ml_negative = (
            action == "buy"
            and ml_runtime_effect == "observe_only_compare"
            and ml_compare in ("avoid", "block", "watch", "caution")
        )

        session_gate = account_state.get("session_momentum_gate") or {}
        session_would_block = action == "buy" and bool(session_gate.get("would_block"))

        setup_quality = account_state.get("setup_quality") or {}
        setup_score = setup_quality.get("score")
        setup_recommendation = setup_quality.get("recommendation")
        weak_setup = (
            action == "buy"
            and (
                setup_recommendation == "avoid"
                or (isinstance(setup_score, (int, float)) and setup_score < 40)
            )
        )

        _increment_if(counts, "decision_policy_block_advisory", dp_block)
        _increment_if(counts, "decision_policy_block_but_approved", dp_block and approved)
        _increment_if(counts, "decision_policy_size_down_advisory", dp_size_down)
        _increment_if(
            counts,
            "decision_policy_size_down_not_applied",
            dp_size_down and not dp_size_down_applied,
        )
        _increment_if(counts, "ml_negative_compare_advisory", ml_negative)
        _increment_if(counts, "ml_negative_compare_but_approved", ml_negative and approved)
        _increment_if(counts, "session_would_block_advisory", session_would_block)
        _increment_if(counts, "session_would_block_but_approved", session_would_block and approved)
        _increment_if(counts, "weak_setup_quality_advisory", weak_setup)
        _increment_if(counts, "weak_setup_quality_but_approved", weak_setup and approved)

        if approved and (dp_block or ml_negative or session_would_block or weak_setup):
            examples.append(
                {
                    "time": row.get("decision_time"),
                    "symbol": row.get("symbol"),
                    "action": row.get("action"),
                    "signals": ",".join(
                        label
                        for label, condition in (
                            ("decision_policy_block", dp_block),
                            ("ml_negative_compare", ml_negative),
                            ("session_would_block", session_would_block),
                            ("weak_setup_quality", weak_setup),
                        )
                        if condition
                    ),
                }
            )

    print(f"rows                         : {counts['rows']}")
    print(f"buy_rows                     : {counts['buy_rows']}")
    print(f"approved_rows                : {counts['approved_rows']}")
    print()
    print("Authority modes")
    for mode, n in sorted(mode_counts.items()):
        print(f"  {mode:<32} {n:5d}")

    print()
    print("Advisory disagreement counts")
    for key in (
        "decision_policy_block_advisory",
        "decision_policy_block_but_approved",
        "decision_policy_size_down_advisory",
        "decision_policy_size_down_not_applied",
        "ml_negative_compare_advisory",
        "ml_negative_compare_but_approved",
        "session_would_block_advisory",
        "session_would_block_but_approved",
        "weak_setup_quality_advisory",
        "weak_setup_quality_but_approved",
    ):
        print(f"  {key:<42} {counts[key]:5d}")

    if examples:
        print()
        print("Approved rows with advisory-negative signals")
        for item in examples[:20]:
            print(
                f"  {str(item['time'])[:19]:<19} "
                f"{str(item['symbol'] or '-'):<6} "
                f"{str(item['action'] or '-'):<4} "
                f"{item['signals']}"
            )

    print()
    print("[OK] advisory authority report completed")
    return True
