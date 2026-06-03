"""Operator report for curated trading-education source policy."""

from __future__ import annotations

from services.trading_education_corpus_service import build_trading_education_health_payload


def run_trading_education_health() -> bool:
    payload = build_trading_education_health_payload()

    print()
    print("=" * 72)
    print("  Trading Education Source Health")
    print("=" * 72)
    print(f"report_version      : {payload['report_version']}")
    print(f"corpus_version      : {payload['corpus_version']}")
    print(f"runtime_effect      : {payload['runtime_effect']}")
    print(f"authority_ready     : {payload['authority_ready']}")
    print(f"authority_note      : {payload['authority_note']}")
    print(f"source_count        : {payload['source_count']}")
    print(f"concept_count       : {payload['concept_count']}")
    print(f"approved_seed_count : {payload['approved_seed_count']}")
    print(f"metadata/manual     : {payload['metadata_or_manual_count']}")

    print()
    print("Approved crawl domains")
    for domain in payload["approved_domains"]:
        print(f"  - {domain}")

    print()
    print("Source status counts")
    for status, count in payload["by_status"].items():
        print(f"  {status:<24} {count:>4}")

    print()
    print("Curated sources")
    print(f"  {'key':<34} {'tier':<22} {'status':<22} {'follow':<18}")
    print(f"  {'-' * 34} {'-' * 22} {'-' * 22} {'-' * 18}")
    for source in payload["sources"]:
        print(
            f"  {source['key']:<34} "
            f"{source['tier']:<22} "
            f"{source['ingestion_status']:<22} "
            f"{source['link_follow_policy']:<18}"
        )

    print()
    print("Curated education concepts")
    print(f"  {'key':<28} {'type':<20} {'authority':<24}")
    print(f"  {'-' * 28} {'-' * 20} {'-' * 24}")
    for concept in payload["concepts"]:
        print(
            f"  {concept['key']:<28} "
            f"{concept['concept_type']:<20} "
            f"{concept['live_authority']:<24}"
        )

    print()
    print("[OK] trading education sources are curated; no live authority changed")
    return True
