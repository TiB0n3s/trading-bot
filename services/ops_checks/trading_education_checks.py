"""Operator report for curated trading-education source policy."""

from __future__ import annotations

from pathlib import Path

from repositories.trading_education_repo import TradingEducationRepository
from services.trading_education_corpus_service import build_trading_education_health_payload
from services.trading_education_coverage_service import build_trading_education_coverage_payload


def run_trading_education_health(*, base_dir: Path | None = None) -> bool:
    payload = build_trading_education_health_payload()
    repo = TradingEducationRepository(base_dir / "trades.db") if base_dir else TradingEducationRepository()
    stored = repo.summary()

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
    print(f"stored_pages        : {stored['stored']}")
    print(f"needs_review        : {stored['needs_review']}")
    print(f"failed_pages        : {stored['failed']}")
    print(f"avg_confidence      : {stored['avg_confidence']:.2f}")
    print(f"latest_retrieved_at : {stored['latest_retrieved_at'] or '-'}")

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

    if stored["by_source"]:
        print()
        print("Stored education pages by source")
        print(f"  {'source':<34} {'status':<14} {'rows':>5} {'latest'}")
        print(f"  {'-' * 34} {'-' * 14} {'-' * 5} {'-' * 20}")
        for row in stored["by_source"]:
            print(
                f"  {row['source_key']:<34} "
                f"{row['status']:<14} "
                f"{int(row['rows'] or 0):>5} "
                f"{row['latest_retrieved_at'] or '-'}"
            )

    recent = repo.recent_pages(limit=8, stored_only=True)
    if recent:
        print()
        print("Recent stored concept cards")
        for row in recent:
            print(
                f"  {row['source_key']:<28} {row['status']:<12} "
                f"{str(row['concept_keys'] or '[]')[:54]:<54} "
                f"{str(row['title'] or '-')[:70]}"
            )

    print()
    print("[OK] trading education sources are curated; no live authority changed")
    return True


def run_trading_education_review(*, base_dir: Path | None = None) -> bool:
    repo = TradingEducationRepository(base_dir / "trades.db") if base_dir else TradingEducationRepository()
    summary = repo.summary()
    rows = repo.review_rows(limit=30)

    print()
    print("=" * 72)
    print("  Trading Education Extraction Review")
    print("=" * 72)
    print("report_version      : trading_education_review_v1")
    print("runtime_effect      : education_context_only_no_trade_authority")
    print(f"stored_pages        : {summary['stored']}")
    print(f"needs_review        : {summary['needs_review']}")
    print(f"failed_pages        : {summary['failed']}")
    print(f"avg_confidence      : {summary['avg_confidence']:.2f}")

    if not rows:
        print()
        print("[OK] no trading education extraction rows require review")
        return True

    print()
    print("Rows requiring review")
    print(f"  {'source':<28} {'status':<14} {'conf':>5} {'method':<16} {'warning/error'}")
    print(f"  {'-' * 28} {'-' * 14} {'-' * 5} {'-' * 16} {'-' * 40}")
    for row in rows:
        warnings = row.get("extraction_warnings") or row.get("error") or "-"
        print(
            f"  {str(row.get('source_key') or '-'):<28} "
            f"{str(row.get('status') or '-'):<14} "
            f"{float(row.get('extraction_confidence') or 0.0):>5.2f} "
            f"{str(row.get('ingestion_method') or '-'):<16} "
            f"{str(warnings)[:90]}"
        )
        print(f"    {row.get('url')}")

    print()
    print("[WARN] trading education extraction has rows requiring review")
    return False


def run_trading_education_coverage(*, base_dir: Path) -> bool:
    payload = build_trading_education_coverage_payload(base_dir=base_dir)

    print()
    print("=" * 72)
    print("  Trading Education Coverage")
    print("=" * 72)
    print(f"report_version       : {payload['report_version']}")
    print(f"runtime_effect       : {payload['runtime_effect']}")
    print(f"decision_policy      : {payload['decision_influence_policy']}")
    print(f"concept_count        : {payload['concept_count']}")
    print(f"connected_count      : {payload['connected_count']}")
    print(f"stored_only_count    : {payload['stored_only_count']}")
    print(f"taxonomy_only_count  : {payload['taxonomy_only_count']}")

    print()
    print("Concept coverage")
    print(
        f"  {'concept':<32} {'status':<14} {'stored':>6} {'refs':>5} "
        f"{'feature_refs':>12} {'missing_capabilities'}"
    )
    print(
        f"  {'-' * 32} {'-' * 14} {'-' * 6} {'-' * 5} "
        f"{'-' * 12} {'-' * 28}"
    )
    for row in payload["concepts"]:
        missing = ",".join(row["missing_capabilities"]) if row["missing_capabilities"] else "-"
        print(
            f"  {row['key']:<32} {row['coverage_status']:<14} "
            f"{row['stored_pages']:>6} {row['concept_reference_count']:>5} "
            f"{row['related_feature_reference_count']:>12} {missing}"
        )

    print()
    print("Backtesting readiness")
    for row in payload["backtest_readiness"]:
        status = "present" if row["present"] else "missing"
        matched = ", ".join(row["matched_patterns"]) if row["matched_patterns"] else "-"
        print(f"  {row['key']:<28} {status:<8} {matched}")

    print()
    print("Quant-stack dependencies")
    for row in payload["quant_stack_dependencies"]:
        status = "available" if row["available"] else "missing"
        print(f"  {row['package']:<14} {status:<10} {row['capability']}")

    print()
    print("[OK] trading education coverage completed; no live authority changed")
    return True
