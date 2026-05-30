"""Runtime observability counters for policy and pipeline decisions."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from threading import Lock
from time import perf_counter
from typing import Iterator


_lock = Lock()
_metrics = {
    "pipeline_stage_timing": {},
    "fallback_frequency": {},
    "dominant_limiter_frequency": {},
    "policy_disagreement_rates": {},
    "policy_kill_switches": {},
}


def reset_metrics() -> None:
    with _lock:
        for value in _metrics.values():
            value.clear()


@contextmanager
def stage_timer(stage: str) -> Iterator[None]:
    start = perf_counter()
    try:
        yield
    finally:
        record_stage_timing(stage, (perf_counter() - start) * 1000.0)


def record_stage_timing(stage: str, elapsed_ms: float) -> None:
    with _lock:
        item = _metrics["pipeline_stage_timing"].setdefault(
            stage,
            {"count": 0, "total_ms": 0.0, "max_ms": 0.0},
        )
        item["count"] += 1
        item["total_ms"] += float(elapsed_ms)
        item["max_ms"] = max(item["max_ms"], float(elapsed_ms))


def record_market_data_fetch(symbol: str, feed: str, fallback: bool = False) -> None:
    key = f"{str(symbol or '').upper()}:{feed}"
    with _lock:
        item = _metrics["fallback_frequency"].setdefault(
            key,
            {"fetches": 0, "fallbacks": 0},
        )
        item["fetches"] += 1
        if fallback:
            item["fallbacks"] += 1


def record_dominant_limiter(limiter: str) -> None:
    key = limiter or "unknown"
    with _lock:
        bucket = _metrics["dominant_limiter_frequency"]
        bucket[key] = bucket.get(key, 0) + 1


def record_policy_comparison(policy: str, primary: str | None, secondary: str | None) -> None:
    if secondary is None:
        return
    with _lock:
        item = _metrics["policy_disagreement_rates"].setdefault(
            policy,
            {"comparisons": 0, "agreements": 0, "disagreements": 0},
        )
        item["comparisons"] += 1
        if primary == secondary:
            item["agreements"] += 1
        else:
            item["disagreements"] += 1


def record_policy_kill_switch(policy_family: str, enabled: bool) -> None:
    with _lock:
        _metrics["policy_kill_switches"][policy_family] = {
            "enabled": bool(enabled),
            "runtime_effect": "enabled" if enabled else "disabled",
        }


def metrics_snapshot() -> dict:
    with _lock:
        snapshot = deepcopy(_metrics)

    for item in snapshot["pipeline_stage_timing"].values():
        count = item.get("count") or 0
        total_ms = item.get("total_ms") or 0.0
        item["avg_ms"] = round(total_ms / count, 3) if count else 0.0
        item["total_ms"] = round(total_ms, 3)
        item["max_ms"] = round(item.get("max_ms") or 0.0, 3)

    for item in snapshot["fallback_frequency"].values():
        fetches = item.get("fetches") or 0
        fallbacks = item.get("fallbacks") or 0
        item["fallback_rate"] = round(fallbacks / fetches, 4) if fetches else 0.0

    for item in snapshot["policy_disagreement_rates"].values():
        comparisons = item.get("comparisons") or 0
        disagreements = item.get("disagreements") or 0
        item["disagreement_rate"] = (
            round(disagreements / comparisons, 4) if comparisons else 0.0
        )

    return snapshot
