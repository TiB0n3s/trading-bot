from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.ops_checks.external_symbol_discovery_checks import (
    EXTERNAL_SYMBOL_DISCOVERY_VERSION,
    build_external_symbol_discovery_payload,
    run_external_symbol_discovery,
)


def _init_db(base_dir: Path) -> None:
    con = sqlite3.connect(base_dir / "trades.db")
    con.execute(
        """
        CREATE TABLE daily_symbol_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            event_type TEXT,
            event_subtype TEXT,
            event_summary TEXT,
            source TEXT,
            source_url TEXT,
            expected_market_impact TEXT,
            trade_relevance TEXT,
            confidence TEXT,
            raw_json TEXT,
            created_at TEXT
        )
        """
    )
    con.commit()
    con.close()


def _insert_event(
    base_dir: Path,
    *,
    market_date: str = "2026-06-05",
    symbol: str,
    summary: str,
    source: str = "Reuters",
    event_type: str = "company_news",
    raw_json: dict | None = None,
) -> None:
    con = sqlite3.connect(base_dir / "trades.db")
    con.execute(
        """
        INSERT INTO daily_symbol_events (
            market_date, symbol, event_type, event_subtype, event_summary,
            source, source_url, expected_market_impact, trade_relevance,
            confidence, raw_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            market_date,
            symbol,
            event_type,
            None,
            summary,
            source,
            "https://www.reuters.com/markets/",
            "positive",
            "context",
            "medium",
            json.dumps(raw_json or {}),
            f"{market_date}T14:00:00Z",
        ),
    )
    con.commit()
    con.close()


def test_external_symbol_discovery_classifies_context_and_unknown_symbols():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        _init_db(base_dir)
        _insert_event(
            base_dir,
            symbol="MU",
            summary="Micron memory demand could affect NVDA AMD and TSM.",
            raw_json={"context_only": True, "linked_symbols": ["NVDA", "AMD", "TSM"]},
        )
        _insert_event(
            base_dir,
            symbol="XYZ",
            summary="Unknown external ticker XYZ appears in a reliable item linked to AAPL.",
            raw_json={"linked_symbols": ["AAPL"]},
        )
        _insert_event(
            base_dir,
            symbol="AAPL",
            summary="AAPL supplier context mentions MU memory demand.",
        )

        payload = build_external_symbol_discovery_payload(
            base_dir=base_dir,
            start_date="2026-06-05",
            min_mentions=1,
        )

        assert payload["report_version"] == EXTERNAL_SYMBOL_DISCOVERY_VERSION
        assert payload["status"] == "ok"
        by_symbol = {row["symbol"]: row for row in payload["findings"]}

        assert by_symbol["MU"]["symbol_class"] == "context_only"
        assert by_symbol["MU"]["recommendation"] == "review_context_weighting"
        assert {"AMD", "NVDA", "TSM"} <= set(by_symbol["MU"]["linked_approved_symbols"])
        assert by_symbol["MU"]["direct_event_rows"] == 1
        assert by_symbol["MU"]["approved_event_mentions"] == 1

        assert by_symbol["XYZ"]["symbol_class"] == "unknown_external"
        assert by_symbol["XYZ"]["recommendation"] == "review_for_context_or_approval"
        assert by_symbol["XYZ"]["linked_approved_symbols"] == ["AAPL"]


def test_external_symbol_discovery_no_findings_is_clean():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        _init_db(base_dir)
        _insert_event(base_dir, symbol="AAPL", summary="AAPL direct approved-universe event.")

        payload = build_external_symbol_discovery_payload(
            base_dir=base_dir,
            start_date="2026-06-05",
        )

        assert payload["status"] == "ok"
        assert payload["event_rows_scanned"] == 1
        assert payload["findings"] == []
        assert run_external_symbol_discovery(
            "2026-06-05",
            base_dir=base_dir,
        )


def main():
    test_external_symbol_discovery_classifies_context_and_unknown_symbols()
    test_external_symbol_discovery_no_findings_is_clean()
    print("external symbol discovery checks tests passed")


if __name__ == "__main__":
    main()
