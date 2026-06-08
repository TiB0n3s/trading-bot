"""Paper-only validation for historical-bar intelligence scores."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from repositories.historical_bar_training_repo import fetch_historical_bar_training_rows


PAPER_VALIDATION_VERSION = "historical_bar_paper_validation_v1"
WALK_FORWARD_VERSION = "historical_bar_walk_forward_v1"


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _label(row: dict[str, Any], label_target: str) -> int | None:
    value = _float(row.get(label_target))
    if value is None:
        return None
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _paper_score(row: dict[str, Any]) -> float:
    components: list[float] = []
    for key in ("long_opportunity_score", "pattern_score"):
        value = _float(row.get(key))
        if value is not None:
            components.append(_clamp(value))
    pressure = _float(row.get("volume_weighted_pressure_3"))
    if pressure is not None:
        components.append(_clamp(50.0 + pressure * 10.0))
    cvd = _float(row.get("cvd_price_corr_20"))
    if cvd is not None:
        components.append(_clamp(50.0 + cvd * 25.0))
    frac = _float(row.get("fractional_diff_zscore_20"))
    if frac is not None:
        components.append(_clamp(50.0 + frac * 8.0))
    vpin = _float(row.get("vpin_toxicity_20"))
    if vpin is not None:
        components.append(_clamp(70.0 - vpin * 30.0))
    if not components:
        return 50.0
    return round(sum(components) / len(components), 4)


def _baseline_score(row: dict[str, Any]) -> float:
    score = 50.0
    rsi = _float(row.get("rsi_14"))
    close_location = _float(row.get("close_location"))
    price_vs_sma = _float(row.get("price_vs_sma_20_pct"))
    if rsi is not None:
        if rsi <= 35:
            score += 12.0
        elif rsi >= 70:
            score -= 10.0
        else:
            score += (50.0 - abs(rsi - 50.0)) / 50.0 * 6.0
    if close_location is not None:
        score += (close_location - 0.5) * 10.0
    if price_vs_sma is not None:
        if price_vs_sma < -1.0:
            score += 8.0
        elif price_vs_sma > 2.0:
            score -= 8.0
    return round(_clamp(score), 4)


def _score_rows(rows: list[dict[str, Any]], *, label_target: str, threshold: float) -> dict[str, Any]:
    total = 0
    paper_taken = 0
    paper_winners = 0
    paper_losers = 0
    baseline_taken = 0
    baseline_winners = 0
    false_positive_avoided = 0
    false_negative_cost = 0
    score_edges: list[float] = []
    by_phase: dict[str, list[int]] = defaultdict(list)

    for row in rows:
        label = _label(row, label_target)
        if label is None:
            continue
        total += 1
        paper = _paper_score(row)
        baseline = _baseline_score(row)
        paper_take = paper >= threshold
        baseline_take = baseline >= threshold
        if paper_take:
            paper_taken += 1
            paper_winners += int(label > 0)
            paper_losers += int(label < 0)
            score_edges.append(paper - baseline)
        if baseline_take:
            baseline_taken += 1
            baseline_winners += int(label > 0)
        if baseline_take and not paper_take and label < 0:
            false_positive_avoided += 1
        if not paper_take and label > 0:
            false_negative_cost += 1
        minute = int(_float(row.get("minute_of_day")) or 0)
        phase = "open" if minute < 600 else "midday" if minute < 840 else "late"
        by_phase[phase].append(label)

    phase_rows = []
    for phase, labels in sorted(by_phase.items()):
        phase_rows.append(
            {
                "phase": phase,
                "rows": len(labels),
                "positive_rate": round(sum(1 for item in labels if item > 0) / len(labels), 4)
                if labels
                else 0.0,
            }
        )
    return {
        "rows": total,
        "threshold": threshold,
        "paper_taken": paper_taken,
        "paper_hit_rate": round(paper_winners / paper_taken, 4) if paper_taken else 0.0,
        "paper_loss_rate": round(paper_losers / paper_taken, 4) if paper_taken else 0.0,
        "baseline_taken": baseline_taken,
        "baseline_hit_rate": round(baseline_winners / baseline_taken, 4) if baseline_taken else 0.0,
        "hit_rate_delta": round(
            (paper_winners / paper_taken if paper_taken else 0.0)
            - (baseline_winners / baseline_taken if baseline_taken else 0.0),
            4,
        ),
        "false_positive_avoided": false_positive_avoided,
        "false_negative_cost": false_negative_cost,
        "avg_paper_minus_baseline_score": round(sum(score_edges) / len(score_edges), 4)
        if score_edges
        else 0.0,
        "phase_rows": phase_rows,
    }


def _parse_thresholds(raw: str | None, fallback: float) -> list[float]:
    if not raw:
        return [fallback]
    output: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            output.append(float(part))
        except ValueError:
            continue
    return output or [fallback]


def _readiness_from_thresholds(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [row for row in rows if int(row.get("paper_taken") or 0) > 0]
    if not candidates:
        return {
            "status": "not_ready",
            "recommended_threshold": None,
            "blockers": ["no_paper_candidates_at_tested_thresholds"],
        }
    def blockers_for(row: dict[str, Any]) -> list[str]:
        blockers = []
        if int(row.get("paper_taken") or 0) < 20:
            blockers.append("fewer_than_20_paper_candidates")
        if float(row.get("hit_rate_delta") or 0.0) <= 0:
            blockers.append("no_positive_hit_rate_delta")
        if float(row.get("paper_loss_rate") or 0.0) >= 0.45:
            blockers.append("paper_loss_rate_at_or_above_45pct")
        return blockers

    ranked = sorted(
        candidates,
        key=lambda row: (
            len(blockers_for(row)) == 0,
            float(row.get("hit_rate_delta") or 0.0),
            int(row.get("false_positive_avoided") or 0),
            -int(row.get("false_negative_cost") or 0),
            int(row.get("paper_taken") or 0),
        ),
        reverse=True,
    )
    best = ranked[0]
    blockers = blockers_for(best)
    return {
        "status": "paper_soft_modifier_candidate" if not blockers else "observe_only",
        "recommended_threshold": best.get("threshold"),
        "blockers": blockers,
        "best": best,
    }


def build_historical_bar_paper_validation_payload(
    *,
    base_dir: Path,
    start_date: str,
    end_date: str,
    label_target: str,
    rows_per_symbol: int,
    limit: int,
    threshold: float,
    thresholds: list[float] | None = None,
) -> dict[str, Any]:
    rows = fetch_historical_bar_training_rows(
        db_path=base_dir / "trades.db",
        start_date=start_date,
        end_date=end_date,
        label_target=label_target,
        rows_per_symbol=rows_per_symbol,
        limit=limit,
    )
    tested_thresholds = thresholds or [threshold]
    sweep = [
        _score_rows(rows, label_target=label_target, threshold=item)
        for item in tested_thresholds
    ]
    scored = sweep[0] if len(sweep) == 1 else _score_rows(rows, label_target=label_target, threshold=threshold)
    readiness = _readiness_from_thresholds(sweep)
    return {
        "report_version": PAPER_VALIDATION_VERSION,
        "runtime_effect": "paper_validation_only_no_live_authority",
        "start_date": start_date,
        "end_date": end_date,
        "label_target": label_target,
        "symbol_count": len({row.get("symbol") for row in rows if row.get("symbol")}),
        "threshold_sweep": sweep,
        "promotion_readiness": readiness,
        **scored,
    }


def build_historical_bar_walk_forward_payload(
    *,
    base_dir: Path,
    start_date: str,
    end_date: str,
    label_target: str,
    rows_per_symbol: int,
    limit: int,
    threshold: float,
    folds: int,
) -> dict[str, Any]:
    rows = fetch_historical_bar_training_rows(
        db_path=base_dir / "trades.db",
        start_date=start_date,
        end_date=end_date,
        label_target=label_target,
        rows_per_symbol=rows_per_symbol,
        limit=limit,
    )
    rows = sorted(rows, key=lambda row: str(row.get("bar_timestamp") or ""))
    folds = max(2, int(folds or 5))
    fold_size = max(1, len(rows) // folds)
    fold_rows = []
    for idx in range(folds):
        start = idx * fold_size
        end = len(rows) if idx == folds - 1 else (idx + 1) * fold_size
        chunk = rows[start:end]
        if not chunk:
            continue
        metrics = _score_rows(chunk, label_target=label_target, threshold=threshold)
        fold_rows.append(
            {
                "fold": idx + 1,
                "start_ts": chunk[0].get("bar_timestamp"),
                "end_ts": chunk[-1].get("bar_timestamp"),
                **metrics,
            }
        )
    hit_rates = [float(row["paper_hit_rate"]) for row in fold_rows if int(row["paper_taken"]) > 0]
    zero_candidate_folds = sum(1 for row in fold_rows if int(row.get("paper_taken") or 0) == 0)
    negative_delta_folds = sum(1 for row in fold_rows if float(row.get("hit_rate_delta") or 0.0) <= 0)
    spread = round(max(hit_rates) - min(hit_rates), 4) if len(hit_rates) >= 2 else None
    blockers = []
    if zero_candidate_folds:
        blockers.append(f"{zero_candidate_folds}_folds_without_paper_candidates")
    if negative_delta_folds:
        blockers.append(f"{negative_delta_folds}_folds_without_positive_delta")
    if spread is not None and spread > 0.25:
        blockers.append("fold_hit_rate_spread_above_25pct")
    return {
        "report_version": WALK_FORWARD_VERSION,
        "runtime_effect": "walk_forward_validation_only_no_live_authority",
        "start_date": start_date,
        "end_date": end_date,
        "label_target": label_target,
        "rows": len(rows),
        "folds": fold_rows,
        "fold_hit_rate_min": round(min(hit_rates), 4) if hit_rates else None,
        "fold_hit_rate_max": round(max(hit_rates), 4) if hit_rates else None,
        "fold_hit_rate_spread": spread,
        "zero_candidate_folds": zero_candidate_folds,
        "negative_delta_folds": negative_delta_folds,
        "stability_status": "stable_paper_candidate" if not blockers else "observe_only",
        "stability_blockers": blockers,
    }


def run_historical_bar_paper_validation(
    *,
    base_dir: Path,
    start_date: str,
    end_date: str,
    label_target: str = "triple_barrier_label",
    rows_per_symbol: int = 250,
    limit: int = 30000,
    threshold: float = 65.0,
    thresholds: list[float] | None = None,
) -> bool:
    payload = build_historical_bar_paper_validation_payload(
        base_dir=base_dir,
        start_date=start_date,
        end_date=end_date,
        label_target=label_target,
        rows_per_symbol=rows_per_symbol,
        limit=limit,
        threshold=threshold,
        thresholds=thresholds,
    )
    print()
    print("=" * 72)
    print("  Historical Bar Paper Validation")
    print("=" * 72)
    for key in (
        "report_version",
        "runtime_effect",
        "start_date",
        "end_date",
        "label_target",
        "rows",
        "symbol_count",
        "threshold",
        "paper_taken",
        "paper_hit_rate",
        "paper_loss_rate",
        "baseline_taken",
        "baseline_hit_rate",
        "hit_rate_delta",
        "false_positive_avoided",
        "false_negative_cost",
    ):
        print(f"{key:<28}: {payload.get(key)}")
    if len(payload.get("threshold_sweep") or []) > 1:
        print()
        print("Threshold sweep")
        for row in payload["threshold_sweep"]:
            print(
                f"  threshold={float(row['threshold']):<6.1f} "
                f"taken={int(row['paper_taken']):<6} "
                f"hit={float(row['paper_hit_rate']):<6.3f} "
                f"base={float(row['baseline_hit_rate']):<6.3f} "
                f"delta={float(row['hit_rate_delta']):<7.3f} "
                f"fp_avoided={int(row['false_positive_avoided']):<5} "
                f"fn_cost={int(row['false_negative_cost']):<5}"
            )
    readiness = payload.get("promotion_readiness") or {}
    print()
    print("Paper promotion readiness")
    print(f"  status                 : {readiness.get('status')}")
    print(f"  recommended_threshold  : {readiness.get('recommended_threshold')}")
    blockers = readiness.get("blockers") or []
    print(f"  blockers               : {', '.join(blockers) if blockers else '-'}")
    print()
    print("[OK] paper validation generated" if payload["rows"] else "[WARN] no rows available")
    return bool(payload["rows"])


def run_historical_bar_walk_forward(
    *,
    base_dir: Path,
    start_date: str,
    end_date: str,
    label_target: str = "triple_barrier_label",
    rows_per_symbol: int = 250,
    limit: int = 30000,
    threshold: float = 65.0,
    folds: int = 5,
) -> bool:
    payload = build_historical_bar_walk_forward_payload(
        base_dir=base_dir,
        start_date=start_date,
        end_date=end_date,
        label_target=label_target,
        rows_per_symbol=rows_per_symbol,
        limit=limit,
        threshold=threshold,
        folds=folds,
    )
    print()
    print("=" * 72)
    print("  Historical Bar Walk-Forward Validation")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"date_filter             : {start_date}..{end_date}")
    print(f"label_target            : {label_target}")
    print(f"rows                    : {payload['rows']}")
    print(f"fold_hit_rate_spread    : {payload['fold_hit_rate_spread']}")
    print(f"stability_status        : {payload['stability_status']}")
    print(
        "stability_blockers      : "
        + (", ".join(payload["stability_blockers"]) if payload["stability_blockers"] else "-")
    )
    print()
    print("Folds")
    for row in payload["folds"]:
        print(
            f"  {row['fold']:<2} {row['start_ts']}..{row['end_ts']} "
            f"taken={row['paper_taken']:<5} hit={row['paper_hit_rate']:<6.3f} "
            f"base={row['baseline_hit_rate']:<6.3f} delta={row['hit_rate_delta']:<7.3f}"
        )
    ok = bool(payload["rows"]) and bool(payload["folds"])
    print()
    print("[OK] walk-forward validation generated" if ok else "[WARN] insufficient rows")
    return ok
