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
    parser.add_argument("--manual-file", help="Ingest an operator-provided HTML/text snapshot")
    parser.add_argument("--url", help="Approved source URL for --manual-file")
    parser.add_argument("--title", help="Optional title override for --manual-file")
    args = parser.parse_args(argv)

    service = TradingEducationIngestionService()
    if args.manual_file:
        if not args.url:
            parser.error("--manual-file requires --url")
        result = service.ingest_manual_file(
            url=args.url,
            path=args.manual_file,
            title=args.title,
            dry_run=bool(args.dry_run),
        )
    else:
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
        if "visited" in result:
            print(f"  visited        : {result['visited']}")
            print(f"  stored         : {result['stored']}")
            print(f"  needs_review   : {result.get('needs_review', 0)}")
            print(f"  failed         : {result['failed']}")
            for page in result["pages"]:
                suffix = f" error={page.get('error')}" if page.get("error") else ""
                print(f"  - {page['status']:<12} {page['source_key']:<28} {page['url']}{suffix}")
        else:
            print(f"  status         : {result['status']}")
            print(f"  url            : {result['url']}")
            print(f"  source_key     : {result.get('source_key', '-')}")
            print(f"  title          : {result.get('title', '-')}")
            print(f"  confidence     : {result.get('extraction_confidence', '-')}")
            print(f"  warnings       : {result.get('extraction_warnings', [])}")
            print(f"  concepts       : {result.get('concept_keys', [])}")

    if args.manual_file:
        return 0 if result["status"] in {"stored", "needs_review"} or result["dry_run"] else 1
    return 0 if result["stored"] > 0 or result.get("needs_review", 0) > 0 or result["dry_run"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
