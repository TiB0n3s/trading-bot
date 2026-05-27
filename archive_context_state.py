#!/usr/bin/env python3
"""Archive point-in-time market context and override state.

Historical replay should not read mutable runtime files such as
market_context.json. This command creates timestamped JSON snapshots under
data_archive/point_in_time/ so dataset builders can later select the context
that existed at decision time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from policy_artifacts import POLICY_ARTIFACT_FILES
from symbols_config import SYMBOL_UNIVERSE_VERSION


BASE_DIR = Path(__file__).resolve().parent
ARCHIVE_ROOT = BASE_DIR / "data_archive" / "point_in_time"
RUNTIME_FILES = (
    "market_context.json",
    "manual_strategy_overrides.json",
    "symbol_overrides.json",
)


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:
        return {"_error": str(e)}


def _file_record(path: Path) -> dict[str, Any]:
    record = {
        "exists": path.exists(),
        "sha256": _sha256(path),
        "size_bytes": None,
        "mtime": None,
        "json": None,
    }
    if path.exists():
        stat = path.stat()
        record["size_bytes"] = stat.st_size
        record["mtime"] = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        record["json"] = _load_json(path)
    return record


def build_archive_payload(archive_reason: str) -> dict[str, Any]:
    files = {name: _file_record(BASE_DIR / name) for name in RUNTIME_FILES}
    policy_artifacts = {
        name: {
            "exists": (BASE_DIR / name).exists(),
            "sha256": _sha256(BASE_DIR / name),
        }
        for name in POLICY_ARTIFACT_FILES
    }
    # Full JSON content of policy artifacts for point-in-time replay.
    # strategy_memory.json is read by evaluate_decision_policy at replay time;
    # archiving its content lets replay use the version that existed at decision time.
    policy_artifacts_full = {
        name: _load_json(BASE_DIR / name)
        for name in POLICY_ARTIFACT_FILES
    }
    state_hash_payload = {
        "runtime_files": {name: item["sha256"] for name, item in files.items()},
        "policy_artifacts": policy_artifacts,
        "symbol_universe_version": SYMBOL_UNIVERSE_VERSION,
    }
    return {
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "archive_reason": archive_reason,
        "symbol_universe_version": SYMBOL_UNIVERSE_VERSION,
        "runtime_files": files,
        "policy_artifacts": policy_artifacts,
        "policy_artifacts_full": policy_artifacts_full,
        "state_hash": hashlib.sha256(
            json.dumps(state_hash_payload, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def write_archive(payload: dict[str, Any], target_date: str | None = None) -> Path:
    market_context = payload.get("runtime_files", {}).get("market_context.json", {}).get("json")
    market_date = None
    if isinstance(market_context, dict):
        market_date = market_context.get("market_date")
    date_part = target_date or market_date or datetime.now().date().isoformat()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ARCHIVE_ROOT / date_part
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"context_state_{ts}.json"
    tmp_path = out_path.with_name(f".{out_path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(out_path)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reason", default="manual_archive")
    parser.add_argument("--date")
    args = parser.parse_args()

    payload = build_archive_payload(args.reason)
    out_path = write_archive(payload, args.date)
    print(f"Wrote point-in-time context archive: {out_path}")
    print(f"state_hash={payload['state_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
