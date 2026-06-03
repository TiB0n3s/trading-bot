"""Operator report for candidate-universe capture coverage."""

from __future__ import annotations

from pathlib import Path
import json

from repositories.candidate_universe_repo import CandidateUniverseRepository
from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from services.candidate_universe_service import CANDIDATE_UNIVERSE_CONTRACT_VERSION
from services.lifecycle_analysis_service import LifecycleAnalysisService


def _float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _load_json(raw) -> dict:
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _nested(payload: dict, key: str):
    if payload.get(key) not in (None, ""):
        return payload.get(key)
    candidate = payload.get("candidate")
    if isinstance(candidate, dict):
        return candidate.get(key)
    return None


def run_candidate_universe_report(
    target_date: str,
    *,
    base_dir: Path,
    symbol: str | None = None,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Candidate Universe Capture — {target_date}")
    print("=" * 72)
    print(f"contract_version       : {CANDIDATE_UNIVERSE_CONTRACT_VERSION}")
    print("runtime_effect         : candidate_capture_only_no_live_authority")

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    repo = CandidateUniverseRepository(db_path)
    rows = [dict(row) for row in repo.rows_for_date(target_date, symbol=symbol)]
    if symbol:
        print(f"symbol                 : {symbol.upper()}")
    print(f"rows                   : {len(rows)}")

    if not rows:
        print("[WARN] no candidate-universe rows found")
        return False

    by_kind_status: dict[tuple[str, str], int] = {}
    near_threshold = 0
    exit_not_taken = 0
    skipped = 0
    scored = 0
    reference_price_rows = 0
    bid_ask_rows = 0
    spread_rows = 0
    fallback_reference_rows = 0
    for row in rows:
        key = (row.get("candidate_kind") or "unknown", row.get("candidate_status") or "unknown")
        by_kind_status[key] = by_kind_status.get(key, 0) + 1
        if row.get("candidate_status") == "near_threshold":
            near_threshold += 1
        if row.get("candidate_status") == "exit_considered_not_taken":
            exit_not_taken += 1
        if row.get("candidate_status") == "scored_not_taken":
            skipped += 1
        if row.get("score") is not None:
            scored += 1
        payload = _load_json(row.get("candidate_json"))
        if _nested(payload, "reference_price") is not None:
            reference_price_rows += 1
        if _nested(payload, "bid") is not None and _nested(payload, "ask") is not None:
            bid_ask_rows += 1
        if _nested(payload, "spread_pct") is not None:
            spread_rows += 1
        if payload.get("forward_reference_price_source") == "first_bar_close_at_or_after_candidate_ts":
            fallback_reference_rows += 1

    lifecycle = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
    lifecycle_rows = lifecycle.payload(start_date=target_date, symbol=symbol).rows
    by_hash = {
        row.get("entry_canonical_intelligence_hash"): row
        for row in lifecycle_rows
        if row.get("entry_canonical_intelligence_hash")
    }
    by_pattern_status: dict[tuple[str, str], int] = {}
    proven_good = 0
    proven_bad = 0
    top_missed = []
    for row in rows:
        matched = by_hash.get(row.get("canonical_intelligence_hash"))
        payload = _load_json(row.get("candidate_json"))
        candidate_payload = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
        pattern = (
            (matched or {}).get("symbol_pattern")
            or candidate_payload.get("symbol_pattern")
            or payload.get("symbol_pattern")
            or "unknown"
        )
        status = row.get("candidate_status") or "unknown"
        key = (str(pattern), str(status))
        by_pattern_status[key] = by_pattern_status.get(key, 0) + 1
        if not matched:
            mfe = _float(payload.get("forward_mfe_pct") or payload.get("max_favorable_60m"))
            ret = _float(payload.get("forward_return_pct") or payload.get("return_60m"))
        elif matched.get("approved"):
            mfe = _float(matched.get("mfe_pct"))
            ret = _float(matched.get("realized_return_pct"))
        else:
            mfe = _float(matched.get("rejected_max_favorable_60m"))
            ret = _float(matched.get("rejected_return_60m"))
        if ret is not None:
            if ret > 0:
                proven_good += 1
            else:
                proven_bad += 1
        if row.get("candidate_status") != "taken" and mfe is not None and mfe > 0:
            top_missed.append({
                "candidate_ts": row.get("candidate_ts"),
                "symbol": row.get("symbol"),
                "candidate_status": row.get("candidate_status"),
                "score": row.get("score"),
                "threshold_distance": row.get("threshold_distance"),
                "pattern": pattern,
                "mfe": mfe,
                "return": ret,
                "reason": row.get("reason"),
            })
    top_missed.sort(key=lambda item: (-float(item.get("mfe") or 0.0), str(item.get("candidate_ts") or "")))

    print(f"scored                 : {scored}")
    print(f"near_threshold         : {near_threshold}")
    print(f"scored_not_taken       : {skipped}")
    print(f"exit_considered_not_taken: {exit_not_taken}")
    print(f"candidates_proven_good : {proven_good}")
    print(f"candidates_proven_bad  : {proven_bad}")
    print(f"reference_price_rows   : {reference_price_rows}")
    print(f"bid_ask_rows           : {bid_ask_rows}")
    print(f"spread_rows            : {spread_rows}")
    print(f"fallback_reference_rows: {fallback_reference_rows}")
    print()
    print("By kind/status")
    for (kind, status), count in sorted(by_kind_status.items()):
        print(f"  {kind:<8} {status:<28} {count:>6}")

    if by_pattern_status:
        print()
        print("By symbol pattern/status")
        for (pattern, status), count in sorted(
            by_pattern_status.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )[:20]:
            print(f"  {pattern[:38]:<38} {status:<28} {count:>6}")

    if top_missed:
        print()
        print("Top non-taken candidates by forward MFE")
        print(
            f"  {'time':<19} {'sym':<6} {'status':<24} {'pattern':<28} "
            f"{'score':>8} {'mfe':>8} {'ret':>8} reason"
        )
        for item in top_missed[:15]:
            print(
                f"  {str(item['candidate_ts'] or '-')[:19]:<19} "
                f"{str(item['symbol'] or '-'):<6} "
                f"{str(item['candidate_status'] or '-'):<24} "
                f"{str(item.get('pattern') or '-')[:28]:<28} "
                f"{str(item['score'] if item['score'] is not None else '-'):>8} "
                f"{item['mfe']:>8.4f} "
                f"{str(item['return'] if item['return'] is not None else '-'):>8} "
                f"{item.get('reason') or '-'}"
            )

    print()
    print("[OK] candidate-universe capture is queryable")
    return True
