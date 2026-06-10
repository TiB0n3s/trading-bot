"""External-symbol discovery report for event intelligence."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from repositories.external_symbol_discovery_repo import ExternalSymbolDiscoveryRepository
from symbols_config import (
    APPROVED_SYMBOLS,
    CONTEXT_ONLY_SYMBOL_CONFIG,
    CONTEXT_ONLY_SYMBOLS,
)

from market_intelligence.source_reliability import classify_source

EXTERNAL_SYMBOL_DISCOVERY_VERSION = "external_symbol_discovery_v1"
TOKEN_RE = re.compile(r"\b[A-Z]{2,5}\b")


def _load_json(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).upper().strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.upper().strip()]
    return []


def _linked_approved_symbols(symbol: str, raw: dict[str, Any], text: str) -> list[str]:
    linked = set()
    if symbol in CONTEXT_ONLY_SYMBOL_CONFIG:
        linked.update(CONTEXT_ONLY_SYMBOL_CONFIG[symbol].get("linked_symbols") or [])
    linked.update(_json_list(raw.get("linked_symbols")))
    linked.update(_json_list(raw.get("approved_symbols")))
    linked.update(TOKEN_RE.findall(text or ""))
    return sorted(sym for sym in linked if sym in APPROVED_SYMBOLS)


def _context_mentions(text: str) -> set[str]:
    tokens = set(TOKEN_RE.findall(text or ""))
    return tokens & CONTEXT_ONLY_SYMBOLS


def _event_text(row: dict[str, Any], raw: dict[str, Any]) -> str:
    pieces = [
        row.get("event_summary"),
        row.get("event_type"),
        row.get("event_subtype"),
        raw.get("event_summary"),
        raw.get("title"),
        raw.get("summary"),
        raw.get("headline"),
        " ".join(_json_list(raw.get("linked_symbols"))),
        " ".join(_json_list(raw.get("symbols"))),
    ]
    return " ".join(str(piece) for piece in pieces if piece)


def _recommendation(
    *,
    symbol_class: str,
    mentions: int,
    trusted_mentions: int,
    linked_count: int,
    min_mentions: int,
) -> str:
    if symbol_class == "context_only":
        if mentions >= min_mentions and linked_count > 0:
            return "review_context_weighting"
        return "keep_context_only"
    if trusted_mentions >= min_mentions or (mentions >= min_mentions and linked_count > 0):
        return "review_for_context_or_approval"
    return "ignore_or_keep_watch"


def build_external_symbol_discovery_payload(
    *,
    base_dir: Path,
    start_date: str,
    end_date: str | None = None,
    min_mentions: int = 2,
    limit: int = 12,
) -> dict[str, Any]:
    end_date = end_date or start_date
    db_path = base_dir / "trades.db"
    repo_payload = ExternalSymbolDiscoveryRepository(db_path).daily_symbol_event_rows(
        start_date=start_date,
        end_date=end_date,
    )
    if repo_payload["status"] == "missing_db":
        return {
            "report_version": EXTERNAL_SYMBOL_DISCOVERY_VERSION,
            "status": "missing_db",
            "db_path": str(db_path),
            "start_date": start_date,
            "end_date": end_date,
            "findings": [],
        }

    if repo_payload["status"] == "missing_table":
        return {
            "report_version": EXTERNAL_SYMBOL_DISCOVERY_VERSION,
            "status": "missing_table",
            "start_date": start_date,
            "end_date": end_date,
            "findings": [],
        }

    rows = list(repo_payload.get("rows") or [])

    findings: dict[str, dict[str, Any]] = {}
    mention_sources: defaultdict[str, Counter[str]] = defaultdict(Counter)

    def ensure(symbol: str) -> dict[str, Any]:
        symbol = symbol.upper().strip()
        if symbol not in findings:
            symbol_class = "context_only" if symbol in CONTEXT_ONLY_SYMBOLS else "unknown_external"
            findings[symbol] = {
                "symbol": symbol,
                "symbol_class": symbol_class,
                "direct_event_rows": 0,
                "approved_event_mentions": 0,
                "trusted_mentions": 0,
                "source_tiers": Counter(),
                "sources": Counter(),
                "event_types": Counter(),
                "impact_counts": Counter(),
                "relevance_counts": Counter(),
                "confidence_counts": Counter(),
                "linked_approved_symbols": set(),
                "examples": [],
            }
        return findings[symbol]

    for row in rows:
        symbol = str(row.get("symbol") or "").upper().strip()
        raw = _load_json(row.get("raw_json"))
        text = _event_text(row, raw)
        policy = classify_source(row.get("source"), url=row.get("source_url"))
        tier = str(raw.get("source_tier") or policy.get("source_tier") or "unclassified")
        trusted = bool(raw.get("trusted_source")) or tier in {
            "official",
            "confirmed_financial_news",
            "deep_analysis",
        }

        symbols_to_credit: set[str] = set()
        direct_external = symbol and symbol not in APPROVED_SYMBOLS
        if direct_external:
            symbols_to_credit.add(symbol)
        for mentioned in _context_mentions(text):
            if symbol in APPROVED_SYMBOLS or mentioned != symbol:
                symbols_to_credit.add(mentioned)

        for ext_symbol in symbols_to_credit:
            finding = ensure(ext_symbol)
            if ext_symbol == symbol and direct_external:
                finding["direct_event_rows"] += 1
            else:
                finding["approved_event_mentions"] += 1
            finding["trusted_mentions"] += int(trusted)
            finding["source_tiers"][tier] += 1
            finding["sources"][str(row.get("source") or raw.get("source_name") or "unknown")] += 1
            finding["event_types"][str(row.get("event_type") or "unknown")] += 1
            finding["impact_counts"][str(row.get("expected_market_impact") or "unknown")] += 1
            finding["relevance_counts"][str(row.get("trade_relevance") or "unknown")] += 1
            finding["confidence_counts"][str(row.get("confidence") or "unknown")] += 1
            finding["linked_approved_symbols"].update(
                _linked_approved_symbols(ext_symbol, raw, text)
            )
            if len(finding["examples"]) < 3:
                finding["examples"].append(
                    {
                        "market_date": row.get("market_date"),
                        "source": row.get("source") or "unknown",
                        "source_tier": tier,
                        "event_type": row.get("event_type") or "unknown",
                        "summary": str(row.get("event_summary") or raw.get("event_summary") or "")[
                            :160
                        ],
                    }
                )
            mention_sources[ext_symbol][symbol or "unknown"] += 1

    normalized: list[dict[str, Any]] = []
    for symbol, finding in findings.items():
        mentions = int(finding["direct_event_rows"] + finding["approved_event_mentions"])
        linked = sorted(finding["linked_approved_symbols"])
        normalized.append(
            {
                "symbol": symbol,
                "symbol_class": finding["symbol_class"],
                "mentions": mentions,
                "direct_event_rows": int(finding["direct_event_rows"]),
                "approved_event_mentions": int(finding["approved_event_mentions"]),
                "trusted_mentions": int(finding["trusted_mentions"]),
                "linked_approved_symbols": linked,
                "recommendation": _recommendation(
                    symbol_class=finding["symbol_class"],
                    mentions=mentions,
                    trusted_mentions=int(finding["trusted_mentions"]),
                    linked_count=len(linked),
                    min_mentions=min_mentions,
                ),
                "source_tiers": dict(finding["source_tiers"].most_common()),
                "top_sources": dict(finding["sources"].most_common(5)),
                "event_types": dict(finding["event_types"].most_common(5)),
                "impact_counts": dict(finding["impact_counts"].most_common(5)),
                "relevance_counts": dict(finding["relevance_counts"].most_common(5)),
                "confidence_counts": dict(finding["confidence_counts"].most_common(5)),
                "observed_under_symbols": dict(mention_sources[symbol].most_common(8)),
                "examples": finding["examples"],
            }
        )

    normalized.sort(
        key=lambda item: (
            item["recommendation"] != "review_for_context_or_approval",
            item["recommendation"] != "review_context_weighting",
            -item["mentions"],
            item["symbol"],
        )
    )

    return {
        "report_version": EXTERNAL_SYMBOL_DISCOVERY_VERSION,
        "status": "ok",
        "start_date": start_date,
        "end_date": end_date,
        "event_rows_scanned": len(rows),
        "external_symbol_count": len(normalized),
        "min_mentions": min_mentions,
        "findings": normalized[: max(1, limit)],
        "truncated": len(normalized) > limit,
    }


def run_external_symbol_discovery(
    start_date: str,
    *,
    base_dir: Path,
    end_date: str | None = None,
    min_mentions: int = 2,
    limit: int = 12,
) -> bool:
    payload = build_external_symbol_discovery_payload(
        base_dir=base_dir,
        start_date=start_date,
        end_date=end_date,
        min_mentions=min_mentions,
        limit=limit,
    )

    print()
    print("=" * 72)
    print(f"  External Symbol Discovery - {payload['start_date']}..{payload['end_date']}")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"status                  : {payload['status']}")

    if payload["status"] != "ok":
        print(f"[WARN] external symbol discovery unavailable: {payload['status']}")
        if payload.get("db_path"):
            print(f"db_path                 : {payload['db_path']}")
        return False

    print(f"event_rows_scanned      : {payload['event_rows_scanned']}")
    print(f"external_symbol_count   : {payload['external_symbol_count']}")
    print(f"min_mentions            : {payload['min_mentions']}")

    findings = payload["findings"]
    if not findings:
        print()
        print("[OK] no non-approved symbol references found in event context")
        return True

    print()
    print("External symbols")
    print("  symbol class             mentions trusted action")
    print("  " + "-" * 62)
    for item in findings:
        print(
            f"  {item['symbol']:<6} {item['symbol_class']:<17} "
            f"{item['mentions']:>8} {item['trusted_mentions']:>7} {item['recommendation']}"
        )
        linked = ", ".join(item["linked_approved_symbols"]) or "-"
        sources = ", ".join(f"{name}:{count}" for name, count in item["top_sources"].items()) or "-"
        tiers = ", ".join(f"{name}:{count}" for name, count in item["source_tiers"].items()) or "-"
        print(f"         linked approved : {linked}")
        print(f"         source tiers    : {tiers}")
        print(f"         top sources     : {sources}")
        if item["examples"]:
            example = item["examples"][0]
            print(
                f"         example         : {example['market_date']} {example['source']} - {example['summary']}"
            )

    if payload.get("truncated"):
        print()
        print(
            f"[WARN] output truncated to top {len(findings)} symbols; increase --limit to inspect more"
        )

    review_count = sum(
        1
        for item in findings
        if item["recommendation"] in {"review_context_weighting", "review_for_context_or_approval"}
    )
    print()
    if review_count:
        print(f"[WARN] {review_count} external symbol(s) need review before any universe change")
    else:
        print("[OK] external symbols remain context-only/watch-only")
    return True
