"""Operator report for strategy-memory hard-block attribution."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from repositories import auto_buy_repo

REPORT_VERSION = "strategy_memory_hard_block_review_v1"
SPREAD_GUARD_MAX_PCT = 2.0


def _load_json(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _candidate(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("candidate")
    return nested if isinstance(nested, dict) else {}


def _first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _fmt_pct(value: Any) -> str:
    number = _float(value)
    return "-" if number is None else f"{number:.3f}%"


def _short(text: Any, width: int) -> str:
    value = str(text or "-")
    return value if len(value) <= width else value[: max(0, width - 1)] + "…"


def _primary_hard_block(reason: str | None) -> str:
    text = str(reason or "").strip()
    if not text:
        return "none"
    first = text.split(";", 1)[0]
    return first.split(":", 1)[0].strip() or "unknown"


def _strategy_memory_summary(reason_text: str) -> dict[str, Any]:
    match = re.search(
        r"strategy_memory:(?P<rec>[^:;]+):min_setup=(?P<min>[^:;]+):trades=(?P<trades>[^;]+)",
        reason_text,
    )
    if not match:
        return {
            "present": False,
            "recommendation": None,
            "min_setup_score": None,
            "trades": None,
        }
    return {
        "present": True,
        "recommendation": match.group("rec"),
        "min_setup_score": _float(match.group("min")),
        "trades": _float(match.group("trades")),
    }


def _bar_pattern_summary(reason_text: str) -> dict[str, Any]:
    match = re.search(
        r"bar_pattern_memory:(?P<rec>[^:;]+):(?P<label>[^:;]+):(?P<key>[^;]+)",
        reason_text,
    )
    if not match:
        return {
            "present": False,
            "recommendation": None,
            "label": None,
            "key": None,
        }
    return {
        "present": True,
        "recommendation": match.group("rec"),
        "label": match.group("label"),
        "key": match.group("key"),
    }


def _spread_cost_pct(payload: dict[str, Any]) -> float | None:
    cand = _candidate(payload)
    bid = _float(_first_value(cand.get("bid"), payload.get("bid")))
    ask = _float(_first_value(cand.get("ask"), payload.get("ask")))
    reference = _float(
        _first_value(
            payload.get("forward_reference_price"),
            payload.get("reference_price"),
            cand.get("reference_price"),
            cand.get("mid"),
            cand.get("current_price"),
            cand.get("price"),
        )
    )
    if bid is None or ask is None or reference is None or reference <= 0 or ask < bid:
        return None
    return round((ask - bid) / reference * 100.0, 4)


def _guarded_spread_cost_pct(spread_cost: float | None) -> float | None:
    if spread_cost is None or spread_cost < 0 or spread_cost > SPREAD_GUARD_MAX_PCT:
        return None
    return spread_cost


def _slippage_artifact_status(base_dir: Path) -> dict[str, Any]:
    artifact = base_dir / "ops" / "model_promotion_evidence" / "cost_slippage_exit_analysis.json"
    payload: dict[str, Any] = {}
    if artifact.exists():
        try:
            loaded = json.loads(artifact.read_text(encoding="utf-8"))
            payload = loaded if isinstance(loaded, dict) else {}
        except Exception:
            payload = {}
    return {
        "artifact_path": str(artifact),
        "artifact_exists": artifact.exists(),
        "artifact_ready": payload.get("ready") is True,
        "source": payload.get("source"),
        "per_symbol_model_available": False,
    }


def build_strategy_memory_hard_block_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = _load_json(row.get("candidate_json"))
        cand = _candidate(payload)
        hard_block_reason = str(
            _first_value(
                cand.get("hard_block_reason"),
                payload.get("hard_block_reason"),
                row.get("hard_block_reason"),
            )
            or ""
        )
        primary = _primary_hard_block(hard_block_reason)
        if not primary.startswith("strategy_memory_avoid"):
            continue

        reason_text = str(
            _first_value(cand.get("reason"), payload.get("reason"), row.get("reason")) or ""
        )
        memory = _strategy_memory_summary(reason_text)
        pattern = _bar_pattern_summary(reason_text)
        return_60m = _float(payload.get("return_60m"))
        max_favorable_60m = _float(
            payload.get("max_favorable_60m") or payload.get("forward_mfe_pct")
        )
        max_adverse_60m = _float(payload.get("max_adverse_60m") or payload.get("forward_mae_pct"))
        return_eod = _float(payload.get("return_eod"))
        spread_cost = _spread_cost_pct(payload)
        guarded_spread_cost = _guarded_spread_cost_pct(spread_cost)
        net_60m = (
            round(return_60m - guarded_spread_cost, 4)
            if return_60m is not None and guarded_spread_cost is not None
            else None
        )

        out.append(
            {
                "candidate_ts": row.get("candidate_ts"),
                "symbol": row.get("symbol"),
                "score": _float(row.get("score")),
                "setup_label": row.get("setup_label"),
                "decision": row.get("decision"),
                "primary_blocker": primary,
                "weak_evidence": primary == "strategy_memory_avoid_weak_evidence",
                "memory_recommendation": memory.get("recommendation"),
                "memory_min_setup_score": memory.get("min_setup_score"),
                "memory_trades": memory.get("trades"),
                "bar_pattern_recommendation": pattern.get("recommendation"),
                "bar_pattern_label": pattern.get("label"),
                "bar_pattern_key": pattern.get("key"),
                "return_60m": return_60m,
                "return_eod": return_eod,
                "max_favorable_60m": max_favorable_60m,
                "max_adverse_60m": max_adverse_60m,
                "spread_cost_pct": spread_cost,
                "spread_cost_guarded_pct": guarded_spread_cost,
                "spread_guarded_out": spread_cost is not None and guarded_spread_cost is None,
                "net_return_60m_after_spread": net_60m,
                "label_status": payload.get("label_status"),
                "partial_reason": payload.get("partial_reason"),
                "has_forward_outcome": any(
                    value is not None
                    for value in (return_60m, return_eod, max_favorable_60m, max_adverse_60m)
                ),
                "hard_block_reason": hard_block_reason,
            }
        )
    return out


def _print_group_summary(review_rows: list[dict[str, Any]]) -> None:
    groups: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "rows": 0,
            "with_outcome": 0,
            "score_sum": 0.0,
            "score_count": 0,
            "return_60m_values": [],
            "net_60m_values": [],
            "spread_guarded_out": 0,
        }
    )
    for row in review_rows:
        key = (
            str(row.get("primary_blocker") or "unknown"),
            str(row.get("bar_pattern_label") or "no_bar_pattern"),
            str(row.get("bar_pattern_key") or "no_key"),
        )
        group = groups[key]
        group["rows"] += 1
        if row.get("has_forward_outcome"):
            group["with_outcome"] += 1
        score = _float(row.get("score"))
        if score is not None:
            group["score_sum"] += score
            group["score_count"] += 1
        if row.get("return_60m") is not None:
            group["return_60m_values"].append(float(row["return_60m"]))
        if row.get("net_return_60m_after_spread") is not None:
            group["net_60m_values"].append(float(row["net_return_60m_after_spread"]))
        if row.get("spread_guarded_out"):
            group["spread_guarded_out"] += 1

    print()
    print("By blocker/component")
    print(
        "  blocker                            bar_pattern                  key                         rows smp avgScore smp60 smpNet sprGuard"
    )
    for (blocker, label, key), group in sorted(
        groups.items(), key=lambda item: (-item[1]["rows"], item[0])
    ):
        avg_score = group["score_sum"] / group["score_count"] if group["score_count"] else None
        returns = group["return_60m_values"]
        nets = group["net_60m_values"]
        avg_return = sum(returns) / len(returns) if returns else None
        avg_net = sum(nets) / len(nets) if nets else None
        avg_score_s = f"{avg_score:.2f}" if avg_score is not None else "-"
        print(
            f"  {_short(blocker, 34):<34} "
            f"{_short(label, 28):<28} "
            f"{_short(key, 27):<27} "
            f"{group['rows']:>4} {group['with_outcome']:>3} "
            f"{avg_score_s:>8} "
            f"{_fmt_pct(avg_return):>7} {_fmt_pct(avg_net):>7} "
            f"{group['spread_guarded_out']:>8}"
        )


def _print_top_rows(review_rows: list[dict[str, Any]], samples: int) -> None:
    print()
    print("Top strategy-memory hard blocks")
    print(
        "  time                sym    score blocker                         component                    ret60    mfe60    mae60 spread net60 status"
    )
    ranked = sorted(
        review_rows,
        key=lambda row: (
            float(row.get("score") if row.get("score") is not None else -9999),
            str(row.get("candidate_ts") or ""),
        ),
        reverse=True,
    )
    for row in ranked[:samples]:
        component = row.get("bar_pattern_label") or "symbol/context"
        status = row.get("label_status") or row.get("partial_reason") or "-"
        print(
            f"  {str(row.get('candidate_ts') or '-')[:19]:<19} "
            f"{str(row.get('symbol') or '-'):<6} "
            f"{row.get('score') if row.get('score') is not None else '-':>5} "
            f"{_short(row.get('primary_blocker'), 31):<31} "
            f"{_short(component, 28):<28} "
            f"{_fmt_pct(row.get('return_60m')):>7} "
            f"{_fmt_pct(row.get('max_favorable_60m')):>7} "
            f"{_fmt_pct(row.get('max_adverse_60m')):>7} "
            f"{_fmt_pct(row.get('spread_cost_guarded_pct')):>6} "
            f"{_fmt_pct(row.get('net_return_60m_after_spread')):>7} "
            f"{_short(status, 18)}"
        )


def _print_probe_candidates(review_rows: list[dict[str, Any]], samples: int) -> None:
    weak_rows = [row for row in review_rows if row.get("weak_evidence")]
    if not weak_rows:
        return

    print()
    print("Weak-evidence probe candidates")
    print("  time                sym    score trades reason/status          mfe60    mae60")
    for row in weak_rows[:samples]:
        status = row.get("partial_reason") or row.get("label_status") or "-"
        print(
            f"  {str(row.get('candidate_ts') or '-')[:19]:<19} "
            f"{str(row.get('symbol') or '-'):<6} "
            f"{row.get('score') if row.get('score') is not None else '-':>5} "
            f"{row.get('memory_trades') if row.get('memory_trades') is not None else '-':>6} "
            f"{_short(status, 22):<22} "
            f"{_fmt_pct(row.get('max_favorable_60m')):>7} "
            f"{_fmt_pct(row.get('max_adverse_60m')):>7}"
        )


def _print_coverage_summary(
    *,
    review_rows: list[dict[str, Any]],
    enriched_rows: list[dict[str, Any]],
    sample_keys: set[tuple[str, str]],
    full_day: bool,
) -> None:
    scoped_rows = (
        review_rows
        if full_day
        else [
            row
            for row in review_rows
            if (str(row.get("symbol")), str(row.get("candidate_ts"))) in sample_keys
        ]
    )
    with_outcome = sum(1 for row in scoped_rows if row.get("has_forward_outcome"))
    missing = len(scoped_rows) - with_outcome
    spread_rows = sum(1 for row in scoped_rows if row.get("spread_cost_pct") is not None)
    spread_guarded = sum(1 for row in scoped_rows if row.get("spread_guarded_out"))
    missing_join = sum(1 for row in enriched_rows if not row.get("candidate_json"))
    label = "full_day" if full_day else "sample"
    print(f"{label}_rows_enriched : {len(scoped_rows)}")
    print(f"{label}_with_outcome  : {with_outcome}")
    print(f"{label}_missing_outcome: {missing}")
    print(f"{label}_spread_rows   : {spread_rows}")
    print(f"{label}_spread_guarded: {spread_guarded}")
    print(f"{label}_missing_join  : {missing_join}")


def _print_slippage_status(base_dir: Path) -> None:
    status = _slippage_artifact_status(base_dir)
    print()
    print("Slippage evidence")
    print(f"  cost_slippage_artifact : {status['artifact_exists']}")
    print(f"  artifact_ready         : {status['artifact_ready']}")
    print(f"  artifact_source        : {status.get('source') or '-'}")
    print(f"  per_symbol_model       : {status['per_symbol_model_available']}")
    if status["artifact_exists"] and not status["per_symbol_model_available"]:
        print("  note                   : existing artifact is evidence, not per-symbol slippage")


def _print_review_guardrails(*, full_day: bool) -> None:
    print()
    print("Review guardrails")
    print("  independent_days       : 1")
    print("  minimum_before_policy  : multiple independent sessions")
    print("  runtime_effect         : analysis_only_no_trade_authority")
    if not full_day:
        print("  next_audit             : rerun with --full-day after outcome backfill")


def run_strategy_memory_hard_blocks(
    target_date: str,
    *,
    base_dir: Path,
    symbol: str | None = None,
    samples: int = 20,
    full_day: bool = False,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Strategy-Memory Hard Block Review - {target_date}")
    print("=" * 72)
    print(f"report_version       : {REPORT_VERSION}")
    print("runtime_effect       : analysis_only_no_trade_authority")

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    rows = auto_buy_repo.strategy_memory_hard_block_candidate_rows(
        target_date,
        symbol=symbol,
        db_path=db_path,
    )
    initial_review_rows = build_strategy_memory_hard_block_rows(rows)
    top_keys = {
        (str(row.get("symbol")), str(row.get("candidate_ts")))
        for row in sorted(
            initial_review_rows,
            key=lambda item: (
                float(item.get("score") if item.get("score") is not None else -9999),
                str(item.get("candidate_ts") or ""),
            ),
            reverse=True,
        )[:samples]
    }
    weak_keys = [
        (str(row.get("symbol")), str(row.get("candidate_ts")))
        for row in initial_review_rows
        if row.get("weak_evidence")
    ]
    sample_keys = top_keys | set(weak_keys[:samples])
    rows_to_enrich = (
        rows
        if full_day
        else [
            row
            for row in rows
            if (str(row.get("symbol")), str(row.get("candidate_ts"))) in sample_keys
        ]
    )
    auto_buy_repo.enrich_candidate_universe_json(rows_to_enrich, db_path=db_path)
    review_rows = build_strategy_memory_hard_block_rows(rows)
    if symbol:
        print(f"symbol               : {symbol.upper()}")
    print(f"candidate_rows       : {len(rows)}")
    print(f"strategy_memory_rows : {len(review_rows)}")

    if not review_rows:
        print("[WARN] no strategy-memory hard-block rows found")
        return False

    weak = sum(1 for row in review_rows if row.get("weak_evidence"))
    print(f"weak_evidence_rows   : {weak}")
    print(
        "cost_model           : guarded_spread_only_from_captured_bid_ask; "
        f"spread_guard_max_pct={SPREAD_GUARD_MAX_PCT}; slippage_not_applied"
    )
    _print_coverage_summary(
        review_rows=review_rows,
        enriched_rows=rows_to_enrich,
        sample_keys=sample_keys,
        full_day=full_day,
    )

    _print_group_summary(review_rows)
    _print_top_rows(review_rows, samples=samples)
    _print_probe_candidates(review_rows, samples=samples)
    _print_slippage_status(base_dir)
    _print_review_guardrails(full_day=full_day)

    missing = sum(
        1
        for row in review_rows
        if (full_day or (str(row.get("symbol")), str(row.get("candidate_ts"))) in sample_keys)
        and not row.get("has_forward_outcome")
    )
    if missing:
        print()
        print("[WARN] some displayed strategy-memory hard blocks are missing forward outcomes")
        print("       Run: python3 ops_check.py candidate-outcome-backfill " + target_date)

    print()
    print("[OK] strategy-memory hard-block review completed")
    return True
