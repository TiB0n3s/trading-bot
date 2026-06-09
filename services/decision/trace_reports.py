"""Trace-native decision reporting from persisted decision snapshots."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from repositories.decision_snapshot_repo import DecisionSnapshotRepository


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _trace_from_state(state: dict[str, Any]) -> dict[str, Any]:
    trace = state.get("canonical_decision_trace") or state.get("decision_trace") or {}
    return trace if isinstance(trace, dict) else {}


def load_trace_rows(
    *,
    db_path: Path,
    target_date: str,
    limit: int = 500,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    repo = DecisionSnapshotRepository(db_path)
    for row in repo.list_trace_rows(target_date=target_date, limit=limit):
        trace = _loads(row["gate_trace_json"])
        if not trace:
            state = _loads(row["account_state_json"])
            trace = _trace_from_state(state)
        if not trace:
            continue
        payloads.append(
            {
                "snapshot_id": row["id"],
                "decision_time": row["decision_time"],
                "symbol": row["symbol"],
                "action": row["action"],
                "final_decision": row["final_decision"],
                "rejection_reason": row["rejection_reason"],
                "trace": trace,
            }
        )
    return payloads


def decision_trace_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    final_counts = Counter(str(row.get("final_decision") or "unknown") for row in rows)
    gate_counts: Counter[str] = Counter()
    blocking_counts: Counter[str] = Counter()
    limiter_counts: Counter[str] = Counter()
    for row in rows:
        trace = row.get("trace") or {}
        if trace.get("blocking_gate"):
            blocking_counts[str(trace["blocking_gate"])] += 1
        if trace.get("dominant_limiter"):
            limiter_counts[str(trace["dominant_limiter"])] += 1
        for gate in trace.get("gate_results") or []:
            if isinstance(gate, dict):
                gate_counts[str(gate.get("gate_id") or "unknown")] += 1
    return {
        "rows": len(rows),
        "final_decisions": dict(final_counts),
        "gate_counts": dict(gate_counts),
        "blocking_gates": dict(blocking_counts),
        "dominant_limiters": dict(limiter_counts),
    }


def gate_impact_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    impacts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        trace = row.get("trace") or {}
        for gate in trace.get("gate_results") or []:
            if not isinstance(gate, dict):
                continue
            gate_id = str(gate.get("gate_id") or "unknown")
            decision = str(gate.get("decision") or "unknown")
            enforced = "enforced" if gate.get("enforced") else "observed"
            impacts[gate_id][f"{decision}:{enforced}"] += 1
    return {gate_id: dict(counts) for gate_id, counts in sorted(impacts.items())}


def model_authority_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sources = Counter()
    effects = Counter()
    for row in rows:
        trace = row.get("trace") or {}
        shadow = trace.get("shadow") or {}
        sources[str(shadow.get("approval_source") or "unknown")] += 1
        for gate in trace.get("gate_results") or []:
            if not isinstance(gate, dict):
                continue
            if gate.get("layer") in {"authority", "ml", "prediction", "intelligence"}:
                effects[
                    f"{gate.get('gate_id') or 'unknown'}:{gate.get('decision') or 'unknown'}"
                ] += 1
    return {"approval_sources": dict(sources), "model_authority_effects": dict(effects)}


def counterfactual_replay_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    changed_by_trace = []
    for row in rows:
        trace = row.get("trace") or {}
        shadow = trace.get("shadow") or {}
        source = shadow.get("approval_source")
        if source and source not in {"claude", "unknown"}:
            changed_by_trace.append(
                {
                    "snapshot_id": row.get("snapshot_id"),
                    "symbol": row.get("symbol"),
                    "action": row.get("action"),
                    "source": source,
                    "final_decision": trace.get("final_decision"),
                }
            )
    return {
        "changed_decisions": len(changed_by_trace),
        "rows": changed_by_trace[:50],
    }
