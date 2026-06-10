"""Operator check proving learning artifacts are produced and consumed."""

from __future__ import annotations

import json
from pathlib import Path

from policy_artifacts import policy_artifact_status

from repositories import auto_buy_repo


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text())
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def run_learning_artifact_consumption(
    target_date: str,
    *,
    base_dir: Path,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Learning Artifact Consumption - {target_date}")
    print("=" * 72)
    print("report_version          : learning_artifact_consumption_v1")
    print("runtime_effect          : diagnostic_only_no_live_authority")

    status = policy_artifact_status(base_dir)
    artifacts = status.get("files") or {}
    strategy = _load_json(base_dir / "strategy_memory.json")
    db_path = base_dir / "trades.db"
    auto_buy_rows = []
    if db_path.exists():
        auto_buy_rows = [
            dict(row)
            for row in auto_buy_repo.decision_snapshot_rows_between(
                target_date,
                target_date,
                db_path=db_path,
            )
        ]

    consumed_rows = sum(
        1 for row in auto_buy_rows if "strategy_memory:" in str(row.get("reason") or "")
    )
    constrained_rows = sum(
        1
        for row in auto_buy_rows
        if "strategy_memory_caution" in str(row.get("reason") or "")
        or "strategy_memory_avoid" in str(row.get("hard_block_reason") or "")
    )
    learned_tiebreaker_rows = 0
    for row in auto_buy_rows:
        try:
            payload = json.loads(str(row.get("candidate_json") or "{}"))
        except Exception:
            payload = {}
        candidate = (
            payload.get("candidate") if isinstance(payload.get("candidate"), dict) else payload
        )
        if isinstance(candidate, dict) and candidate.get("learned_tiebreaker_applied"):
            learned_tiebreaker_rows += 1

    print(f"policy_artifacts_enabled: {status.get('enabled')}")
    print(f"policy_artifact_effect  : {status.get('runtime_effect')}")
    registry = status.get("registry") or {}
    print(f"known_good              : {(registry.get('known_good') or {}).get('artifact_set_id')}")
    print(f"state_hash              : {status.get('state_hash')}")
    print(f"strategy_generated_at   : {strategy.get('generated_at')}")
    print(f"strategy_trade_count    : {strategy.get('trade_count')}")
    print(f"auto_buy_rows           : {len(auto_buy_rows)}")
    print(f"strategy_consumed_rows  : {consumed_rows}")
    print(f"strategy_constrained_rows: {constrained_rows}")
    print(f"learned_tiebreaker_rows : {learned_tiebreaker_rows}")
    print()
    print("Artifacts")
    for name in sorted(artifacts):
        item = artifacts.get(name) or {}
        print(
            f"  {name:<36} exists={item.get('exists')} "
            f"generated_at={item.get('generated_at') or '-'} "
            f"sha={str(item.get('sha256') or '-')[:12]}"
        )

    ok = bool(status.get("enabled")) and bool(strategy) and consumed_rows > 0
    if ok:
        print()
        print("[OK] learning artifacts are registered and consumed by auto-buy")
        return True

    print()
    print("[WARN] learning artifact production/consumption has gaps")
    return False
