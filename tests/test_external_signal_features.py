#!/usr/bin/env python3
"""Tests for point-in-time external signal features."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

from repositories.external_signal_feature_repo import (
    ExternalSignalFeature,
    ExternalSignalFeatureRepository,
    feature_from_mapping,
)

from scripts.analyze_ml_edge import EdgeRow
from scripts.external_signal_features import enrich_rows_with_external_features, main


def _edge_row(symbol: str = "AAPL", market_date: str = "2026-06-16") -> EdgeRow:
    return EdgeRow(
        source="test",
        symbol=symbol,
        market_date=market_date,
        decision="skip",
        score=None,
        confluence_score=None,
        conviction_score=None,
        setup_score=None,
        probability_pct=None,
        probability_source=None,
        instruction="none",
        instruction_class="unknown",
        forward_return_pct=1.0,
        forward_mfe_pct=None,
        numeric_features={},
        categorical_features={},
    )


def test_external_signal_feature_repo_upserts_and_filters_as_of(tmp_path):
    db_path = tmp_path / "features.db"
    repo = ExternalSignalFeatureRepository(db_path)

    changed = repo.upsert_many(
        [
            ExternalSignalFeature(
                symbol="AAPL",
                feature_ts="2026-06-15T21:00:00Z",
                available_at="2026-06-15T21:05:00Z",
                source="test_vendor",
                feature_family="earnings",
                feature_name="surprise_pct",
                feature_value_numeric=3.2,
            ),
            ExternalSignalFeature(
                symbol="AAPL",
                feature_ts="2026-06-17T21:00:00Z",
                available_at="2026-06-17T21:05:00Z",
                source="test_vendor",
                feature_family="earnings",
                feature_name="surprise_pct",
                feature_value_numeric=-9.0,
            ),
        ]
    )

    assert changed == 2
    as_of = repo.as_of_features(symbol="AAPL", decision_ts="2026-06-16T14:30:00Z")
    assert as_of["external.earnings.surprise_pct"]["feature_value_numeric"] == 3.2
    assert repo.leakage_violations() == 0


def test_feature_from_mapping_normalizes_value_aliases():
    feature = feature_from_mapping(
        {
            "symbol": "msft",
            "feature_ts": "2026-06-15T00:00:00Z",
            "available_at": "2026-06-16T00:00:00Z",
            "source": "public",
            "feature_family": "short_interest",
            "feature_name": "days_to_cover",
            "value": "2.5",
        }
    )

    assert feature.symbol == "MSFT"
    assert feature.feature_value_numeric == 2.5


def test_leakage_audit_allows_declared_scheduled_events(tmp_path):
    db_path = tmp_path / "features.db"
    repo = ExternalSignalFeatureRepository(db_path)

    repo.upsert_many(
        [
            ExternalSignalFeature(
                symbol="*",
                feature_ts="2026-06-17T18:00:00Z",
                available_at="2026-06-16T12:00:00Z",
                source="macro_calendar",
                feature_family="macro",
                feature_name="fomc_event_known",
                feature_value_numeric=1.0,
                revision_policy="scheduled_known_before_event",
            ),
            ExternalSignalFeature(
                symbol="AAPL",
                feature_ts="2026-06-17T21:00:00Z",
                available_at="2026-06-16T12:00:00Z",
                source="bad_vendor",
                feature_family="earnings",
                feature_name="surprise_pct",
                feature_value_numeric=5.0,
            ),
        ]
    )

    assert repo.leakage_violations() == 1


def test_enrich_rows_with_external_features_adds_prefixed_features(tmp_path):
    db_path = tmp_path / "features.db"
    repo = ExternalSignalFeatureRepository(db_path)
    repo.upsert_many(
        [
            ExternalSignalFeature(
                symbol="*",
                feature_ts="2026-06-15",
                available_at="2026-06-15",
                source="macro_calendar",
                feature_family="macro",
                feature_name="fomc_day",
                feature_value_numeric=1.0,
                feature_value_text="scheduled",
            )
        ]
    )

    enriched = enrich_rows_with_external_features([_edge_row()], repo)

    assert enriched[0].numeric_features["external.macro.fomc_day"] == 1.0
    assert enriched[0].categorical_features["external.macro.fomc_day"] == "scheduled"


def test_enrich_rows_uses_decision_timestamp_when_available(tmp_path):
    db_path = tmp_path / "features.db"
    repo = ExternalSignalFeatureRepository(db_path)
    repo.upsert_many(
        [
            ExternalSignalFeature(
                symbol="AAPL",
                feature_ts="2026-06-16T14:00:00Z",
                available_at="2026-06-16T14:30:00Z",
                source="event_feed",
                feature_family="news",
                feature_name="headline_count_30m",
                feature_value_numeric=3.0,
            )
        ]
    )

    early = replace(
        _edge_row(market_date="2026-06-16"),
        categorical_features={"decision_ts": "2026-06-16T14:00:00Z"},
    )
    late = replace(
        _edge_row(market_date="2026-06-16"),
        categorical_features={"decision_ts": "2026-06-16T14:31:00Z"},
    )

    enriched = enrich_rows_with_external_features([early, late], repo)

    assert "external.news.headline_count_30m" not in enriched[0].numeric_features
    assert enriched[1].numeric_features["external.news.headline_count_30m"] == 3.0


def test_external_signal_features_cli_ingests_jsonl(tmp_path):
    db_path = tmp_path / "features.db"
    input_path = tmp_path / "features.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "symbol": "AAPL",
                "feature_ts": "2026-06-15",
                "available_at": "2026-06-16",
                "source": "edgar",
                "feature_family": "filing",
                "feature_name": "new_8k",
                "value": 1,
            }
        )
        + "\n"
    )

    rc = main(["--db-path", str(db_path), "ingest-jsonl", "--input", str(input_path)])

    assert rc == 0
    with sqlite3.connect(db_path) as con:
        count = con.execute("SELECT COUNT(*) FROM external_signal_features").fetchone()[0]
    assert count == 1
