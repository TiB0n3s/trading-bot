"""Helpers for runtime policy artifact files.

Policy artifacts are JSON files produced by after-close learning and consumed by
the live runtime. Writes must be atomic because Flask workers can read them
while the learning job is running.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POLICY_ARTIFACT_FILES = (
    "strategy_memory.json",
    "portfolio_replacement_memory.json",
    "excursion_memory.json",
    "missed_opportunity_memory.json",
    "symbol_momentum_timing_memory.json",
    "policy_backtest_summary.json",
)

REGISTRY_DIR = Path("data_archive") / "policy_artifacts"
SNAPSHOT_DIR = REGISTRY_DIR / "snapshots"
REGISTRY_FILE = REGISTRY_DIR / "registry.json"
KNOWN_GOOD_FILE = REGISTRY_DIR / "known_good.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_sha(base_dir: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=base_dir,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).strip()
    except Exception:
        return None


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def policy_artifacts_enabled() -> bool:
    value = os.getenv("POLICY_ARTIFACTS_ENABLED", "true").strip().lower()
    return value not in ("0", "false", "no", "off")


def atomic_write_json(
    path: Path | str, data: Any, *, indent: int = 2, sort_keys: bool = True
) -> Path:
    """Write JSON atomically using a temp file and os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    try:
        tmp_path.write_text(json.dumps(data, indent=indent, sort_keys=sort_keys) + "\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return path


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _artifact_file_record(base_dir: Path, name: str) -> dict[str, Any]:
    path = base_dir / name
    item = {
        "exists": path.exists(),
        "sha256": None,
        "size_bytes": None,
        "mtime": None,
        "generated_at": None,
        "runtime_effect": "policy_artifact",
    }
    if not path.exists():
        return item

    raw = path.read_bytes()
    stat = path.stat()
    item.update(
        {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        }
    )
    try:
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict):
            item["generated_at"] = data.get("generated_at")
            item["lookback_days"] = data.get("lookback_days")
            if name == "policy_backtest_summary.json":
                item["recommendation"] = data.get("recommendation")
                item["reason"] = data.get("reason")
    except Exception as e:
        item["parse_error"] = str(e)
    return item


def _current_artifact_files(base_dir: Path) -> dict[str, dict[str, Any]]:
    return {name: _artifact_file_record(base_dir, name) for name in POLICY_ARTIFACT_FILES}


def _state_hash(files: dict[str, Any]) -> str:
    payload = {
        name: item.get("sha256") if isinstance(item, dict) else item for name, item in files.items()
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def registry_paths(base_dir: Path | str) -> dict[str, Path]:
    base_dir = Path(base_dir)
    root = base_dir / REGISTRY_DIR
    return {
        "root": root,
        "snapshots": base_dir / SNAPSHOT_DIR,
        "registry": base_dir / REGISTRY_FILE,
        "known_good": base_dir / KNOWN_GOOD_FILE,
    }


def policy_artifact_registry_status(base_dir: Path | str) -> dict[str, Any]:
    base_dir = Path(base_dir)
    paths = registry_paths(base_dir)
    registry = _load_json(paths["registry"], {"entries": []})
    known_good = _load_json(paths["known_good"], None)
    entries = registry.get("entries") if isinstance(registry, dict) else []
    entries = entries if isinstance(entries, list) else []
    return {
        "registry_path": str(paths["registry"]),
        "known_good_path": str(paths["known_good"]),
        "entry_count": len(entries),
        "latest_entry": entries[-1] if entries else None,
        "known_good": known_good,
    }


def register_policy_artifact_set(
    base_dir: Path | str,
    *,
    label: str = "manual",
    source: str = "manual",
    runtime_effect: str = "live_policy_context",
    mark_known_good: bool = False,
) -> dict[str, Any]:
    """Snapshot current policy artifacts and append a registry entry."""
    base_dir = Path(base_dir)
    paths = registry_paths(base_dir)
    paths["root"].mkdir(parents=True, exist_ok=True)
    paths["snapshots"].mkdir(parents=True, exist_ok=True)

    files = _current_artifact_files(base_dir)
    state_hash = _state_hash(files)
    created_at = _utc_now()
    id_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_set_id = f"policy_artifacts_{id_ts}_{state_hash[:12]}"
    snapshot_path = paths["snapshots"] / f"{artifact_set_id}.json"
    snapshot_payload = {
        "artifact_set_id": artifact_set_id,
        "created_at": created_at,
        "label": label,
        "source": source,
        "runtime_effect": runtime_effect,
        "git_sha": _git_sha(base_dir),
        "state_hash": state_hash,
        "files": files,
        "contents": {},
    }

    missing = []
    for name in POLICY_ARTIFACT_FILES:
        path = base_dir / name
        if path.exists():
            snapshot_payload["contents"][name] = path.read_text()
        else:
            missing.append(name)
            snapshot_payload["contents"][name] = None
    snapshot_payload["missing_files"] = missing
    atomic_write_json(snapshot_path, snapshot_payload)

    entry = {
        "artifact_set_id": artifact_set_id,
        "created_at": created_at,
        "label": label,
        "source": source,
        "runtime_effect": runtime_effect,
        "state_hash": state_hash,
        "snapshot_path": str(snapshot_path.relative_to(base_dir)),
        "git_sha": snapshot_payload["git_sha"],
        "files": {
            name: {
                "sha256": item.get("sha256"),
                "mtime": item.get("mtime"),
                "generated_at": item.get("generated_at"),
                "exists": item.get("exists"),
            }
            for name, item in files.items()
        },
        "missing_files": missing,
    }

    registry = _load_json(
        paths["registry"], {"version": "policy_artifact_registry_v1", "entries": []}
    )
    if not isinstance(registry, dict):
        registry = {"version": "policy_artifact_registry_v1", "entries": []}
    registry.setdefault("version", "policy_artifact_registry_v1")
    registry.setdefault("entries", [])
    registry["entries"].append(entry)
    registry["updated_at"] = created_at
    atomic_write_json(paths["registry"], registry)

    if mark_known_good:
        known_good = {
            "artifact_set_id": artifact_set_id,
            "state_hash": state_hash,
            "snapshot_path": entry["snapshot_path"],
            "marked_at": created_at,
            "marked_by": source,
            "runtime_effect": runtime_effect,
        }
        atomic_write_json(paths["known_good"], known_good)

    return entry


def rollback_policy_artifacts(
    base_dir: Path | str,
    *,
    artifact_set_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Restore runtime policy artifacts from a registered snapshot."""
    base_dir = Path(base_dir)
    paths = registry_paths(base_dir)
    registry = _load_json(paths["registry"], {"entries": []})
    entries = registry.get("entries") if isinstance(registry, dict) else []
    entries = entries if isinstance(entries, list) else []

    target = None
    if artifact_set_id:
        target = next((e for e in entries if e.get("artifact_set_id") == artifact_set_id), None)
    else:
        known_good = _load_json(paths["known_good"], None)
        if isinstance(known_good, dict):
            kg_id = known_good.get("artifact_set_id")
            target = next((e for e in entries if e.get("artifact_set_id") == kg_id), None)

    if not target:
        raise FileNotFoundError("No registered policy artifact set found for rollback")

    snapshot_path = base_dir / target["snapshot_path"]
    snapshot = _load_json(snapshot_path, None)
    if not isinstance(snapshot, dict):
        raise FileNotFoundError(f"Policy artifact snapshot not readable: {snapshot_path}")

    restored = []
    skipped_missing = []
    for name in POLICY_ARTIFACT_FILES:
        content = (snapshot.get("contents") or {}).get(name)
        target_path = base_dir / name
        if content is None:
            skipped_missing.append(name)
            continue
        if not dry_run:
            tmp_path = target_path.with_name(f".{target_path.name}.rollback.tmp")
            tmp_path.write_text(content)
            os.replace(tmp_path, target_path)
        restored.append(name)

    result = {
        "artifact_set_id": target.get("artifact_set_id"),
        "state_hash": target.get("state_hash"),
        "snapshot_path": str(snapshot_path),
        "dry_run": dry_run,
        "restored_files": restored,
        "skipped_missing_files": skipped_missing,
        "rolled_back_at": _utc_now() if not dry_run else None,
    }

    if not dry_run:
        rollback_record = paths["root"] / "last_rollback.json"
        atomic_write_json(rollback_record, result)
    return result


def policy_artifact_status(base_dir: Path | str) -> dict[str, Any]:
    """Return read-only hashes for policy artifacts."""
    base_dir = Path(base_dir)
    artifacts = _current_artifact_files(base_dir)
    registry = policy_artifact_registry_status(base_dir)
    try:
        from ml_platform.registry import model_staleness_guard

        model_guard = model_staleness_guard(
            model_id=os.getenv("ML_MODEL_ID", "").strip(),
            max_age_seconds=int(os.getenv("ML_MODEL_MAX_AGE_SECONDS", "0") or 0),
            registry_path=base_dir / "ml" / "models" / "registry.json",
        )
    except Exception as exc:
        model_guard = {
            "status": "guard_error",
            "fallback_required": True,
            "fallback_strategy": "deterministic_policy_no_ml_authority",
            "reason": str(exc),
        }

    return {
        "artifact_type": "policy_artifact",
        "runtime_effect": "live_policy_context" if policy_artifacts_enabled() else "disabled",
        "enabled": policy_artifacts_enabled(),
        "model_staleness_guard": model_guard,
        "state_hash": _state_hash(artifacts),
        "registry": registry,
        "files": artifacts,
    }


def main() -> int:
    import argparse

    default_base_dir = str(Path(__file__).resolve().parents[1])

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    status_cmd = sub.add_parser("status")
    status_cmd.add_argument("--base-dir", default=default_base_dir)

    reg = sub.add_parser("register")
    reg.add_argument("--base-dir", default=default_base_dir)
    reg.add_argument("--label", default="manual")
    reg.add_argument("--source", default="policy_artifacts.py")
    reg.add_argument("--runtime-effect", default="live_policy_context")
    reg.add_argument("--known-good", action="store_true")

    rb = sub.add_parser("rollback")
    rb.add_argument("--base-dir", default=default_base_dir)
    rb.add_argument("--artifact-set-id")
    rb.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(policy_artifact_status(args.base_dir), indent=2, sort_keys=True))
        return 0
    if args.command == "register":
        print(
            json.dumps(
                register_policy_artifact_set(
                    args.base_dir,
                    label=args.label,
                    source=args.source,
                    runtime_effect=args.runtime_effect,
                    mark_known_good=args.known_good,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "rollback":
        print(
            json.dumps(
                rollback_policy_artifacts(
                    args.base_dir,
                    artifact_set_id=args.artifact_set_id,
                    dry_run=args.dry_run,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
