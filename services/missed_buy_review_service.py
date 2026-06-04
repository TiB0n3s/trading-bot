"""Missed-buy diagnostics from candidate-universe forward outcomes.

This module is intentionally report-only. It turns captured non-taken BUY
candidates into a reviewable learning surface without granting any live
authority to the analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable


MISSED_BUY_REVIEW_VERSION = "missed_buy_review_v1"
MISSED_BUY_REVIEW_RUNTIME_EFFECT = "diagnostic_only_no_live_authority"


@dataclass(frozen=True)
class MissedBuyReviewPayload:
    summary: dict[str, Any]
    top_missed: list[dict[str, Any]]
    reason_token_counts: list[dict[str, Any]]
    symbol_counts: list[dict[str, Any]]
    pattern_counts: list[dict[str, Any]]
    learning_actions: list[str]


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(count / total, 4)


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


def _candidate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload.get("candidate")
    return candidate if isinstance(candidate, dict) else payload


def _first_float(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _float(payload.get(key))
        if value is not None:
            return value
    return None


def _forward_return(payload: dict[str, Any]) -> float | None:
    return _first_float(
        payload,
        (
            "forward_return_pct",
            "return_60m",
            "return_30m",
            "return_eod",
        ),
    )


def _forward_mfe(payload: dict[str, Any]) -> float | None:
    return _first_float(
        payload,
        (
            "forward_mfe_pct",
            "max_favorable_60m",
            "max_favorable_30m",
            "max_favorable_eod",
        ),
    )


def _forward_mae(payload: dict[str, Any]) -> float | None:
    return _first_float(
        payload,
        (
            "forward_mae_pct",
            "max_adverse_60m",
            "max_adverse_30m",
            "max_adverse_eod",
        ),
    )


def _normalize_token(token: str) -> str:
    text = token.strip().lower()
    if not text:
        return ""
    for separator in (":", "(", "["):
        if separator in text:
            text = text.split(separator, 1)[0].strip()
    text = text.replace(" ", "_")
    return text


def _reason_tokens(row: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    raw_parts: list[str] = []
    for key in ("reason", "decision", "hard_block_reason", "live_block_reason"):
        value = row.get(key)
        if value:
            raw_parts.append(str(value))
    for key in ("reason", "decision", "hard_block_reason", "live_block_reason"):
        value = candidate.get(key)
        if value:
            raw_parts.append(str(value))

    tokens: list[str] = []
    for raw in raw_parts:
        for part in raw.replace("|", ";").split(";"):
            token = _normalize_token(part)
            if token:
                tokens.append(token)

    ml_bucket = candidate.get("ml_prediction_bucket")
    if ml_bucket not in (None, "", "unknown"):
        tokens.append(f"ml_prediction_{str(ml_bucket).strip().lower()}")
    setup_label = row.get("setup_label") or candidate.get("setup_label")
    if setup_label not in (None, "", "unknown"):
        tokens.append(f"setup_label_{str(setup_label).strip().lower()}")
    return sorted(set(tokens))


def _pattern(row: dict[str, Any], candidate: dict[str, Any], payload: dict[str, Any]) -> str:
    value = (
        candidate.get("symbol_pattern")
        or payload.get("symbol_pattern")
        or candidate.get("pattern_label")
        or row.get("setup_label")
        or "unknown"
    )
    return str(value)


def _is_taken(row: dict[str, Any]) -> bool:
    status = str(row.get("candidate_status") or "").lower()
    decision = str(row.get("decision") or "").lower()
    return status == "taken" or decision in {"submitted", "approved", "buy"}


def _missed_quality(forward_return: float | None, forward_mfe: float | None) -> str:
    if forward_return is None and forward_mfe is None:
        return "missing_outcome"
    if (forward_mfe is not None and forward_mfe >= 2.0) or (
        forward_return is not None and forward_return >= 1.0
    ):
        return "high_quality_missed"
    if (forward_mfe is not None and forward_mfe >= 0.8) or (
        forward_return is not None and forward_return >= 0.4
    ):
        return "missed_good"
    if forward_return is not None and forward_return <= -0.25:
        return "correctly_avoided_or_bad_candidate"
    return "inconclusive"


def _count_rows(values: Iterable[str]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for value in values:
        key = value or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return [
        {"key": key, "count": count}
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _learning_actions(
    *,
    coverage_rate: float | None,
    reason_counts: list[dict[str, Any]],
    missed_good: int,
    high_quality_missed: int,
) -> list[str]:
    actions: list[str] = []
    if coverage_rate is None or coverage_rate < 0.80:
        actions.append("continue candidate-outcome-backfill until forward-outcome coverage is at least 80%")
    if missed_good <= 0:
        actions.append("no missed-good candidates found in this sample; keep collecting outcomes")
        return actions

    top_reasons = {str(row["key"]): int(row["count"]) for row in reason_counts}
    if top_reasons.get("negative_session_downtrend", 0) >= 3:
        actions.append("review negative_session_downtrend false negatives against symbol-level trend recovery")
    if top_reasons.get("below_vwap", 0) >= 3:
        actions.append("review below_vwap rejection when EFI/PVT or forward MFE shows recovery setups")
    if top_reasons.get("setup_avoid", 0) + top_reasons.get("setup_unclassified_transition", 0) >= 3:
        actions.append("review setup-quality avoid/unclassified labels for missed positive-forward candidates")
    if top_reasons.get("strategy_memory_caution_setup_below_min", 0) >= 3:
        actions.append("review strategy-memory caution thresholds for buckets with positive forward outcome")
    if top_reasons.get("mom_strong_decel", 0) >= 3:
        actions.append("review momentum deceleration penalty when later MFE remains favorable")
    if high_quality_missed > 0:
        actions.append("inspect high_quality_missed rows before relaxing any live gate")
    actions.append("compare missed-buy rows with decision-quality approved rows before tuning thresholds")
    return actions


def build_missed_buy_review_payload(
    candidate_rows: Iterable[dict[str, Any]],
    *,
    min_mfe_pct: float = 0.8,
) -> MissedBuyReviewPayload:
    rows = [dict(row) for row in candidate_rows]
    rows_with_forward = 0
    non_taken_with_forward = 0
    missed_good = 0
    high_quality_missed = 0
    correctly_avoided = 0
    quality_counts: dict[str, int] = {}
    missed_mfe_values: list[float] = []
    missed_return_values: list[float] = []
    soft_block_missed_good = 0
    promotion_review_candidates = 0
    top_missed: list[dict[str, Any]] = []
    reason_tokens: list[str] = []
    symbol_values: list[str] = []
    pattern_values: list[str] = []

    for row in rows:
        payload = _load_json(row.get("candidate_json"))
        candidate = _candidate_payload(payload)
        forward_return = _forward_return(payload)
        forward_mfe = _forward_mfe(payload)
        forward_mae = _forward_mae(payload)
        if forward_return is not None or forward_mfe is not None:
            rows_with_forward += 1
        if _is_taken(row):
            continue
        if forward_return is None and forward_mfe is None:
            continue

        non_taken_with_forward += 1
        quality = _missed_quality(forward_return, forward_mfe)
        quality_counts[quality] = quality_counts.get(quality, 0) + 1
        if quality in {"missed_good", "high_quality_missed"}:
            missed_good += 1
            if forward_mfe is not None:
                missed_mfe_values.append(forward_mfe)
            if forward_return is not None:
                missed_return_values.append(forward_return)
        if quality == "high_quality_missed":
            high_quality_missed += 1
        if quality == "correctly_avoided_or_bad_candidate":
            correctly_avoided += 1

        pattern = _pattern(row, candidate, payload)
        row_reason_tokens = _reason_tokens(row, candidate)
        if quality in {"missed_good", "high_quality_missed"}:
            reason_tokens.extend(row_reason_tokens)
            symbol_values.append(str(row.get("symbol") or "unknown").upper())
            pattern_values.append(pattern)
            if any(
                token.startswith(("setup_avoid", "strategy_memory_caution"))
                for token in row_reason_tokens
            ):
                soft_block_missed_good += 1
            score = _float(row.get("score"))
            threshold = _float(row.get("threshold"))
            if (
                score is not None
                and threshold is not None
                and score >= threshold
                and any(token.startswith("setup_avoid") for token in row_reason_tokens)
            ):
                promotion_review_candidates += 1

        if forward_mfe is not None and forward_mfe >= min_mfe_pct:
            top_missed.append(
                {
                    "candidate_ts": row.get("candidate_ts"),
                    "symbol": str(row.get("symbol") or "").upper(),
                    "candidate_status": row.get("candidate_status"),
                    "score": _float(row.get("score")),
                    "threshold": _float(row.get("threshold")),
                    "threshold_distance": _float(row.get("threshold_distance")),
                    "pattern": pattern,
                    "setup_label": row.get("setup_label") or candidate.get("setup_label"),
                    "ml_prediction_bucket": candidate.get("ml_prediction_bucket"),
                    "forward_mfe_pct": round(forward_mfe, 4),
                    "forward_return_pct": round(forward_return, 4) if forward_return is not None else None,
                    "forward_mae_pct": round(forward_mae, 4) if forward_mae is not None else None,
                    "quality": quality,
                    "reason_tokens": row_reason_tokens,
                    "soft_block_candidate": any(
                        token.startswith(("setup_avoid", "strategy_memory_caution"))
                        for token in row_reason_tokens
                    ),
                    "paper_promotion_review_candidate": bool(
                        quality in {"missed_good", "high_quality_missed"}
                        and _float(row.get("score")) is not None
                        and _float(row.get("threshold")) is not None
                        and (_float(row.get("score")) or 0.0) >= (_float(row.get("threshold")) or 0.0)
                        and any(token.startswith("setup_avoid") for token in row_reason_tokens)
                    ),
                    "reason": row.get("reason") or candidate.get("reason"),
                }
            )

    top_missed.sort(
        key=lambda item: (
            -float(item.get("forward_mfe_pct") or 0.0),
            str(item.get("candidate_ts") or ""),
            str(item.get("symbol") or ""),
        )
    )
    reason_token_counts = _count_rows(reason_tokens)
    summary = {
        "report_version": MISSED_BUY_REVIEW_VERSION,
        "runtime_effect": MISSED_BUY_REVIEW_RUNTIME_EFFECT,
        "authority_ready": False,
        "authority_note": "review-only; does not approve, block, or size trades",
        "candidate_rows": len(rows),
        "rows_with_forward_outcome": rows_with_forward,
        "forward_outcome_coverage_rate": _rate(rows_with_forward, len(rows)),
        "non_taken_with_forward_outcome": non_taken_with_forward,
        "missed_good_candidates": missed_good,
        "high_quality_missed_candidates": high_quality_missed,
        "correctly_avoided_or_bad_candidates": correctly_avoided,
        "missed_good_rate_of_non_taken_with_forward": _rate(missed_good, non_taken_with_forward),
        "quality_counts": dict(sorted(quality_counts.items())),
        "soft_block_missed_good_candidates": soft_block_missed_good,
        "paper_promotion_review_candidates": promotion_review_candidates,
        "avg_missed_good_mfe_pct": (
            round(sum(missed_mfe_values) / len(missed_mfe_values), 4)
            if missed_mfe_values
            else None
        ),
        "avg_missed_good_return_pct": (
            round(sum(missed_return_values) / len(missed_return_values), 4)
            if missed_return_values
            else None
        ),
        "min_mfe_pct": min_mfe_pct,
    }
    return MissedBuyReviewPayload(
        summary=summary,
        top_missed=top_missed,
        reason_token_counts=reason_token_counts,
        symbol_counts=_count_rows(symbol_values),
        pattern_counts=_count_rows(pattern_values),
        learning_actions=_learning_actions(
            coverage_rate=summary["forward_outcome_coverage_rate"],
            reason_counts=reason_token_counts,
            missed_good=missed_good,
            high_quality_missed=high_quality_missed,
        ),
    )
