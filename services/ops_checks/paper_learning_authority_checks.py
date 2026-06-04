"""Paper learning authority outcome audit."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from repositories.ops_check_repo import OpsCheckRepository
from services.lifecycle_analysis_service import LifecycleAnalysisService


PAPER_LEARNING_AUTHORITY_REPORT_VERSION = "paper_learning_authority_v1"


def _load_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _paper_authority_outcome(row: dict[str, Any]) -> dict[str, Any]:
    canonical = _load_json(row.get("canonical_intelligence_json"))
    authority = canonical.get("advisory_authority_state")
    if isinstance(authority, dict):
        outcome = authority.get("paper_learning_authority_outcome")
        if isinstance(outcome, dict) and outcome:
            return outcome

    account_state = _load_json(row.get("account_state_json"))
    outcome = account_state.get("paper_learning_authority_override")
    return outcome if isinstance(outcome, dict) else {}


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _fmt_num(value: Any, *, digits: int = 3) -> str:
    number = _num(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}"


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def run_paper_learning_authority_report(target_date: str, *, base_dir: Path) -> bool:
    print()
    print("=" * 72)
    print(f"  Paper Learning Authority Report - {target_date}")
    print("=" * 72)
    print(f"report_version          : {PAPER_LEARNING_AUTHORITY_REPORT_VERSION}")
    print("runtime_effect          : paper_only_diagnostic")

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    repo = OpsCheckRepository(db_path)
    rows = [dict(row) for row in repo.decision_authority_rows(target_date)]
    if not rows:
        print("[WARN] no decision snapshot rows found")
        return False

    lifecycle_payload = LifecycleAnalysisService(
        LifecycleAnalysisRepository(db_path)
    ).payload(start_date=target_date, end_date=target_date)
    lifecycle_by_snapshot = {
        row.get("decision_snapshot_id"): row for row in lifecycle_payload.rows
    }

    counts = Counter()
    setup_scores: list[float] = []
    buy_scores: list[float] = []
    realized_pnl_values: list[float] = []
    realized_pnl_pct_values: list[float] = []
    mfe_values: list[float] = []
    counterfactual_values: list[float] = []
    examples: list[dict[str, Any]] = []

    for row in rows:
        action = str(row.get("action") or "").lower()
        approved = bool(row.get("approved"))
        counts["decision_rows"] += 1
        if action == "buy":
            counts["buy_rows"] += 1

        outcome = _paper_authority_outcome(row)
        if not outcome:
            continue

        allowed = bool(outcome.get("allowed"))
        counts["paper_authority_rows"] += 1
        if action == "buy":
            counts["paper_authority_buy_rows"] += 1
        if allowed:
            counts["allowed_overrides"] += 1
        else:
            counts["blocked_by_paper_authority_checks"] += 1
        if approved:
            counts["approved_after_override"] += 1
        else:
            counts["still_rejected_after_marker"] += 1

        setup_score = _num(outcome.get("setup_score"))
        buy_score = _num(outcome.get("buy_opportunity_score"))
        if setup_score is not None:
            setup_scores.append(setup_score)
        if buy_score is not None:
            buy_scores.append(buy_score)

        lifecycle = lifecycle_by_snapshot.get(row.get("id")) or {}
        lifecycle_status = lifecycle.get("lifecycle_status")
        if lifecycle_status:
            counts[f"lifecycle_{lifecycle_status}"] += 1
        else:
            counts["lifecycle_unlinked"] += 1

        realized_pnl = _num(lifecycle.get("realized_pnl"))
        realized_pnl_pct = _num(lifecycle.get("realized_pnl_pct"))
        mfe_pct = _num(lifecycle.get("mfe_pct"))
        rejected_return_60m = _num(lifecycle.get("rejected_return_60m"))
        if realized_pnl is not None:
            realized_pnl_values.append(realized_pnl)
        if realized_pnl_pct is not None:
            realized_pnl_pct_values.append(realized_pnl_pct)
        if mfe_pct is not None:
            mfe_values.append(mfe_pct)
        if rejected_return_60m is not None:
            counterfactual_values.append(rejected_return_60m)

        if len(examples) < 20:
            examples.append(
                {
                    "time": row.get("decision_time"),
                    "symbol": row.get("symbol"),
                    "approved": approved,
                    "setup_score": setup_score,
                    "buy_score": buy_score,
                    "lifecycle_status": lifecycle_status or "unlinked",
                    "realized_pnl_pct": realized_pnl_pct,
                    "mfe_pct": mfe_pct,
                    "reason": outcome.get("reason"),
                }
            )

    print()
    print("Coverage")
    for key in (
        "decision_rows",
        "buy_rows",
        "paper_authority_rows",
        "paper_authority_buy_rows",
        "allowed_overrides",
        "blocked_by_paper_authority_checks",
        "approved_after_override",
        "still_rejected_after_marker",
        "lifecycle_unlinked",
    ):
        print(f"  {key:<38} {counts[key]:5d}")

    print()
    print("Lifecycle evidence")
    for key in sorted(k for k in counts if k.startswith("lifecycle_") and k != "lifecycle_unlinked"):
        print(f"  {key:<38} {counts[key]:5d}")

    print()
    print("Outcome metrics")
    print(f"  avg_setup_score                       {_fmt_num(_avg(setup_scores))}")
    print(f"  avg_buy_opportunity_score             {_fmt_num(_avg(buy_scores))}")
    print(f"  avg_realized_pnl                      {_fmt_num(_avg(realized_pnl_values), digits=2)}")
    print(f"  avg_realized_pnl_pct                  {_fmt_num(_avg(realized_pnl_pct_values))}")
    print(f"  avg_mfe_pct                           {_fmt_num(_avg(mfe_values))}")
    print(f"  avg_rejected_return_60m               {_fmt_num(_avg(counterfactual_values))}")

    if examples:
        print()
        print("Recent paper-authority rows")
        for item in examples:
            print(
                f"  {str(item['time'])[:19]:<19} "
                f"{str(item['symbol'] or '-'):<6} "
                f"approved={str(item['approved']):<5} "
                f"setup={_fmt_num(item['setup_score']):>7} "
                f"buy_opp={_fmt_num(item['buy_score']):>7} "
                f"status={str(item['lifecycle_status']):<38} "
                f"pnl_pct={_fmt_num(item['realized_pnl_pct']):>8} "
                f"mfe={_fmt_num(item['mfe_pct']):>8}"
            )

    if counts["paper_authority_rows"] == 0:
        print()
        print("[INFO] no paper learning authority rows found")
        print("[OK] paper learning authority report completed")
        return True

    print()
    print("[OK] paper learning authority report completed")
    return True
