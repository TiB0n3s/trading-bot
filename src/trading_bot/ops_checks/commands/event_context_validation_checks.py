"""Validate event-context inference against source reliability evidence."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from repositories.ops_check_repo import OpsCheckRepository

from market_intelligence.source_reliability import classify_source

TRUSTED_TIERS = {"official", "confirmed_financial_news", "deep_analysis"}
RUMOR_SENSITIVE_TYPES = {
    "mna_rumor",
    "deal_chatter",
    "supplier_signal",
    "customer_signal",
    "personnel_change",
    "leadership_change",
}
EVENT_CONTEXT_VALIDATION_REPORT_VERSION = "event_context_validation_v1"


def _load_json(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _tier(row: dict[str, Any], raw: dict[str, Any]) -> str:
    if raw.get("source_tier"):
        return str(raw["source_tier"])
    return str(classify_source(row.get("source"), url=row.get("source_url")).get("source_tier"))


def _impact(event: dict[str, Any], row: dict[str, Any]) -> str:
    return str(
        event.get("expected_market_impact")
        or row.get("expected_market_impact")
        or event.get("trade_relevance")
        or ""
    ).lower()


def run_event_context_validation(target_date: str, *, base_dir: Path) -> bool:
    print()
    print("=" * 72)
    print(f"  Event Context Validation - {target_date}")
    print("=" * 72)
    print(f"report_version          : {EVENT_CONTEXT_VALIDATION_REPORT_VERSION}")

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    repo = OpsCheckRepository(db_path)
    rows = [dict(row) for row in repo.event_source_rows(target_date)]
    if not rows:
        print("[WARN] no daily_symbol_events rows found")
        return False

    counts: Counter[str] = Counter()
    flagged: list[dict[str, Any]] = []

    for row in rows:
        raw = _load_json(row.get("raw_json"))
        tier = _tier(row, raw)
        trusted = tier in TRUSTED_TIERS or bool(raw.get("trusted_source"))
        event_type = str(row.get("event_type") or raw.get("event_type") or "unknown")
        impact = _impact(raw, row)
        reason = str(raw.get("scoring_reason") or raw.get("reason") or "")
        peripheral = (
            bool(raw.get("peripheral_context")) or raw.get("search_scope") == "company_peripheral"
        )

        counts["rows"] += 1
        counts[f"tier:{tier}"] += 1
        counts["trusted"] += int(trusted)
        counts["peripheral"] += int(peripheral)

        bullish = any(token in impact for token in ("bullish", "positive", "upside", "strong"))
        rumor_sensitive = event_type in RUMOR_SENSITIVE_TYPES or peripheral
        issue = None
        if bullish and not trusted:
            issue = "bullish_inference_without_trusted_source"
        elif rumor_sensitive and not trusted:
            issue = "peripheral_or_rumor_sensitive_unconfirmed"
        elif tier == "unclassified":
            issue = "unclassified_source"
        elif "capped" in reason.lower() and trusted:
            issue = "trusted_source_but_inference_was_capped"

        if issue:
            counts[f"issue:{issue}"] += 1
            flagged.append(
                {
                    "symbol": row.get("symbol"),
                    "event_type": event_type,
                    "source": row.get("source"),
                    "tier": tier,
                    "impact": impact or "-",
                    "issue": issue,
                    "summary": str(raw.get("event_summary") or row.get("event_summary") or "")[:80],
                }
            )

    trusted_rate = counts["trusted"] / counts["rows"] * 100.0 if counts["rows"] else 0.0
    issue_count = sum(count for key, count in counts.items() if key.startswith("issue:"))
    issue_rate = issue_count / counts["rows"] * 100.0 if counts["rows"] else 0.0

    print(f"events             : {counts['rows']}")
    print(f"trusted_rate       : {trusted_rate:.1f}%")
    print(f"peripheral_events  : {counts['peripheral']}")
    print(f"validation_issues  : {issue_count}")
    print(f"issue_rate         : {issue_rate:.1f}%")

    print()
    print("Source tiers")
    for key, count in sorted(
        ((key[5:], value) for key, value in counts.items() if key.startswith("tier:")),
        key=lambda item: (-item[1], item[0]),
    ):
        print(f"  {key:<28} {count:>5}")

    print()
    print("Validation issue counts")
    issue_rows = [(key[6:], value) for key, value in counts.items() if key.startswith("issue:")]
    if issue_rows:
        for key, count in sorted(issue_rows, key=lambda item: (-item[1], item[0])):
            print(f"  {key:<42} {count:>5}")
    else:
        print("  none")

    if flagged:
        print()
        print("Flagged event-context rows")
        for item in flagged[:20]:
            print(
                f"  {str(item['symbol'] or '-'):<6} {item['tier']:<28} "
                f"{item['issue']:<42} {str(item['source'] or '-'):<22} "
                f"{item['event_type']}: {item['summary']}"
            )

    ok = issue_rate < 25.0
    print()
    print(
        "[OK] event context validation passed review threshold"
        if ok
        else "[WARN] event context validation found inference/source issues"
    )
    return ok
