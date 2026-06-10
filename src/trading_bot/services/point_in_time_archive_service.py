"""Point-in-time archive for replay-safe context metadata."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POINT_IN_TIME_ARCHIVE_VERSION = "point_in_time_archive_v1"


@dataclass(frozen=True)
class PointInTimeArchiveResult:
    archive_path: Path
    archive_hash: str
    payload: dict[str, Any]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_json_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, None
    raw = path.read_text()
    try:
        loaded = json.loads(raw)
        data = loaded if isinstance(loaded, dict) else {"raw": loaded}
    except Exception:
        data = {"parse_error": True}
    return data, _sha256_text(raw)


class PointInTimeArchiveService:
    def __init__(self, *, base_dir: Path):
        self.base_dir = base_dir

    def archive_current_context(
        self,
        *,
        archive_date: str,
        reason: str = "operator_snapshot",
    ) -> PointInTimeArchiveResult:
        archived_at = _now_iso()
        market_context, market_context_hash = _read_json_file(self.base_dir / "market_context.json")
        symbol_overrides, symbol_overrides_hash = _read_json_file(
            self.base_dir / "symbol_overrides.json"
        )
        prediction_status, prediction_status_hash = _read_json_file(
            self.base_dir / "prediction_cache_status.json"
        )

        payload = {
            "version": POINT_IN_TIME_ARCHIVE_VERSION,
            "archived_at": archived_at,
            "archive_date": archive_date,
            "archive_reason": reason,
            "market_context": market_context or {},
            "market_context_hash": market_context_hash,
            "symbol_overrides": symbol_overrides or {},
            "symbol_overrides_hash": symbol_overrides_hash,
            "prediction_cache_status": prediction_status or {},
            "prediction_cache_status_hash": prediction_status_hash,
            "policy_artifact_refs": self._policy_artifact_refs(),
            "source_timestamps": self._source_timestamps(market_context or {}),
        }
        archive_json = json.dumps(payload, sort_keys=True, default=str, indent=2)
        archive_hash = _sha256_text(archive_json)
        out_dir = self.base_dir / "data_archive" / "point_in_time" / archive_date
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_ts = archived_at.replace(":", "").replace("-", "")[:15] + "Z"
        archive_path = out_dir / f"{safe_ts}_{archive_hash[:12]}.json"
        archive_path.write_text(archive_json)
        return PointInTimeArchiveResult(
            archive_path=archive_path,
            archive_hash=archive_hash,
            payload=payload,
        )

    def _policy_artifact_refs(self) -> dict[str, Any]:
        refs = {}
        for path in sorted((self.base_dir / "policy_artifacts").glob("*")):
            if not path.is_file():
                continue
            refs[path.name] = {
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_text(path.read_text(errors="replace")),
            }
        return refs

    @staticmethod
    def _source_timestamps(market_context: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "generated_at",
            "intraday_refresh_at",
            "market_context_date",
            "source_timestamp",
        )
        return {key: market_context.get(key) for key in keys if market_context.get(key)}
