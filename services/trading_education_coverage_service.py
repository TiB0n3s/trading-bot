"""Coverage and gap analysis for the trading education corpus."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from repositories.trading_education_repo import TradingEducationRepository
from services.optional_dependency_service import optional_dependency_status
from services.trading_education_corpus_service import (
    CURATED_TRADING_EDUCATION_CONCEPTS,
    TRADING_EDUCATION_RUNTIME_EFFECT,
)


TRADING_EDUCATION_COVERAGE_VERSION = "trading_education_coverage_v1"

EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    "venv",
    ".pytest_cache",
    "strategy_memory_history",
    "runtime_state",
    "research_exports",
}
SCANNED_SUFFIXES = {".py", ".md", ".sh"}

QUANT_STACK_PACKAGES = (
    "numpy",
    "pandas",
    "sklearn",
    "xgboost",
    "torch",
    "yfinance",
    "vectorbt",
    "backtrader",
)

CAPABILITY_PATTERNS: dict[str, dict[str, tuple[str, ...]]] = {
    "rally_exhaustion_exit_patterns": {
        "feature": ("exit_decision_quality", "winner_became_loser", "peak_bucket"),
        "report": ("winner-became-loser", "peak-bucket-report", "post-trade-learning"),
        "learning": ("exit_snapshot", "post_exit", "missed_lock"),
    },
    "heikin_ashi_trend_reversal": {
        "feature": ("heikin", "bar_pattern", "ema_8_21"),
        "report": ("bar-pattern", "symbol-patterns", "pattern-learning-inputs"),
        "learning": ("bar_pattern_features", "pattern_state"),
    },
    "implied_volatility_context": {
        "feature": ("implied_volatility", "iv_rank", "expected_move", "vix"),
        "report": ("event-context-validation", "feature-attribution"),
        "learning": ("volatility_normalization", "event_volatility"),
    },
    "algorithmic_trading_pipeline": {
        "feature": ("supervised_prediction_training", "prediction_validation", "shadow_prediction"),
        "report": ("learning-readiness", "shadow-predictions", "feature-attribution"),
        "learning": ("point_in_time", "candidate_outcome", "retraining"),
    },
    "news_expectations_positioning": {
        "feature": ("event_context", "source_reliability", "market_alignment"),
        "report": ("event-context-validation", "event-source-coverage"),
        "learning": ("event_attribution", "source_confirmation"),
    },
    "ipo_liquidity_restrictions": {
        "feature": ("s1_filing", "lockup", "blackout", "insider_supply"),
        "report": ("event-context-validation", "event-source-coverage"),
        "learning": ("peripheral", "official_disclosure", "event_context"),
    },
    "short_selling_risk": {
        "feature": ("short_interest", "borrow", "squeeze"),
        "report": ("portfolio-risk", "event-context-validation"),
        "learning": ("downside_asymmetry", "squeeze_risk"),
    },
}

BACKTEST_READINESS_CHECKS: tuple[dict[str, Any], ...] = (
    {
        "key": "point_in_time_archive",
        "label": "Point-in-time archive exists",
        "patterns": ("point_in_time_archive", "feature_available_at"),
    },
    {
        "key": "candidate_outcomes",
        "label": "Candidate/rejected forward outcomes exist",
        "patterns": ("candidate_outcome", "rejected_signal_outcomes"),
    },
    {
        "key": "shadow_predictions",
        "label": "Shadow model comparison path exists",
        "patterns": ("shadow_prediction", "shadow-predictions"),
    },
    {
        "key": "friction_model",
        "label": "Execution friction/slippage context exists",
        "patterns": ("slippage", "transaction_cost", "net_execution_cost"),
    },
    {
        "key": "promotion_governance",
        "label": "Promotion governance exists",
        "patterns": ("promotion", "rollout_contract", "readiness"),
    },
)


def _iter_project_files(base_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in base_dir.rglob("*"):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        rel_parts = path.relative_to(base_dir).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            continue
        files.append(path)
    return files


def _read_text(path: Path) -> str:
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return ""


def _project_text(base_dir: Path) -> tuple[str, dict[str, int]]:
    text_parts: list[str] = []
    file_hits: dict[str, int] = {}
    for path in _iter_project_files(base_dir):
        rel = str(path.relative_to(base_dir))
        text = _read_text(path).lower()
        if not text:
            continue
        text_parts.append(text)
        file_hits[rel] = len(text)
    return "\n".join(text_parts), file_hits


def _stored_concept_counts(repo: TradingEducationRepository) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in repo.recent_pages(limit=2000, stored_only=True):
        try:
            concept_keys = json.loads(row.get("concept_keys") or "[]")
        except Exception:
            concept_keys = []
        for key in concept_keys:
            counts[str(key)] += 1
    return counts


def _patterns_present(project_text: str, patterns: tuple[str, ...]) -> list[str]:
    return [pattern for pattern in patterns if pattern.lower() in project_text]


def build_trading_education_coverage_payload(
    *,
    base_dir: Path,
    repo: TradingEducationRepository | None = None,
) -> dict[str, Any]:
    repo = repo or TradingEducationRepository(base_dir / "trades.db")
    project_text, _ = _project_text(base_dir)
    stored_counts = _stored_concept_counts(repo)
    dependency_status = optional_dependency_status()

    concept_rows: list[dict[str, Any]] = []
    for concept in CURATED_TRADING_EDUCATION_CONCEPTS:
        concept_data = concept.to_dict()
        key = concept.key
        related_features = concept_data["related_features"]
        concept_refs = project_text.count(key.lower())
        feature_refs = sum(project_text.count(str(feature).lower()) for feature in related_features)
        stored_pages = int(stored_counts.get(key, 0))
        capability = CAPABILITY_PATTERNS.get(key, {})
        capability_rows = {}
        missing_capabilities = []
        for capability_key, patterns in capability.items():
            present = _patterns_present(project_text, patterns)
            capability_rows[capability_key] = {
                "present": bool(present),
                "matched_patterns": present,
                "expected_patterns": list(patterns),
            }
            if not present:
                missing_capabilities.append(capability_key)

        if stored_pages and feature_refs:
            status = "connected"
        elif stored_pages:
            status = "stored_only"
        elif feature_refs:
            status = "code_only"
        else:
            status = "taxonomy_only"

        concept_rows.append(
            {
                "key": key,
                "name": concept.name,
                "concept_type": concept.concept_type,
                "stored_pages": stored_pages,
                "concept_reference_count": concept_refs,
                "related_feature_reference_count": feature_refs,
                "coverage_status": status,
                "capabilities": capability_rows,
                "missing_capabilities": missing_capabilities,
                "influence_boundary": (
                    "advisory/explanation context only unless a separate promoted policy "
                    "explicitly consumes calibrated feature outcomes"
                ),
            }
        )

    dependency_rows = [
        {
            "package": package,
            "available": bool(dependency_status["packages"].get(package, {}).get("available")),
            "capability": dependency_status["packages"].get(package, {}).get("capability", "-"),
        }
        for package in QUANT_STACK_PACKAGES
    ]

    backtest_rows = []
    for check in BACKTEST_READINESS_CHECKS:
        present = _patterns_present(project_text, tuple(check["patterns"]))
        backtest_rows.append(
            {
                "key": check["key"],
                "label": check["label"],
                "present": bool(present),
                "matched_patterns": present,
                "expected_patterns": list(check["patterns"]),
            }
        )

    return {
        "report_version": TRADING_EDUCATION_COVERAGE_VERSION,
        "runtime_effect": TRADING_EDUCATION_RUNTIME_EFFECT,
        "decision_influence_policy": (
            "Education may shape AI explanation, diagnostics, and candidate recommendations; "
            "live approval/sizing/execution requires explicit promotion governance."
        ),
        "concept_count": len(concept_rows),
        "connected_count": sum(1 for row in concept_rows if row["coverage_status"] == "connected"),
        "stored_only_count": sum(1 for row in concept_rows if row["coverage_status"] == "stored_only"),
        "taxonomy_only_count": sum(1 for row in concept_rows if row["coverage_status"] == "taxonomy_only"),
        "concepts": concept_rows,
        "backtest_readiness": backtest_rows,
        "quant_stack_dependencies": dependency_rows,
    }
