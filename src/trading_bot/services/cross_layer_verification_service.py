"""Cross-layer verification matrix for paper model decision topology."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from ml_platform.config import MODEL_ROOT

CROSS_LAYER_VERIFICATION_VERSION = "cross_layer_verification_matrix_v1"
DEFAULT_DRIFT_ARTIFACT_PATH = MODEL_ROOT / "veto_relaxation_v1" / "concept_drift.json"


@dataclass(frozen=True)
class CrossLayerVerificationPayload:
    report_version: str
    runtime_effect: str
    target_date: str
    summary: dict[str, Any]
    drift_relaxation_symmetry: dict[str, Any]
    veto_to_sizing_handshake: dict[str, Any]
    marginal_risk_translation: dict[str, Any]
    cross_layer_anomaly: dict[str, Any]
    examples: list[dict[str, Any]]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _path(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        parsed = float(value)
    except Exception:
        return None
    return parsed if parsed == parsed else None


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(count / total, 4)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mean_x = mean(xs)
    mean_y = mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x <= 0 or den_y <= 0:
        return None
    return round(numerator / (den_x * den_y), 4)


def _stable_level0(regime: dict[str, Any], alt_gate: dict[str, Any]) -> bool:
    if str(alt_gate.get("decision") or "pass") == "veto":
        return False
    if regime.get("allow_new_longs") is False:
        return False
    size_modifier = _num(regime.get("size_modifier"))
    if size_modifier is not None and size_modifier < 0.90:
        return False
    label = str(regime.get("regime_label") or "").lower()
    if any(token in label for token in ("high", "crash", "panic", "bear", "volatile")):
        return False
    return True


def _layered_payload(row: dict[str, Any]) -> dict[str, Any]:
    canonical = _load_json(row.get("canonical_intelligence_json"))
    account_state = _load_json(row.get("account_state_json"))
    candidates = (
        canonical,
        canonical.get("layered_model_decision"),
        canonical.get("layered_model_decision_state"),
        account_state.get("layered_model_decision"),
        account_state.get("layered_model_decision_state"),
    )
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("version") == "layered_model_decision_v1":
            return candidate
    return {}


def _load_drift_artifact(path: Path | str = DEFAULT_DRIFT_ARTIFACT_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    return _load_json(path.read_text())


def build_cross_layer_verification_payload(
    rows: list[dict[str, Any]],
    *,
    target_date: str,
    drift_artifact_path: Path | str = DEFAULT_DRIFT_ARTIFACT_PATH,
) -> CrossLayerVerificationPayload:
    rows = [dict(row) for row in rows]
    drift = _load_drift_artifact(drift_artifact_path)
    layered_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for row in rows:
        layered = _layered_payload(row)
        if layered:
            layered_rows.append((row, layered))

    veto_rows = 0
    drift_disabled = 0
    relaxation_active = 0
    high_unveto = 0
    p_unveto_values: list[float] = []

    marginal_approvals = 0
    marginal_scaled_down = 0
    marginal_size_ratios: list[float] = []
    marginal_scores: list[float] = []
    marginal_allocation_multipliers: list[float] = []
    marginal_max_size_rows = 0
    stable_low_confidence_rows = 0
    stable_low_confidence_symbols: set[str] = set()
    stable_low_confidence_scores: list[float] = []
    examples: list[dict[str, Any]] = []

    for row, layered in layered_rows:
        regime = _load_json(layered.get("level_0_regime"))
        alt_gate = _load_json(layered.get("level_0_alternative_gates"))
        meta = _load_json(layered.get("level_2_meta_label"))
        sizing = _load_json(layered.get("level_3_sizing"))
        final_instruction = str(layered.get("final_instruction") or "")
        instruction = str(meta.get("instruction") or "")
        if final_instruction == "veto" or instruction == "veto":
            veto_rows += 1

        unveto = _load_json(meta.get("counterfactual_veto_relaxation"))
        status = str(unveto.get("status") or "")
        if status == "concept_drift_disabled":
            drift_disabled += 1
        p_unveto = _num(unveto.get("p_unveto"))
        if p_unveto is not None:
            p_unveto_values.append(p_unveto)
            if p_unveto >= 0.75:
                high_unveto += 1
        relaxation = _num(unveto.get("threshold_relaxation_pct"))
        if relaxation is not None and relaxation > 0:
            relaxation_active += 1

        score = _num(meta.get("success_probability"))
        threshold = _num(meta.get("threshold"))
        if score is not None and score > 1.0:
            score /= 100.0
        if threshold is not None and threshold > 1.0:
            threshold /= 100.0
        margin = None
        if score is not None and threshold is not None:
            margin = score - threshold

        final_size = _num(sizing.get("final_size_pct"))
        requested_size = _num(sizing.get("requested_size_pct"))
        regime_adjusted = _num(sizing.get("regime_adjusted_size_pct"))
        denominator = regime_adjusted if regime_adjusted and regime_adjusted > 0 else requested_size
        if score is not None and 0.65 <= score <= 0.70 and final_size is not None:
            if denominator and denominator > 0:
                allocation_multiplier = final_size / denominator
                marginal_scores.append(score)
                marginal_allocation_multipliers.append(allocation_multiplier)
                if allocation_multiplier >= 0.95:
                    marginal_max_size_rows += 1
        if (
            final_instruction in {"paper_approval", "pass", "size_increase"}
            and margin is not None
            and 0 <= margin <= 0.02
        ):
            marginal_approvals += 1
            if final_size is not None and denominator and denominator > 0:
                ratio = final_size / denominator
                marginal_size_ratios.append(ratio)
                if ratio < 0.90:
                    marginal_scaled_down += 1
            examples.append(
                {
                    "snapshot_id": row.get("id"),
                    "symbol": row.get("symbol"),
                    "decision_time": row.get("decision_time"),
                    "score": round(score, 4) if score is not None else None,
                    "threshold": round(threshold, 4) if threshold is not None else None,
                    "margin": round(margin, 4),
                    "final_size_pct": final_size,
                    "requested_or_regime_size_pct": denominator,
                    "final_instruction": final_instruction,
                }
            )
        if score is not None and score < 0.50 and _stable_level0(regime, alt_gate):
            stable_low_confidence_rows += 1
            if row.get("symbol"):
                stable_low_confidence_symbols.add(str(row["symbol"]).upper())
            stable_low_confidence_scores.append(score)

    severe_drift = bool(drift.get("severe_drift"))
    veto_rate = _rate(veto_rows, len(layered_rows))
    relaxation_rate = _rate(relaxation_active, len(layered_rows))
    drift_disabled_rate = _rate(drift_disabled, len(layered_rows))
    warnings: list[str] = []
    if rows and not layered_rows:
        warnings.append(
            "decision snapshots exist but no layered_model_decision_v1 payloads were found"
        )
    if severe_drift and drift_disabled == 0 and layered_rows:
        warnings.append(
            "severe PSI drift artifact exists but no layered rows show relaxation disablement"
        )
    if relaxation_active and severe_drift:
        warnings.append("counterfactual relaxation is active despite severe drift artifact")
    if marginal_approvals and marginal_scaled_down == 0:
        warnings.append("marginal Level-2 approvals did not show Level-3 size-down evidence")
    marginal_corr = _pearson(marginal_scores, marginal_allocation_multipliers)
    if len(marginal_scores) >= 3 and marginal_corr is not None and marginal_corr < 0.25:
        warnings.append(
            "weak marginal confidence-to-allocation correlation; Level-3 may not be translating Level-2 risk"
        )
    if len(marginal_scores) >= 3 and marginal_max_size_rows / len(marginal_scores) > 0.50:
        warnings.append("most marginal-confidence rows still received near-maximum allocation")
    anomaly_status = "not_enough_evidence"
    if layered_rows:
        if stable_low_confidence_rows >= 3 and len(stable_low_confidence_symbols) >= 3:
            anomaly_status = "stable_level0_low_level2_confidence_cluster"
            warnings.append(
                "Level 0 appears stable while Level 2 confidence dropped across multiple symbols"
            )
        else:
            anomaly_status = "no_stable_level0_level2_divergence"

    drift_symmetry_status = "not_enough_layered_evidence"
    if layered_rows:
        if severe_drift and veto_rate is not None and veto_rate >= 0.50:
            drift_symmetry_status = "drift_alert_aligned_with_high_veto_rate"
        elif severe_drift:
            drift_symmetry_status = "drift_alert_without_veto_spike"
        else:
            drift_symmetry_status = "no_severe_drift"

    handshake_status = "not_enough_marginal_approvals"
    if marginal_approvals:
        handshake_status = (
            "marginal_approvals_scaled_down"
            if marginal_scaled_down > 0
            else "marginal_approvals_not_scaled_down"
        )

    return CrossLayerVerificationPayload(
        report_version=CROSS_LAYER_VERIFICATION_VERSION,
        runtime_effect="paper_diagnostic_no_order_authority",
        target_date=target_date,
        summary={
            "decision_rows": len(rows),
            "layered_rows": len(layered_rows),
            "layered_coverage_rate": _rate(len(layered_rows), len(rows)),
            "veto_rows": veto_rows,
            "veto_rate": veto_rate,
        },
        drift_relaxation_symmetry={
            "status": drift_symmetry_status,
            "drift_artifact_present": bool(drift),
            "severe_drift": severe_drift,
            "max_psi": drift.get("max_psi"),
            "relaxation_active_rows": relaxation_active,
            "relaxation_active_rate": relaxation_rate,
            "drift_disabled_rows": drift_disabled,
            "drift_disabled_rate": drift_disabled_rate,
            "high_unveto_rows": high_unveto,
            "avg_p_unveto": round(mean(p_unveto_values), 4) if p_unveto_values else None,
        },
        veto_to_sizing_handshake={
            "status": handshake_status,
            "marginal_approval_rows": marginal_approvals,
            "marginal_scaled_down_rows": marginal_scaled_down,
            "marginal_scaled_down_rate": _rate(marginal_scaled_down, marginal_approvals),
            "avg_marginal_size_ratio": round(mean(marginal_size_ratios), 4)
            if marginal_size_ratios
            else None,
            "margin_definition": "0 <= success_probability - threshold <= 0.02",
        },
        marginal_risk_translation={
            "status": (
                "correlation_available"
                if marginal_corr is not None
                else "not_enough_marginal_confidence_rows"
            ),
            "band": "0.65 <= success_probability <= 0.70",
            "rows": len(marginal_scores),
            "correlation": marginal_corr,
            "avg_allocation_multiplier": round(mean(marginal_allocation_multipliers), 4)
            if marginal_allocation_multipliers
            else None,
            "near_max_allocation_rows": marginal_max_size_rows,
            "near_max_allocation_rate": _rate(marginal_max_size_rows, len(marginal_scores)),
        },
        cross_layer_anomaly={
            "status": anomaly_status,
            "stable_level0_low_level2_rows": stable_low_confidence_rows,
            "stable_level0_low_level2_symbols": len(stable_low_confidence_symbols),
            "avg_low_level2_score": round(mean(stable_low_confidence_scores), 4)
            if stable_low_confidence_scores
            else None,
            "definition": "stable Level 0 plus Level 2 success_probability < 0.50 across >=3 symbols",
        },
        examples=examples[:20],
        warnings=warnings,
    )
