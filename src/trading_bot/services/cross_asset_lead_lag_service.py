"""Cross-asset lead ticker mapping for observe-only ensemble research."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

from symbols_config import APPROVED_SYMBOLS_LIST, SYMBOL_CONFIG

CROSS_ASSET_LEAD_MAP_VERSION = "cross_asset_lead_map_v1"
CROSS_ASSET_RUNTIME_EFFECT = "research_mapping_only_no_live_authority"

BROAD_MARKET_LEADS = ("SPY", "QQQ", "IWM")
CLUSTER_LEADS = {
    "mega_cap_tech": ("QQQ", "XLK", "SPY"),
    "ai_infra": ("QQQ", "XLK", "SMH"),
    "semiconductors": ("SMH", "QQQ", "XLK"),
    "software_infra": ("IGV", "QQQ", "XLK"),
    "hardware_infra": ("QQQ", "XLK", "SMH"),
    "cybersecurity": ("HACK", "IGV", "QQQ"),
    "consumer": ("XLY", "SPY"),
    "consumer_growth": ("XLY", "QQQ", "SPY"),
    "energy": ("XLE", "SPY"),
    "power_energy": ("XLU", "XLE", "SPY"),
    "industrials": ("XLI", "SPY"),
    "aerospace": ("ITA", "XLI", "SPY"),
    "defense": ("ITA", "XLI", "SPY"),
    "healthcare": ("XLV", "IBB", "SPY"),
    "payments": ("XLF", "SPY", "QQQ"),
    "financials": ("XLF", "SPY", "IWM"),
    "telecom": ("XLC", "SPY"),
    "defensive": ("SPLV", "SPY"),
    "hedge": ("GLD", "TLT", "SPY"),
    "broad_index": ("SPY", "QQQ", "IWM"),
}


@dataclass(frozen=True)
class CrossAssetLeadRow:
    symbol: str
    clusters: list[str]
    lead_tickers: list[str]
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CrossAssetLeadMapPayload:
    report_version: str
    runtime_effect: str
    symbol_count: int
    default_leads: list[str]
    rows: list[CrossAssetLeadRow]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "runtime_effect": self.runtime_effect,
            "symbol_count": self.symbol_count,
            "default_leads": self.default_leads,
            "rows": [row.to_dict() for row in self.rows],
            "summary": self.summary,
        }


def _csv(value: str | None) -> list[str]:
    return [item.strip().upper() for item in str(value or "").split(",") if item.strip()]


def _unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        item = value.upper()
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def build_cross_asset_lead_map(
    *,
    env: dict[str, str] | None = None,
    symbols: list[str] | None = None,
) -> CrossAssetLeadMapPayload:
    env = dict(os.environ if env is None else env)
    default_leads = _unique(
        _csv(env.get("ETF_LEAD_LAG_REFERENCE_SYMBOLS")) or list(BROAD_MARKET_LEADS)
    )
    target_symbols = [symbol.upper() for symbol in (symbols or APPROVED_SYMBOLS_LIST)]
    rows: list[CrossAssetLeadRow] = []
    missing_cluster_symbols = []
    lead_usage: dict[str, int] = {}

    for symbol in target_symbols:
        config = SYMBOL_CONFIG.get(symbol) or {}
        clusters = [str(item) for item in config.get("clusters", [])]
        if not clusters:
            missing_cluster_symbols.append(symbol)
        leads = list(default_leads)
        for cluster in clusters:
            leads.extend(CLUSTER_LEADS.get(cluster, ()))
        leads = [lead for lead in _unique(leads) if lead != symbol]
        for lead in leads:
            lead_usage[lead] = lead_usage.get(lead, 0) + 1
        rows.append(
            CrossAssetLeadRow(
                symbol=symbol,
                clusters=clusters,
                lead_tickers=leads,
                source="symbol_cluster_mapping_with_env_override",
            )
        )

    return CrossAssetLeadMapPayload(
        report_version=CROSS_ASSET_LEAD_MAP_VERSION,
        runtime_effect=CROSS_ASSET_RUNTIME_EFFECT,
        symbol_count=len(rows),
        default_leads=default_leads,
        rows=rows,
        summary={
            "unique_leads": sorted(lead_usage),
            "lead_usage": dict(sorted(lead_usage.items())),
            "missing_cluster_symbols": missing_cluster_symbols,
            "transformer_authority": "not_granted",
            "intended_use": "ensemble_input_feature_and_shadow_research",
        },
    )
