#!/usr/bin/env python3
"""Ingest approved trading education sources into compact concept metadata."""

from __future__ import annotations

import argparse
import json

from services.trading_education_corpus_service import TradingEducationIngestionService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, default=12)
    parser.add_argument("--no-follow", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    service = TradingEducationIngestionService()
    result = service.ingest(
        max_pages=max(1, int(args.max_pages)),
        follow_links=not args.no_follow,
        dry_run=bool(args.dry_run),
    )

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("Trading education ingestion")
        print(f"  report_version : {result['report_version']}")
        print(f"  corpus_version : {result['corpus_version']}")
        print(f"  runtime_effect : {result['runtime_effect']}")
        print(f"  dry_run        : {result['dry_run']}")
        print(f"  visited        : {result['visited']}")
        print(f"  stored         : {result['stored']}")
        print(f"  failed         : {result['failed']}")
        for page in result["pages"]:
            suffix = f" error={page.get('error')}" if page.get("error") else ""
            print(f"  - {page['status']:<12} {page['source_key']:<28} {page['url']}{suffix}")

    return 0 if result["stored"] > 0 or result["dry_run"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
