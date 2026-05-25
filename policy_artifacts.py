"""Helpers for runtime policy artifact files.

Policy artifacts are JSON files produced by after-close learning and consumed by
the live runtime. Writes must be atomic because Flask workers can read them
while the learning job is running.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


POLICY_ARTIFACT_FILES = (
    "strategy_memory.json",
    "portfolio_replacement_memory.json",
    "excursion_memory.json",
    "missed_opportunity_memory.json",
    "policy_backtest_summary.json",
)


def policy_artifacts_enabled() -> bool:
    value = os.getenv("POLICY_ARTIFACTS_ENABLED", "true").strip().lower()
    return value not in ("0", "false", "no", "off")


def atomic_write_json(path: Path | str, data: Any, *, indent: int = 2, sort_keys: bool = True) -> Path:
    """Write JSON atomically using a temp file and os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(data, indent=indent, sort_keys=sort_keys) + "\n")
    os.replace(tmp_path, path)
    return path


def policy_artifact_status(base_dir: Path | str) -> dict[str, Any]:
    """Return read-only hashes for policy artifacts."""
    base_dir = Path(base_dir)
    artifacts = {}
    combined = {}

    for name in POLICY_ARTIFACT_FILES:
        path = base_dir / name
        item = {
            "exists": path.exists(),
            "runtime_effect": "policy_artifact",
        }

        if path.exists():
            try:
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                stat = path.stat()
                item.update({
                    "sha256": digest,
                    "size_bytes": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                })
                combined[name] = digest
                try:
                    data = json.loads(raw.decode("utf-8"))
                    if isinstance(data, dict):
                        item["generated_at"] = data.get("generated_at")
                        item["lookback_days"] = data.get("lookback_days")
                except Exception:
                    item["generated_at"] = None
            except Exception as e:
                item["error"] = str(e)
        else:
            combined[name] = None

        artifacts[name] = item

    return {
        "artifact_type": "policy_artifact",
        "runtime_effect": "live_policy_context" if policy_artifacts_enabled() else "disabled",
        "enabled": policy_artifacts_enabled(),
        "state_hash": hashlib.sha256(
            json.dumps(combined, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "files": artifacts,
    }
