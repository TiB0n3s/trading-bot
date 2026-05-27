#!/usr/bin/env python3
"""
setup_engine.py

Rule-based observe-only setup classifier for the trading bot.

Purpose:
- Convert feature snapshots into explicit setup labels
- Encode the strongest / weakest recurring combinations seen in prediction_report.py
- Stay pure and testable
- Remain observe-only until enough data accumulates

Usage:
  python3 setup_engine.py --symbol QQQ
  python3 setup_engine.py --snapshot-id 233
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


def bucket_relative_strength(v: float | None) -> str:
    if v is None:
        return "unknown"
    if v <= -0.30:
        return "weak"
    if v >= 0.30:
        return "strong"
    return "neutral"


def bucket_vwap_distance(v: float | None) -> str:
    if v is None:
        return "unknown"
    if v <= -0.75:
        return "far_below_vwap"
    if v <= -0.15:
        return "below_vwap"
    if v < 0.15:
        return "near_vwap"
    if v < 0.75:
        return "above_vwap"
    return "far_above_vwap"


@dataclass(frozen=True)
class SetupResult:
    setup_label: str
    recommendation: str
    setup_score: int
    confidence: str
    trend_bucket: str
    vwap_bucket: str
    rs_bucket: str
    setup_key: str
    rationale: str
    sample_basis: str


def _trend_bucket(snapshot: dict[str, Any]) -> str:
    direction = snapshot.get("trend_direction") or "unknown"
    strength = snapshot.get("trend_strength") or "unknown"
    return f"{direction}/{strength}"


def _build_setup_key(trend_bucket: str, vwap_bucket: str, rs_bucket: str) -> str:
    return f"{trend_bucket}|{vwap_bucket}|{rs_bucket}"


def classify_feature_snapshot(snapshot: dict[str, Any]) -> SetupResult:
    """
    Classify a feature snapshot into a named setup.

    This version is tuned to the latest observed setup performance from
    prediction_report.py.
    """
    trend_bucket = _trend_bucket(snapshot)
    vwap_bucket = bucket_vwap_distance(snapshot.get("distance_from_vwap"))
    rs_bucket = bucket_relative_strength(snapshot.get("relative_strength_5m"))
    setup_key = _build_setup_key(trend_bucket, vwap_bucket, rs_bucket)

    # Strongest recurring favorable setups
    if (
        trend_bucket == "neutral/weak"
        and vwap_bucket == "near_vwap"
        and rs_bucket == "weak"
    ):
        return SetupResult(
            setup_label="near_vwap_weak_strength_followthrough",
            recommendation="favorable",
            setup_score=88,
            confidence="medium",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale=(
                "Neutral/weak trend near VWAP with weak relative-strength bucket has "
                "been one of the strongest short-horizon performers so far."
            ),
            sample_basis="derived from latest top combined setup leaderboard",
        )

    if (
        trend_bucket == "neutral/weak"
        and vwap_bucket == "above_vwap"
        and rs_bucket == "neutral"
    ):
        return SetupResult(
            setup_label="above_vwap_neutral_continuation",
            recommendation="neutral",
            setup_score=48,
            confidence="low",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale=(
                "Neutral/weak trend above VWAP with neutral RS is no longer a clear positive edge. "
                "Short-horizon behavior is close to flat and longer follow-through is weak."
            ),
            sample_basis="retuned from latest setup-label report",
        )

    if (
        trend_bucket == "bullish/confirmed"
        and vwap_bucket == "near_vwap"
        and rs_bucket == "neutral"
    ):
        return SetupResult(
            setup_label="confirmed_near_vwap_recovery",
            recommendation="watch",
            setup_score=68,
            confidence="low",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale=(
                "Confirmed bullish trend near VWAP with neutral relative strength has "
                "turned positive in the latest observed sample."
            ),
            sample_basis="derived from latest top combined setup leaderboard",
        )

    if (
        trend_bucket == "neutral/weak"
        and vwap_bucket == "far_below_vwap"
        and rs_bucket == "weak"
    ):
        return SetupResult(
            setup_label="oversold_weak_bounce_watch",
            recommendation="watch",
            setup_score=61,
            confidence="low",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale=(
                "Far below VWAP with weak RS can still bounce. Positive expectancy exists, "
                "but hit rate is only moderate and behavior is volatile."
            ),
            sample_basis="derived from latest combined setup leaderboard",
        )

    if (
        trend_bucket == "neutral/weak"
        and vwap_bucket == "far_below_vwap"
        and rs_bucket == "neutral"
    ):
        return SetupResult(
            setup_label="oversold_neutral_rebound_watch",
            recommendation="watch",
            setup_score=58,
            confidence="low",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale=(
                "Far below VWAP, but not outright weak on RS. Rebound potential exists, "
                "but sample size is still small."
            ),
            sample_basis="small-sample positive combined setup",
        )

    if (
        trend_bucket == "neutral/weak"
        and vwap_bucket == "above_vwap"
        and rs_bucket == "neutral"
    ):
        return SetupResult(
            setup_label="above_vwap_neutral_continuation",
            recommendation="watch",
            setup_score=57,
            confidence="low",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale=(
                "Neutral/weak trend above VWAP with neutral RS has shown mild positive expectancy."
            ),
            sample_basis="derived from latest combined setup leaderboard",
        )

    if (
        trend_bucket == "neutral/weak"
        and vwap_bucket == "above_vwap"
        and rs_bucket == "strong"
    ):
        return SetupResult(
            setup_label="above_vwap_strength_continuation",
            recommendation="watch",
            setup_score=54,
            confidence="low",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale=(
                "Above VWAP with strong RS remains modestly positive, but less robust than "
                "the better near-VWAP setups."
            ),
            sample_basis="derived from latest combined setup leaderboard",
        )

    # Strong avoid setups
    if (
        trend_bucket == "bullish/confirmed"
        and vwap_bucket == "above_vwap"
        and rs_bucket == "strong"
    ):
        return SetupResult(
            setup_label="avoid_stretched_above_vwap_strength",
            recommendation="avoid",
            setup_score=5,
            confidence="medium",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale=(
                "Confirmed bullish trend already above VWAP with strong RS has been the worst "
                "short-horizon loser in the latest sample. This looks like late chase behavior."
            ),
            sample_basis="derived from latest bottom combined setup leaderboard",
        )

    if (
        trend_bucket == "bullish/developing"
        and vwap_bucket == "far_below_vwap"
        and rs_bucket == "weak"
    ):
        return SetupResult(
            setup_label="avoid_far_below_vwap_chase",
            recommendation="avoid",
            setup_score=8,
            confidence="medium",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale=(
                "Bullish developing trend while still far below VWAP with weak relative strength "
                "remains a clear recurring short-horizon loser."
            ),
            sample_basis="derived from latest bottom combined setup leaderboard",
        )

    if (
        trend_bucket == "neutral/weak"
        and vwap_bucket == "below_vwap"
        and rs_bucket == "weak"
    ):
        return SetupResult(
            setup_label="avoid_below_vwap_weak_drift",
            recommendation="avoid",
            setup_score=18,
            confidence="medium",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale=(
                "Neutral/weak trend below VWAP with weak RS has become a clearly negative setup."
            ),
            sample_basis="derived from latest bottom combined setup leaderboard",
        )

    if (
        trend_bucket == "neutral/weak"
        and vwap_bucket == "near_vwap"
        and rs_bucket == "neutral"
    ):
        return SetupResult(
            setup_label="near_vwap_neutral_fade_risk",
            recommendation="avoid",
            setup_score=28,
            confidence="low",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale=(
                "Near VWAP with neutral RS looked fine earlier, but the latest broader sample "
                "has turned this combination negative."
            ),
            sample_basis="derived from latest bottom combined setup leaderboard",
        )

    if (
        trend_bucket == "bullish/confirmed"
        and vwap_bucket == "near_vwap"
        and rs_bucket == "strong"
    ):
        return SetupResult(
            setup_label="late_strength_near_vwap_risk",
            recommendation="avoid",
            setup_score=24,
            confidence="low",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale=(
                "Confirmed bullish trend near VWAP with strong RS still looks like late strength "
                "rather than fresh continuation."
            ),
            sample_basis="derived from latest bottom combined setup leaderboard",
        )

    # Neutral / fallback states
    if (
        trend_bucket == "neutral/weak"
        and vwap_bucket == "below_vwap"
        and rs_bucket == "neutral"
    ):
        return SetupResult(
            setup_label="below_vwap_neutral_drift_risk",
            recommendation="avoid",
            setup_score=30,
            confidence="low",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale=(
                "Neutral/weak trend below VWAP with neutral RS has turned negative in the broader sample. "
                "Treat this as drift risk rather than a favorable continuation."
            ),
            sample_basis="retuned from latest setup-label report",
        )

    if trend_bucket == "neutral/weak" and vwap_bucket == "near_vwap":
        return SetupResult(
            setup_label="neutral_near_vwap_balanced",
            recommendation="watch",
            setup_score=55,
            confidence="low",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale=(
                "Neutral/weak trend near VWAP remains structurally cleaner than stretched states, "
                "but edge depends strongly on RS bucket."
            ),
            sample_basis="fallback structural rule",
        )

    if vwap_bucket == "far_below_vwap" and rs_bucket == "weak":
        return SetupResult(
            setup_label="far_below_vwap_weakness",
            recommendation="avoid",
            setup_score=20,
            confidence="low",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale=(
                "Far below VWAP with weak RS is generally poor for immediate entries unless proven otherwise."
            ),
            sample_basis="fallback structural rule",
        )

    if vwap_bucket in {"below_vwap", "near_vwap"} and rs_bucket == "neutral":
        return SetupResult(
            setup_label="balanced_transition_state",
            recommendation="neutral",
            setup_score=45,
            confidence="low",
            trend_bucket=trend_bucket,
            vwap_bucket=vwap_bucket,
            rs_bucket=rs_bucket,
            setup_key=setup_key,
            rationale="Balanced state without a strong positive or negative edge yet.",
            sample_basis="fallback structural rule",
        )

    return SetupResult(
        setup_label="unclassified_transition",
        recommendation="neutral",
        setup_score=40,
        confidence="low",
        trend_bucket=trend_bucket,
        vwap_bucket=vwap_bucket,
        rs_bucket=rs_bucket,
        setup_key=setup_key,
        rationale="No strong observed edge yet for this combination. Keep observe-only.",
        sample_basis="fallback default",
    )


def load_snapshot_by_id(snapshot_id: int) -> dict[str, Any] | None:
    with get_connection(DB_PATH) as con:
        row = con.execute(
            """
            SELECT
                id,
                timestamp,
                symbol,
                market_session,
                market_bias,
                trend_direction,
                trend_strength,
                relative_strength_5m,
                distance_from_vwap,
                ret_5m,
                ret_15m,
                bar_timeframe,
                bar_count
            FROM feature_snapshots
            WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone()

    return dict(row) if row else None


def load_latest_snapshot_for_symbol(symbol: str) -> dict[str, Any] | None:
    with get_connection(DB_PATH) as con:
        row = con.execute(
            """
            SELECT
                id,
                timestamp,
                symbol,
                market_session,
                market_bias,
                trend_direction,
                trend_strength,
                relative_strength_5m,
                distance_from_vwap,
                ret_5m,
                ret_15m,
                bar_timeframe,
                bar_count
            FROM feature_snapshots
            WHERE symbol = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (symbol.upper(),),
        ).fetchone()

    return dict(row) if row else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Classify the latest snapshot for a symbol")
    parser.add_argument("--snapshot-id", type=int, help="Classify one snapshot by id")
    args = parser.parse_args()

    if not args.symbol and args.snapshot_id is None:
        parser.error("Provide either --symbol or --snapshot-id")
    if args.symbol and args.snapshot_id is not None:
        parser.error("Use either --symbol or --snapshot-id, not both")

    if args.snapshot_id is not None:
        snapshot = load_snapshot_by_id(args.snapshot_id)
    else:
        snapshot = load_latest_snapshot_for_symbol(args.symbol)

    if not snapshot:
        print("No matching snapshot found.")
        return 1

    result = classify_feature_snapshot(snapshot)

    out = {
        "snapshot": snapshot,
        "setup": asdict(result),
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())