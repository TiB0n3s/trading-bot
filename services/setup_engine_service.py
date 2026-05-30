"""Setup-engine classification and feature snapshot lookup service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from repositories.setup_engine_repo import SetupEngineRepository


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


def _classify_base(snapshot: dict[str, Any]) -> SetupResult:
    """Map trend/VWAP/RS buckets to a named setup. No modifier logic here."""
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


def _score_modifiers(snapshot: dict[str, Any], base: SetupResult) -> SetupResult:
    """
    Apply deterministic score adjustments for fields not captured by the
    base trend/VWAP/RS label: momentum acceleration, volume, extension from
    recent base, and prior-session return.
    """
    delta = 0
    notes: list[str] = []

    acc = snapshot.get("momentum_acceleration_pct")
    if acc is not None:
        if acc <= -0.05:
            delta -= 12
            notes.append(f"strong_decel({acc:.3f})")
        elif acc <= -0.03:
            delta -= 8
            notes.append(f"decel({acc:.3f})")
        elif acc >= 0.05:
            delta += 6
            notes.append(f"strong_accel({acc:.3f})")
        elif acc >= 0.03:
            delta += 3
            notes.append(f"accel({acc:.3f})")

    vol = snapshot.get("volume_surge_ratio")
    if vol is not None:
        if vol >= 2.5:
            delta += 8
            notes.append(f"vol_surge({vol:.1f}x)")
        elif vol >= 2.0:
            delta += 5
            notes.append(f"vol_elevated({vol:.1f}x)")
        elif vol < 0.5:
            delta -= 10
            notes.append(f"vol_thin({vol:.1f}x)")
        elif vol < 0.8:
            delta -= 5
            notes.append(f"vol_below_avg({vol:.1f}x)")

    ext = snapshot.get("extension_from_recent_base_pct")
    if ext is not None:
        if ext >= 8.0:
            delta -= 15
            notes.append(f"overextended({ext:.1f}%)")
        elif ext >= 5.0:
            delta -= 10
            notes.append(f"extended({ext:.1f}%)")
        elif ext >= 3.0:
            delta -= 5
            notes.append(f"slightly_extended({ext:.1f}%)")

    prior = snapshot.get("prior_session_return_pct")
    if prior is not None:
        if prior > 5.0:
            delta -= 10
            notes.append(f"prior_strong_day({prior:.1f}%)")
        elif prior > 3.0:
            delta -= 6
            notes.append(f"prior_good_day({prior:.1f}%)")
        elif prior > 1.5:
            delta -= 3
            notes.append(f"prior_up_day({prior:.1f}%)")

    if delta == 0:
        return base

    new_score = max(0, min(100, base.setup_score + delta))
    rationale = base.rationale + f" [modifiers: {'; '.join(notes)} → {delta:+d}]"
    return SetupResult(
        setup_label=base.setup_label,
        recommendation=base.recommendation,
        setup_score=new_score,
        confidence=base.confidence,
        trend_bucket=base.trend_bucket,
        vwap_bucket=base.vwap_bucket,
        rs_bucket=base.rs_bucket,
        setup_key=base.setup_key,
        rationale=rationale,
        sample_basis=base.sample_basis,
    )


def classify_feature_snapshot(snapshot: dict[str, Any]) -> SetupResult:
    """
    Classify a feature snapshot into a named setup with score modifiers.

    Base label is determined by trend/VWAP/RS buckets (tuned to observed
    setup performance). Score is then adjusted for momentum acceleration,
    volume, extension from recent base, and prior-session return.
    """
    return _score_modifiers(snapshot, _classify_base(snapshot))


class SetupEngineService:
    def __init__(
        self,
        *,
        repository: SetupEngineRepository,
        classifier=classify_feature_snapshot,
    ):
        self.repository = repository
        self.classifier = classifier

    def classify(self, snapshot: dict[str, Any]) -> SetupResult:
        return self.classifier(snapshot)

    def load_snapshot_by_id(self, snapshot_id: int) -> dict[str, Any] | None:
        return self.repository.load_snapshot_by_id(snapshot_id)

    def load_latest_snapshot_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        return self.repository.load_latest_snapshot_for_symbol(symbol)


def build_default_setup_engine_service(db_path=None) -> SetupEngineService:
    repository = (
        SetupEngineRepository(db_path=db_path)
        if db_path is not None
        else SetupEngineRepository()
    )
    return SetupEngineService(repository=repository)
