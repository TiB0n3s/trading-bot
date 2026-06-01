"""Event source coverage report for collected market intelligence."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any

from market_intelligence.source_reliability import classify_source
from repositories.ops_check_repo import OpsCheckRepository


TRUSTED_TIERS = {"official", "confirmed_financial_news", "deep_analysis"}
TIER_BUCKETS = {
    "official": "official",
    "confirmed_financial_news": "top_tier",
    "deep_analysis": "top_tier",
    "medium_confidence": "medium",
    "low_confidence": "low",
    "unclassified": "unclassified",
}
EVENT_SOURCE_COVERAGE_REPORT_VERSION = "event_source_coverage_v1"


def _raw(row: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(row.get("raw_json") or "{}")
    except Exception:
        return {}


def _source_policy(row: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("source_tier"):
        return {
            "source_tier": raw.get("source_tier"),
            "source_reliability": raw.get("source_reliability"),
            "trusted_source": bool(raw.get("trusted_source")),
            "source_name": raw.get("source_name") or row.get("source") or "unknown",
        }
    return classify_source(row.get("source"), url=row.get("source_url"))


def _confirmation_status(raw: dict[str, Any], tier: str, trusted: bool) -> str:
    explicit = raw.get("confirmation_status") or raw.get("confirmation")
    if explicit:
        return str(explicit)
    if tier == "official":
        return "official_confirmed"
    if trusted:
        return "trusted_source_confirmed"
    if tier in {"medium_confidence", "low_confidence", "unclassified"}:
        return "unconfirmed_or_needs_review"
    return "unknown"


def run_event_source_coverage(target_date: str, *, base_dir: Path) -> bool:
    db_path = base_dir / "trades.db"
    repo = OpsCheckRepository(db_path)

    print()
    print("=" * 72)
    print(f"  Event Source Coverage - {target_date}")
    print("=" * 72)
    print(f"report_version          : {EVENT_SOURCE_COVERAGE_REPORT_VERSION}")

    if not repo.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    rows = [dict(row) for row in repo.event_source_rows(target_date)]
    if not rows:
        print("[WARN] no daily_symbol_events rows found for this date")
        return False

    tier_counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    scope_counts: Counter[str] = Counter()
    confirmation_counts: Counter[str] = Counter()
    trusted_count = 0

    for row in rows:
        raw = _raw(row)
        policy = _source_policy(row, raw)
        tier = str(policy.get("source_tier") or "unclassified")
        trusted = bool(policy.get("trusted_source")) or tier in TRUSTED_TIERS
        source_name = str(policy.get("source_name") or row.get("source") or "unknown")
        search_scope = str(raw.get("search_scope") or "unknown")
        peripheral = bool(raw.get("peripheral_context")) or search_scope == "company_peripheral"

        tier_counts[tier] += 1
        bucket_counts[TIER_BUCKETS.get(tier, "unclassified")] += 1
        source_counts[source_name] += 1
        scope_counts["peripheral"] += int(peripheral)
        scope_counts["direct"] += int(not peripheral)
        confirmation_counts[_confirmation_status(raw, tier, trusted)] += 1
        trusted_count += int(trusted)

    total = len(rows)
    trusted_rate = trusted_count / total * 100.0 if total else 0.0
    unclassified_rate = bucket_counts["unclassified"] / total * 100.0 if total else 0.0

    print(f"events                 : {total}")
    print(f"trusted_source_count   : {trusted_count}")
    print(f"trusted_source_rate    : {trusted_rate:.1f}%")
    print(f"unclassified_rate      : {unclassified_rate:.1f}%")

    print()
    print("Reliability buckets")
    for key in ("official", "top_tier", "medium", "low", "unclassified"):
        print(f"  {key:<16} {bucket_counts[key]:>5}")

    print()
    print("Source tiers")
    for tier, count in sorted(tier_counts.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {tier:<28} {count:>5}")

    print()
    print("Direct vs peripheral")
    for key in ("direct", "peripheral"):
        print(f"  {key:<16} {scope_counts[key]:>5}")

    print()
    print("Confirmation status")
    for status, count in sorted(confirmation_counts.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {status:<32} {count:>5}")

    print()
    print("Top sources")
    for source, count in source_counts.most_common(12):
        print(f"  {source:<32} {count:>5}")

    ok = trusted_count > 0 and unclassified_rate < 50.0
    print()
    print("[OK] event source coverage has trusted coverage" if ok else "[WARN] event source coverage needs review")
    return ok
