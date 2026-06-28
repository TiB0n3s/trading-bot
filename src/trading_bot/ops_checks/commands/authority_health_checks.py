"""Authority and evidence-lineage health report.

This command is intentionally read-only and avoids scanning ``trades.db``.
It validates the checked-in authority matrix, then inspects lightweight
artifacts that declare whether evidence is current enough to be trusted.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from symbols_config import APPROVED_SYMBOLS_LIST

from trading_bot.ops_checks.commands.historical_bar_progress_checks import (
    DEFAULT_MANIFEST_DIR,
    _cache_symbol_progress,
    _load_manifests,
)

REPORT_VERSION = "authority_health_v1"
MATRIX_PATH = Path("ops") / "authority_matrix.json"
MODEL_CANDIDATE_DIR = (
    Path("ml") / "models" / "historical_bar_patterns_v1" / "candidates"
)
REQUIRED_GATE_FIELDS = {
    "id",
    "owner",
    "source",
    "authority",
    "mode_scope",
    "freshness",
    "fallback",
    "tests",
    "notes",
}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_hours(value: Any, *, now: datetime) -> float | None:
    parsed = _parse_dt(value)
    if not parsed:
        return None
    return round(max(0.0, (now - parsed).total_seconds() / 3600.0), 2)


def _matrix_health(base_dir: Path) -> dict[str, Any]:
    path = base_dir / MATRIX_PATH
    matrix = _load_json(path)
    gates = matrix.get("gates") if isinstance(matrix.get("gates"), list) else []
    missing_fields: list[str] = []
    duplicate_ids: list[str] = []
    seen: set[str] = set()
    for idx, gate in enumerate(gates):
        if not isinstance(gate, dict):
            missing_fields.append(f"gate[{idx}]:not_object")
            continue
        gate_id = str(gate.get("id") or f"gate[{idx}]")
        if gate_id in seen:
            duplicate_ids.append(gate_id)
        seen.add(gate_id)
        missing = sorted(REQUIRED_GATE_FIELDS - set(gate))
        missing_fields.extend(f"{gate_id}:{field}" for field in missing)
    ok = bool(matrix) and matrix.get("version") == "authority_matrix_v1" and not missing_fields
    return {
        "path": str(path),
        "exists": path.exists(),
        "version": matrix.get("version"),
        "gate_count": len(gates),
        "duplicate_ids": duplicate_ids,
        "missing_fields": missing_fields,
        "ok": ok and not duplicate_ids,
    }


def _strategy_memory_health(
    base_dir: Path,
    *,
    now: datetime,
    max_age_hours: int,
) -> dict[str, Any]:
    path = base_dir / "strategy_memory.json"
    payload = _load_json(path)
    generated_at = payload.get("generated_at")
    age = _age_hours(generated_at, now=now)
    bar_rows = int(payload.get("bar_pattern_rows") or 0)
    context = payload.get("bar_pattern_label_context") or {}
    outcome_rows = 0
    ready_buckets = 0
    if isinstance(context, dict):
        for item in context.values():
            if isinstance(item, dict):
                outcome_rows += int(item.get("forward_outcome_rows") or 0)
                if item.get("authority_ready"):
                    ready_buckets += 1
    blockers: list[str] = []
    if not path.exists():
        blockers.append("strategy_memory_missing")
    if age is None:
        blockers.append("strategy_memory_generated_at_missing")
    elif age > max_age_hours:
        blockers.append(f"strategy_memory_stale:{age:.1f}h>{max_age_hours}h")
    if bar_rows <= 0:
        blockers.append("strategy_memory_bar_pattern_rows_missing")
    if outcome_rows <= 0:
        blockers.append("strategy_memory_bar_pattern_outcomes_missing")
    return {
        "path": str(path),
        "exists": path.exists(),
        "generated_at": generated_at,
        "age_hours": age,
        "max_age_hours": max_age_hours,
        "trade_count": payload.get("trade_count"),
        "bar_pattern_rows": bar_rows,
        "bar_pattern_forward_outcome_rows": outcome_rows,
        "bar_pattern_ready_buckets": ready_buckets,
        "blockers": blockers,
        "ok": not blockers,
    }


def _historical_bar_cache_health(
    base_dir: Path,
    *,
    min_days: int,
    min_symbols: int,
) -> dict[str, Any]:
    cache_dir = base_dir / DEFAULT_MANIFEST_DIR.parent
    progress = _cache_symbol_progress(cache_dir, min_days=min_days)
    ready = [row for row in progress if row.get("ready")]
    remaining = [row for row in progress if not row.get("ready")]
    manifests = _load_manifests(base_dir / DEFAULT_MANIFEST_DIR, limit=10)
    recent_errors = [
        err for manifest in manifests for err in (manifest.get("errors") or [])
    ]
    latest = manifests[0] if manifests else {}
    latest_errors = latest.get("errors") or []
    blockers: list[str] = []
    if len(ready) < min_symbols:
        blockers.append(f"historical_bar_ready_symbols:{len(ready)}<{min_symbols}")
    if latest_errors:
        blockers.append(f"latest_manifest_errors:{len(latest_errors)}")
    return {
        "symbols_expected": len(APPROVED_SYMBOLS_LIST),
        "symbols_ready": len(ready),
        "symbols_remaining": len(remaining),
        "min_days_required": min_days,
        "min_symbols_required": min_symbols,
        "ready_floor_met": len(ready) >= min_symbols,
        "remaining_symbols": [
            {
                "symbol": row.get("symbol"),
                "dates": row.get("market_dates"),
                "remaining_days": row.get("days_remaining"),
                "chunks": row.get("cache_chunks"),
            }
            for row in remaining[:20]
        ],
        "recent_manifest_count": len(manifests),
        "recent_manifest_errors": len(recent_errors),
        "latest_manifest": latest.get("manifest_file") or latest.get("file"),
        "latest_manifest_errors": len(latest_errors),
        "blockers": blockers,
        "ok": not blockers,
    }


def _latest_model_diagnostics(candidate_dir: Path) -> dict[str, dict[str, Any]]:
    by_label: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(candidate_dir.glob("historical_bar_*_*.diagnostic.json")):
        payload = _load_json(path)
        if not payload:
            continue
        label = str(payload.get("label_target") or "unknown")
        payload["_path"] = str(path)
        by_label.setdefault(label, []).append(payload)
    latest: dict[str, dict[str, Any]] = {}
    for label, rows in by_label.items():
        rows.sort(key=lambda item: str(item.get("generated_at") or ""), reverse=True)
        trained_rows = [
            row
            for row in rows
            if (row.get("training") or {}).get("trained")
            and row.get("runtime_effect") == "observe_only_no_live_authority"
        ]
        latest[label] = trained_rows[0] if trained_rows else rows[0]
    return latest


def _historical_model_health(
    base_dir: Path,
    *,
    min_rows: int,
    min_symbols: int,
    min_accuracy: float,
) -> dict[str, Any]:
    candidate_dir = base_dir / MODEL_CANDIDATE_DIR
    diagnostic_count = len(list(candidate_dir.glob("historical_bar_*_*.diagnostic.json")))
    latest = _latest_model_diagnostics(candidate_dir)
    labels: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    for label in ("trend_scan_label", "triple_barrier_label"):
        payload = latest.get(label) or {}
        training = payload.get("training") if isinstance(payload.get("training"), dict) else {}
        rows_loaded = int(payload.get("rows_loaded") or 0)
        symbol_count = int(payload.get("symbol_count") or 0)
        accuracy = training.get("accuracy")
        accuracy_float = float(accuracy) if accuracy is not None else None
        failed: list[str] = []
        if not payload:
            failed.append("missing_diagnostic")
        if payload and payload.get("runtime_effect") != "observe_only_no_live_authority":
            failed.append("runtime_effect_not_observe_only")
        if not training.get("trained"):
            failed.append("not_trained")
        if rows_loaded < min_rows:
            failed.append(f"rows_loaded:{rows_loaded}<{min_rows}")
        if symbol_count < min_symbols:
            failed.append(f"symbol_count:{symbol_count}<{min_symbols}")
        if accuracy_float is None:
            failed.append("accuracy_missing")
        elif accuracy_float < min_accuracy:
            failed.append(f"accuracy:{accuracy_float:.4f}<{min_accuracy:.4f}")
        labels[label] = {
            "model_id": payload.get("model_id"),
            "rows_loaded": rows_loaded,
            "symbol_count": symbol_count,
            "accuracy": accuracy_float,
            "trained": bool(training.get("trained")),
            "status": "observe_only_candidate_ready" if not failed else "not_ready",
            "failed_thresholds": failed,
            "diagnostic_path": payload.get("_path"),
        }
        blockers.extend(f"{label}:{item}" for item in failed)
    return {
        "candidate_dir": str(candidate_dir),
        "diagnostics_found": diagnostic_count,
        "min_rows_required": min_rows,
        "min_symbols_required": min_symbols,
        "min_accuracy_required": min_accuracy,
        "labels": labels,
        "blockers": blockers,
        "ok": not blockers,
    }


def build_authority_health_payload(
    *,
    base_dir: Path,
    now: datetime | None = None,
    max_strategy_age_hours: int = 96,
    historical_min_days: int = 252,
    historical_min_symbols: int = 20,
    model_min_rows: int = 5000,
    model_min_symbols: int = 59,
    model_min_accuracy: float = 0.5,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    matrix = _matrix_health(base_dir)
    strategy = _strategy_memory_health(
        base_dir,
        now=now,
        max_age_hours=max_strategy_age_hours,
    )
    cache = _historical_bar_cache_health(
        base_dir,
        min_days=historical_min_days,
        min_symbols=historical_min_symbols,
    )
    models = _historical_model_health(
        base_dir,
        min_rows=model_min_rows,
        min_symbols=model_min_symbols,
        min_accuracy=model_min_accuracy,
    )
    blockers = []
    for section_name, section in (
        ("matrix", matrix),
        ("strategy_memory", strategy),
        ("historical_bars", cache),
        ("historical_models", models),
    ):
        for blocker in section.get("blockers") or section.get("missing_fields") or []:
            blockers.append(f"{section_name}:{blocker}")
        for duplicate in section.get("duplicate_ids") or []:
            blockers.append(f"{section_name}:duplicate_gate_id:{duplicate}")
    return {
        "report_version": REPORT_VERSION,
        "runtime_effect": "diagnostic_only_no_live_authority",
        "generated_at": now.isoformat(),
        "authority_clean": not blockers,
        "matrix": matrix,
        "strategy_memory": strategy,
        "historical_bars": cache,
        "historical_models": models,
        "blockers": blockers,
    }


def run_authority_health(base_dir: Path | None = None) -> bool:
    base_dir = base_dir or Path.cwd()
    payload = build_authority_health_payload(base_dir=base_dir)
    print()
    print("=" * 72)
    print("  Authority Health")
    print("=" * 72)
    print(f"report_version             : {payload['report_version']}")
    print(f"runtime_effect             : {payload['runtime_effect']}")
    print(f"authority_clean            : {payload['authority_clean']}")

    matrix = payload["matrix"]
    print()
    print("Authority matrix")
    print(f"  version                  : {matrix.get('version')}")
    print(f"  gate_count               : {matrix.get('gate_count')}")
    print(f"  ok                       : {matrix.get('ok')}")

    strategy = payload["strategy_memory"]
    print()
    print("Strategy memory")
    print(f"  generated_at             : {strategy.get('generated_at')}")
    print(f"  age_hours                : {strategy.get('age_hours')}")
    print(f"  trade_count              : {strategy.get('trade_count')}")
    print(f"  bar_pattern_rows         : {strategy.get('bar_pattern_rows')}")
    print(
        "  bar_pattern_outcomes     : "
        f"{strategy.get('bar_pattern_forward_outcome_rows')}"
    )
    print(f"  ready_buckets            : {strategy.get('bar_pattern_ready_buckets')}")
    print(f"  ok                       : {strategy.get('ok')}")

    bars = payload["historical_bars"]
    print()
    print("Historical bars")
    print(f"  symbols_ready            : {bars.get('symbols_ready')}/{bars.get('symbols_expected')}")
    print(f"  symbols_remaining        : {bars.get('symbols_remaining')}")
    print(f"  latest_manifest          : {bars.get('latest_manifest') or '-'}")
    print(f"  latest_manifest_errors   : {bars.get('latest_manifest_errors')}")
    print(f"  recent_manifest_errors   : {bars.get('recent_manifest_errors')}")
    print(f"  ok                       : {bars.get('ok')}")
    if bars.get("remaining_symbols"):
        print("  remaining")
        for row in bars["remaining_symbols"][:10]:
            print(
                f"    {row.get('symbol'):<8} dates={row.get('dates'):<4} "
                f"remaining_days={row.get('remaining_days'):<4} chunks={row.get('chunks')}"
            )

    models = payload["historical_models"]
    print()
    print("Historical models")
    print(f"  diagnostics_found        : {models.get('diagnostics_found')}")
    print(f"  ok                       : {models.get('ok')}")
    for label, row in (models.get("labels") or {}).items():
        accuracy = row.get("accuracy")
        accuracy_text = "-" if accuracy is None else f"{accuracy:.4f}"
        print(
            f"  {label:<24} {row.get('status'):<32} "
            f"rows={row.get('rows_loaded'):<7} symbols={row.get('symbol_count'):<4} "
            f"accuracy={accuracy_text}"
        )
        failed = row.get("failed_thresholds") or []
        if failed:
            print(f"    failed                 : {', '.join(failed)}")

    if payload["blockers"]:
        print()
        print("Blockers")
        for blocker in payload["blockers"]:
            print(f"  - {blocker}")
        print()
        print("[WARN] authority health has unresolved governance or evidence-lineage gaps")
        return False

    print()
    print("[OK] authority matrix and lightweight evidence-lineage checks are clean")
    return True
