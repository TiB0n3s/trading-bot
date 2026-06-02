#!/usr/bin/env python3
"""Tests for SEC EDGAR official disclosure adapter."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.sec_edgar_service import SecEdgarService  # noqa: E402


def test_sec_recent_filings_filters_forms_and_marks_official():
    calls = []

    def transport(request):
        calls.append(request)
        return {
            "name": "Apple Inc.",
            "tickers": ["AAPL"],
            "filings": {
                "recent": {
                    "accessionNumber": ["a1", "a2", "a3"],
                    "form": ["10-K", "8-K", "4"],
                    "filingDate": ["2026-01-01", "2026-01-02", "2026-01-03"],
                    "reportDate": ["2025-12-31", "2026-01-02", "2026-01-03"],
                    "primaryDocument": ["a.htm", "b.htm", "c.htm"],
                }
            },
        }

    service = SecEdgarService(user_agent="trading-bot test@example.com", transport=transport)
    rows = service.recent_filings("320193", forms={"8-K", "4"}, limit=10)

    assert [row["form"] for row in rows] == ["8-K", "4"]
    assert rows[0]["source"] == "SEC EDGAR"
    assert rows[0]["source_tier"] == "official"
    assert rows[0]["trusted_source"] is True
    assert calls[0].path == "/submissions/CIK0000320193.json"
    assert calls[0].user_agent == "trading-bot test@example.com"


def test_sec_requires_user_agent_before_request():
    service = SecEdgarService(user_agent="", transport=lambda request: {})

    try:
        service.submissions("320193")
    except RuntimeError as exc:
        assert "SEC_EDGAR_USER_AGENT" in str(exc)
    else:
        raise AssertionError("expected missing user-agent error")


def main():
    tests = [
        test_sec_recent_filings_filters_forms_and_marks_official,
        test_sec_requires_user_agent_before_request,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} SEC EDGAR service tests passed.")


if __name__ == "__main__":
    main()
