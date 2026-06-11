"""Readiness inventory for optional VM resources.

This module does not import provider SDKs or connect to external services. It
only reports whether the VM has the credentials/packages needed to enable
resource adapters intentionally.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from typing import Any

RESOURCE_READINESS_VERSION = "vm_resource_readiness_v1"


@dataclass(frozen=True)
class ResourceSpec:
    key: str
    label: str
    category: str
    env_vars: tuple[str, ...] = ()
    packages: tuple[str, ...] = ()
    runtime_effect: str = "observe_only_until_explicitly_wired"
    next_action: str = ""


RESOURCE_SPECS: tuple[ResourceSpec, ...] = (
    ResourceSpec(
        key="alpaca_full_market_data",
        label="Alpaca full market data",
        category="market_data",
        env_vars=("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
        packages=("alpaca",),
        runtime_effect="existing_adapter_boundary",
        next_action=(
            "Confirm subscription/feed entitlement, monitor SIP/IEX fallback rate, "
            "and use live_bar_stream.py for observe-only closed-bar learning."
        ),
    ),
    ResourceSpec(
        key="polygon_market_data",
        label="Polygon/Massive independent market data",
        category="market_data",
        env_vars=("POLYGON_API_KEY",),
        packages=("requests",),
        next_action="Add adapter behind MarketDataService only after quote/bar parity checks pass.",
    ),
    ResourceSpec(
        key="databento_historical_market_data",
        label="Databento historical replay data",
        category="market_data_replay",
        env_vars=("DATABENTO_API_KEY",),
        packages=("databento",),
        next_action="Use for execution-cost replay and point-in-time historical validation.",
    ),
    ResourceSpec(
        key="sec_edgar_official_disclosures",
        label="SEC EDGAR official disclosures",
        category="official_disclosures",
        env_vars=("SEC_EDGAR_USER_AGENT",),
        packages=("requests",),
        next_action="Ingest filings as official-source events with company CIK mapping.",
    ),
    ResourceSpec(
        key="premium_news_provider",
        label="Premium/top-tier news API",
        category="event_context",
        env_vars=("NEWS_API_KEY",),
        packages=("requests",),
        next_action="Map provider output through source reliability before applying context.",
    ),
    ResourceSpec(
        key="anthropic_event_interpreter",
        label="Anthropic event intent interpreter",
        category="ai_interpretation",
        env_vars=("ANTHROPIC_API_KEY",),
        packages=("anthropic",),
        runtime_effect="context_only_no_live_authority",
        next_action="Use only for event intent summaries; keep source evidence deterministic.",
    ),
    ResourceSpec(
        key="local_llm_embeddings",
        label="Local embeddings/vector search",
        category="ai_retrieval",
        env_vars=(),
        packages=("sentence_transformers",),
        runtime_effect="research_and_similarity_only",
        next_action="Use for trade/event similarity retrieval outside the order path.",
    ),
    ResourceSpec(
        key="duckdb_research_exports",
        label="DuckDB research export layer",
        category="research_export",
        env_vars=(),
        packages=("duckdb",),
        runtime_effect="offline_analysis_only",
        next_action="Export lifecycle/candidate/parquet datasets for research workflows.",
    ),
    ResourceSpec(
        key="parquet_research_exports",
        label="Parquet research artifacts",
        category="research_export",
        env_vars=(),
        packages=("pyarrow",),
        runtime_effect="offline_analysis_only",
        next_action="Write immutable point-in-time datasets for replay-safe training.",
    ),
    ResourceSpec(
        key="prometheus_metrics",
        label="Prometheus/node-exporter style metrics",
        category="operations",
        env_vars=(),
        packages=("prometheus_client",),
        runtime_effect="observability_only",
        next_action="Expose job/runtime/freshness metrics after process-level collector is configured.",
    ),
)


def _env_status(names: tuple[str, ...], env: dict[str, str]) -> dict[str, Any]:
    present = [name for name in names if bool(env.get(name))]
    missing = [name for name in names if not env.get(name)]
    return {
        "required": list(names),
        "present": present,
        "missing": missing,
        "configured": not missing,
    }


def _package_status(names: tuple[str, ...]) -> dict[str, Any]:
    present = [name for name in names if importlib.util.find_spec(name) is not None]
    missing = [name for name in names if importlib.util.find_spec(name) is None]
    return {
        "required": list(names),
        "present": present,
        "missing": missing,
        "configured": not missing,
    }


def _resource_status(spec: ResourceSpec, env: dict[str, str]) -> dict[str, Any]:
    env_status = _env_status(spec.env_vars, env)
    package_status = _package_status(spec.packages)
    configured = env_status["configured"] and package_status["configured"]
    return {
        "key": spec.key,
        "label": spec.label,
        "category": spec.category,
        "status": "configured" if configured else "not_configured",
        "configured": configured,
        "env": env_status,
        "packages": package_status,
        "runtime_effect": spec.runtime_effect,
        "next_action": spec.next_action,
    }


def vm_resource_readiness(env: dict[str, str] | None = None) -> dict[str, Any]:
    env = env or os.environ
    resources = [_resource_status(spec, env) for spec in RESOURCE_SPECS]
    configured_count = sum(1 for row in resources if row["configured"])
    by_category: dict[str, dict[str, int]] = {}
    for row in resources:
        bucket = by_category.setdefault(row["category"], {"configured": 0, "total": 0})
        bucket["total"] += 1
        bucket["configured"] += int(row["configured"])
    return {
        "version": RESOURCE_READINESS_VERSION,
        "runtime_effect": "readiness_only_no_live_authority",
        "configured_count": configured_count,
        "total_count": len(resources),
        "by_category": by_category,
        "resources": resources,
    }
