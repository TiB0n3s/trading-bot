"""Readiness scoring for advanced alpha feature families.

This is an evidence/reporting layer only. It measures whether advanced feature
families have enough feed, schema, coverage, outcome, and ops support to be
considered for future promotion. It cannot approve, size, block, or execute.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
from typing import Any

from repositories.bar_pattern_feature_repo import BarPatternFeatureRepository
from services.optional_dependency_service import optional_dependency_status


ADVANCED_ALPHA_READINESS_VERSION = "advanced_alpha_readiness_v1"
ADVANCED_ALPHA_RUNTIME_EFFECT = "readiness_only_no_live_authority"


@dataclass(frozen=True)
class AlphaReadinessItem:
    feature_family: str
    readiness_pct: float
    status: str
    passed_checks: int
    total_checks: int
    passed: list[str]
    failed: list[str]
    current_capability: str
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdvancedAlphaReadinessPayload:
    report_version: str
    runtime_effect: str
    target_date: str
    rows: int
    items: list[AlphaReadinessItem]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "runtime_effect": self.runtime_effect,
            "target_date": self.target_date,
            "rows": self.rows,
            "items": [item.to_dict() for item in self.items],
            "summary": self.summary,
        }


def _env_true(env: dict[str, str], key: str) -> bool:
    return str(env.get(key) or "").strip().lower() in {"1", "true", "yes", "on"}


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)


def _pct(count: int, total: int) -> float:
    return round(_rate(count, total) * 100.0, 2)


_CRITICAL_GATES = {
    "schema_integrated",
    "feature_coverage_ge_80pct",
    "feature_coverage_ge_95pct",
    "outcome_linkage_ge_500",
    "sample_size_ge_500",
    "candidate_model_comparison_report",
    "reads_real_reports",
}


def _status(readiness_pct: float, failed: list[str]) -> str:
    if any(item in _CRITICAL_GATES for item in failed):
        if readiness_pct >= 40:
            return "partially_integrated"
        return "not_ready"
    if readiness_pct >= 85:
        return "promotion_evidence_candidate"
    if readiness_pct >= 65:
        return "paper_research_ready"
    if readiness_pct >= 40:
        return "partially_integrated"
    return "not_ready"


def _item(
    *,
    feature_family: str,
    checks: dict[str, bool],
    current_capability: str,
    next_action: str,
) -> AlphaReadinessItem:
    passed = [key for key, ok in checks.items() if ok]
    failed = [key for key, ok in checks.items() if not ok]
    total = max(1, len(checks))
    readiness_pct = round(len(passed) / total * 100.0, 2)
    return AlphaReadinessItem(
        feature_family=feature_family,
        readiness_pct=readiness_pct,
        status=_status(readiness_pct, failed),
        passed_checks=len(passed),
        total_checks=total,
        passed=passed,
        failed=failed,
        current_capability=current_capability,
        next_action=next_action,
    )


def build_advanced_alpha_readiness_payload(
    *,
    target_date: str,
    db_path: Path | str,
    env: dict[str, str] | None = None,
    bar_summary: dict[str, Any] | None = None,
) -> AdvancedAlphaReadinessPayload:
    env = dict(os.environ if env is None else env)
    summary = (
        dict(bar_summary)
        if bar_summary is not None
        else BarPatternFeatureRepository(db_path).summary(target_date)
    )
    rows = int(summary.get("rows") or 0)
    rows_with_forward = int(summary.get("rows_with_forward_outcome") or 0)
    rows_with_order_flow = int(summary.get("rows_with_order_flow") or 0)
    rows_with_fractional = int(summary.get("rows_with_fractional_memory") or 0)
    rows_with_microstructure = int(summary.get("rows_with_microstructure_context") or 0)
    trend_scan_rows = sum(int(row.get("rows") or 0) for row in summary.get("trend_scans", []))
    cvd_rows = sum(int(row.get("rows") or 0) for row in summary.get("cvd_divergences", []))

    deps = optional_dependency_status()
    packages = deps.get("packages", {})
    xgboost_available = bool((packages.get("xgboost") or {}).get("available"))
    plotly_available = bool((packages.get("plotly") or {}).get("available"))
    streamlit_available = bool((packages.get("streamlit") or {}).get("available"))

    polygon_configured = bool(env.get("POLYGON_API_KEY"))
    alpaca_configured = bool(env.get("ALPACA_API_KEY") and env.get("ALPACA_SECRET_KEY"))
    true_order_flow_feed = _env_true(env, "ORDER_FLOW_TRADE_FEED_ENABLED") or _env_true(
        env, "POLYGON_TRADES_API_ENABLED"
    )
    volume_clock_enabled = _env_true(env, "VOLUME_CLOCK_VPIN_ENABLED") or _env_true(
        env, "VOLUME_BAR_FEATURES_ENABLED"
    )
    lsi_enabled = _env_true(env, "LIQUIDITY_STRESS_INDICATOR_ENABLED")
    reference_feed = _env_true(env, "ETF_LEAD_LAG_ENABLED") or bool(
        env.get("ETF_LEAD_LAG_REFERENCE_SYMBOLS")
    )
    options_feed = _env_true(env, "OPTIONS_FLOW_ENABLED") or bool(env.get("OPTIONS_DATA_API_KEY"))

    coverage_threshold_met = rows >= 500
    outcome_threshold_met = rows_with_forward >= 500
    comparison_report_available = trend_scan_rows > 0 and outcome_threshold_met

    items = [
        _item(
            feature_family="bar_order_flow_proxy",
            checks={
                "bar_feed_available": polygon_configured or alpaca_configured,
                "schema_integrated": True,
                "feature_coverage_ge_80pct": rows > 0 and _rate(rows_with_order_flow, rows) >= 0.80,
                "outcome_linkage_ge_500": outcome_threshold_met,
                "sample_size_ge_500": coverage_threshold_met,
                "ops_report_visible": True,
                "authority_leak_safe": True,
            },
            current_capability=(
                "Bar-level tick-test CVD/VPIN proxy is persisted and exported; "
                "not true trade-level aggressor-side order flow."
            ),
            next_action="Accumulate rows, then compare CVD divergence and VPIN buckets against MFE/MAE/EV.",
        ),
        _item(
            feature_family="true_trade_level_vpin",
            checks={
                "trade_level_feed_available": true_order_flow_feed,
                "schema_integrated": False,
                "feature_coverage_ge_95pct": False,
                "outcome_linkage_ge_500": False,
                "ops_report_visible": False,
                "authority_leak_safe": True,
            },
            current_capability="Not populated; current system has only bar-level proxy order-flow features.",
            next_action="Enable a trade-level feed with aggressor side or a validated classifier, then add a separate trade-flow table.",
        ),
        _item(
            feature_family="volume_clock_vpin",
            checks={
                "volume_clock_enabled": volume_clock_enabled,
                "bar_feed_available": polygon_configured or alpaca_configured,
                "schema_integrated": False,
                "feature_coverage_ge_95pct": False,
                "outcome_linkage_ge_500": False,
                "ops_report_visible": False,
                "authority_leak_safe": True,
            },
            current_capability=(
                "Not populated; current VPIN proxy is calculated on fixed-time "
                "1-minute bars, not fixed-volume buckets."
            ),
            next_action=(
                "Build volume-bar sampling from trade/bar volume, persist volume "
                "bucket IDs, then compare volume-clock VPIN against MFE/MAE."
            ),
        ),
        _item(
            feature_family="liquidity_stress_indicator",
            checks={
                "bar_order_flow_proxy_available": rows > 0 and _rate(rows_with_order_flow, rows) >= 0.80,
                "execution_microstructure_available": rows > 0 and _rate(rows_with_microstructure, rows) >= 0.80,
                "lsi_feature_enabled": lsi_enabled,
                "schema_integrated": False,
                "outcome_linkage_ge_500": outcome_threshold_met,
                "ops_report_visible": False,
                "authority_leak_safe": True,
            },
            current_capability=(
                "Inputs exist partially through VPIN/CVD proxies and execution "
                "quality fields, but no unified LSI feature is persisted."
            ),
            next_action=(
                "Aggregate VPIN, spread/slippage deterioration, quote instability, "
                "and volatility stretch into an observe-only LSI bucket."
            ),
        ),
        _item(
            feature_family="etf_component_lead_lag",
            checks={
                "reference_bar_feed_available": polygon_configured or alpaca_configured,
                "symbol_to_reference_mapping_configured": reference_feed,
                "schema_integrated": False,
                "timestamp_alignment_defined": False,
                "outcome_linkage_ge_500": False,
                "ops_report_visible": False,
                "authority_leak_safe": True,
            },
            current_capability="Not populated; no ETF/component reference mapping is currently persisted.",
            next_action="Add sector/index reference symbol mapping, archive aligned reference bars, then export lead/lag return deltas.",
        ),
        _item(
            feature_family="options_skew_flow",
            checks={
                "options_feed_available": options_feed,
                "schema_integrated": False,
                "illiquid_chain_filter_defined": False,
                "outcome_linkage_ge_500": False,
                "ops_report_visible": False,
                "authority_leak_safe": True,
            },
            current_capability="Not populated; no options chain/flow ingestion is configured.",
            next_action="Choose a low-cost options source, normalize OTM put/call and IV-skew buckets, and keep context-only initially.",
        ),
        _item(
            feature_family="fractional_memory_trend_scan",
            checks={
                "schema_integrated": True,
                "feature_coverage_ge_80pct": rows > 0 and _rate(rows_with_fractional, rows) >= 0.80,
                "trend_scan_labels_present": trend_scan_rows > 0,
                "outcome_linkage_ge_500": outcome_threshold_met,
                "sample_size_ge_500": coverage_threshold_met,
                "ops_report_visible": True,
                "authority_leak_safe": True,
            },
            current_capability="Fractional price-memory and trend-scanning labels are persisted and exported.",
            next_action="Accumulate enough rows and run stability/expectancy checks by regime and session phase.",
        ),
        _item(
            feature_family="asymmetric_loss_model_comparison",
            checks={
                "xgboost_available": xgboost_available,
                "triple_barrier_labels_present": bool(summary.get("triple_barriers")),
                "trend_scan_labels_present": trend_scan_rows > 0,
                "outcome_linkage_ge_500": outcome_threshold_met,
                "sample_size_ge_500": coverage_threshold_met,
                "candidate_model_comparison_report": comparison_report_available,
                "authority_leak_safe": True,
            },
            current_capability="Training substrate exists; offline symmetric vs asymmetric comparison is reportable.",
            next_action="Use the comparison report to monitor net EV, drawdown, and false positives before any authority promotion.",
        ),
        _item(
            feature_family="model_monitor_dashboard",
            checks={
                "plotly_available": plotly_available,
                "streamlit_available": streamlit_available,
                "reads_real_reports": False,
                "shadow_vs_live_model_metrics_available": False,
                "no_execution_imports": True,
                "authority_leak_safe": True,
            },
            current_capability="No dashboard is wired; ops CLI reports remain the current monitor surface.",
            next_action="Add a read-only dashboard only after the DB/report payloads stabilize.",
        ),
    ]

    ready_counts: dict[str, int] = {}
    for item in items:
        ready_counts[item.status] = ready_counts.get(item.status, 0) + 1

    return AdvancedAlphaReadinessPayload(
        report_version=ADVANCED_ALPHA_READINESS_VERSION,
        runtime_effect=ADVANCED_ALPHA_RUNTIME_EFFECT,
        target_date=target_date,
        rows=rows,
        items=items,
        summary={
            "rows": rows,
            "rows_with_forward_outcome": rows_with_forward,
            "rows_with_order_flow": rows_with_order_flow,
            "rows_with_fractional_memory": rows_with_fractional,
            "rows_with_microstructure_context": rows_with_microstructure,
            "trend_scan_rows": trend_scan_rows,
            "cvd_divergence_rows": cvd_rows,
            "order_flow_coverage_rate": _pct(rows_with_order_flow, rows),
            "microstructure_coverage_rate": _pct(rows_with_microstructure, rows),
            "fractional_memory_coverage_rate": _pct(rows_with_fractional, rows),
            "status_counts": dict(sorted(ready_counts.items())),
            "authority_ready": False,
        },
    )
