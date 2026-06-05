"""Manage non-approved external symbols as research candidates.

This service deliberately does not mutate SYMBOL_CONFIG and does not grant
trade authority. It turns repeated event references into a staged research
queue so Polygon history and ML-ready features can be built automatically.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from db import DB_PATH


EXTERNAL_SYMBOL_CANDIDATE_VERSION = "external_symbol_candidate_v1"
DEFAULT_STATE_PATH = Path("runtime_state/external_symbol_candidates.json")
DEFAULT_MIN_MENTIONS = 2
DEFAULT_MIN_TRUSTED_MENTIONS = 1
DEFAULT_MIN_BAR_ROWS = 1000
DEFAULT_MIN_BAR_DAYS = 20
DEFAULT_MIN_CONFIDENCE_SCORE = 65.0
DEFAULT_POOL_REVIEW_SCORE = 45.0

STATUS_CONTEXT_ONLY = "context_only"
STATUS_RESEARCH = "candidate_research"
STATUS_BACKFILL_PENDING = "candidate_backfill_pending"
STATUS_TRAINING_PENDING = "candidate_training_pending"
STATUS_READY_REVIEW = "candidate_ready_for_operator_review"
STATUS_POOL = "candidate_pool"
STATUS_REJECTED = "candidate_rejected"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}
    return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _coverage_for_symbols(
    *,
    db_path: Path,
    symbols: list[str],
) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    if not db_path.exists():
        return {
            symbol: {"rows": 0, "trading_days": 0, "coverage_status": "missing_db"}
            for symbol in symbols
        }

    placeholders = ",".join("?" for _ in symbols)
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bar_pattern_features'"
            ).fetchone()
            if not exists:
                return {
                    symbol: {
                        "rows": 0,
                        "trading_days": 0,
                        "coverage_status": "missing_bar_pattern_features",
                    }
                    for symbol in symbols
                }
            columns = {
                str(row["name"])
                for row in con.execute("PRAGMA table_info(bar_pattern_features)").fetchall()
            }
            timeframe_filter = "AND timeframe = '1m'" if "timeframe" in columns else ""
            rows = con.execute(
                f"""
                SELECT
                    symbol,
                    COUNT(*) AS rows,
                    COUNT(DISTINCT substr(bar_timestamp, 1, 10)) AS trading_days,
                    MIN(substr(bar_timestamp, 1, 10)) AS first_date,
                    MAX(substr(bar_timestamp, 1, 10)) AS last_date
                FROM bar_pattern_features
                WHERE symbol IN ({placeholders})
                  {timeframe_filter}
                GROUP BY symbol
                """,
                symbols,
            ).fetchall()
    except Exception as exc:
        return {
            symbol: {
                "rows": 0,
                "trading_days": 0,
                "coverage_status": f"coverage_query_failed:{type(exc).__name__}",
            }
            for symbol in symbols
        }

    observed = {
        str(row["symbol"]).upper(): {
            "rows": int(row["rows"] or 0),
            "trading_days": int(row["trading_days"] or 0),
            "first_date": row["first_date"],
            "last_date": row["last_date"],
            "coverage_status": "observed",
        }
        for row in rows
    }
    return {
        symbol: observed.get(
            symbol,
            {"rows": 0, "trading_days": 0, "coverage_status": "no_rows"},
        )
        for symbol in symbols
    }


def _confidence_score(
    *,
    mentions: int,
    trusted_mentions: int,
    linked_count: int,
    coverage: dict[str, Any],
    min_bar_rows: int,
    min_bar_days: int,
) -> float:
    row_score = min(1.0, float(coverage.get("rows") or 0) / max(1, min_bar_rows)) * 30.0
    day_score = min(1.0, float(coverage.get("trading_days") or 0) / max(1, min_bar_days)) * 25.0
    trusted_score = min(1.0, trusted_mentions / 3.0) * 20.0
    mention_score = min(1.0, mentions / 6.0) * 15.0
    linkage_score = min(1.0, linked_count / 3.0) * 10.0
    return round(row_score + day_score + trusted_score + mention_score + linkage_score, 2)


def _stage(
    *,
    symbol_class: str,
    mentions: int,
    trusted_mentions: int,
    confidence_score: float,
    coverage: dict[str, Any],
    min_mentions: int,
    min_trusted_mentions: int,
    min_bar_rows: int,
    min_bar_days: int,
    min_confidence_score: float,
    pool_review_score: float,
) -> tuple[str, str]:
    if symbol_class == "context_only":
        return STATUS_CONTEXT_ONLY, "configured context-only symbol; not eligible for automatic approval"
    if mentions < min_mentions:
        return STATUS_POOL, "below discovery mention threshold"
    if trusted_mentions < min_trusted_mentions:
        return STATUS_POOL, "below trusted-source threshold"
    rows = int(coverage.get("rows") or 0)
    days = int(coverage.get("trading_days") or 0)
    if rows < min_bar_rows or days < min_bar_days:
        return STATUS_BACKFILL_PENDING, "needs Polygon historical bar backfill"
    if confidence_score >= min_confidence_score:
        return STATUS_READY_REVIEW, "candidate evidence meets review threshold; operator approval still required"
    if confidence_score >= pool_review_score:
        return STATUS_TRAINING_PENDING, "feature history exists but candidate confidence is not review-ready"
    return STATUS_REJECTED, "candidate confidence below minimum; keep out of active research queue"


@dataclass(frozen=True)
class CandidateRefreshResult:
    report_version: str
    runtime_effect: str
    status: str
    state_path: str
    discovery_start_date: str
    discovery_end_date: str
    candidates_seen: int
    backfill_symbols: list[str]
    candidates: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExternalSymbolCandidateService:
    def __init__(
        self,
        *,
        state_path: Path | str = DEFAULT_STATE_PATH,
        db_path: Path | str = DB_PATH,
    ):
        self.state_path = Path(state_path)
        self.db_path = Path(db_path)

    def load_state(self) -> dict[str, Any]:
        state = _read_json(self.state_path)
        if not state:
            return {
                "report_version": EXTERNAL_SYMBOL_CANDIDATE_VERSION,
                "runtime_effect": "research_queue_no_trade_authority",
                "candidates": {},
                "updated_at": None,
            }
        state.setdefault("candidates", {})
        return state

    def refresh_from_discovery(
        self,
        discovery_payload: dict[str, Any],
        *,
        min_mentions: int = DEFAULT_MIN_MENTIONS,
        min_trusted_mentions: int = DEFAULT_MIN_TRUSTED_MENTIONS,
        min_bar_rows: int = DEFAULT_MIN_BAR_ROWS,
        min_bar_days: int = DEFAULT_MIN_BAR_DAYS,
        min_confidence_score: float = DEFAULT_MIN_CONFIDENCE_SCORE,
        pool_review_score: float = DEFAULT_POOL_REVIEW_SCORE,
        persist: bool = True,
    ) -> CandidateRefreshResult:
        state = self.load_state()
        candidates: dict[str, Any] = dict(state.get("candidates") or {})
        findings = discovery_payload.get("findings") or []
        symbols = sorted({
            str(row.get("symbol") or "").upper().strip()
            for row in findings
            if str(row.get("symbol") or "").strip()
        })
        coverage = _coverage_for_symbols(db_path=self.db_path, symbols=symbols)
        now = _now()

        refreshed: list[dict[str, Any]] = []
        for row in findings:
            symbol = str(row.get("symbol") or "").upper().strip()
            if not symbol:
                continue
            current = dict(candidates.get(symbol) or {})
            cov = coverage.get(symbol, {})
            linked = list(row.get("linked_approved_symbols") or [])
            score = _confidence_score(
                mentions=int(row.get("mentions") or 0),
                trusted_mentions=int(row.get("trusted_mentions") or 0),
                linked_count=len(linked),
                coverage=cov,
                min_bar_rows=min_bar_rows,
                min_bar_days=min_bar_days,
            )
            status, reason = _stage(
                symbol_class=str(row.get("symbol_class") or "unknown_external"),
                mentions=int(row.get("mentions") or 0),
                trusted_mentions=int(row.get("trusted_mentions") or 0),
                confidence_score=score,
                coverage=cov,
                min_mentions=min_mentions,
                min_trusted_mentions=min_trusted_mentions,
                min_bar_rows=min_bar_rows,
                min_bar_days=min_bar_days,
                min_confidence_score=min_confidence_score,
                pool_review_score=pool_review_score,
            )
            candidate = {
                **current,
                "symbol": symbol,
                "status": status,
                "status_reason": reason,
                "symbol_class": row.get("symbol_class"),
                "mentions": int(row.get("mentions") or 0),
                "trusted_mentions": int(row.get("trusted_mentions") or 0),
                "linked_approved_symbols": linked,
                "confidence_score": score,
                "coverage": cov,
                "latest_discovery": row,
                "first_seen_at": current.get("first_seen_at") or now,
                "updated_at": now,
                "runtime_effect": "research_only_no_trade_authority",
            }
            candidates[symbol] = candidate
            refreshed.append(candidate)

        backfill_symbols = sorted(
            candidate["symbol"]
            for candidate in refreshed
            if candidate["status"] == STATUS_BACKFILL_PENDING
        )
        state.update(
            {
                "report_version": EXTERNAL_SYMBOL_CANDIDATE_VERSION,
                "runtime_effect": "research_queue_no_trade_authority",
                "updated_at": now,
                "last_discovery_start_date": discovery_payload.get("start_date"),
                "last_discovery_end_date": discovery_payload.get("end_date"),
                "candidates": candidates,
            }
        )
        if persist:
            _write_json(self.state_path, state)

        return CandidateRefreshResult(
            report_version=EXTERNAL_SYMBOL_CANDIDATE_VERSION,
            runtime_effect="research_queue_no_trade_authority",
            status="ok",
            state_path=str(self.state_path),
            discovery_start_date=str(discovery_payload.get("start_date") or ""),
            discovery_end_date=str(discovery_payload.get("end_date") or ""),
            candidates_seen=len(refreshed),
            backfill_symbols=backfill_symbols,
            candidates=sorted(refreshed, key=lambda item: (-float(item.get("confidence_score") or 0), item["symbol"])),
        )

    def report(self, *, limit: int = 20) -> dict[str, Any]:
        state = self.load_state()
        candidates = list((state.get("candidates") or {}).values())
        candidates.sort(
            key=lambda item: (
                item.get("status") != STATUS_READY_REVIEW,
                item.get("status") != STATUS_BACKFILL_PENDING,
                -float(item.get("confidence_score") or 0),
                item.get("symbol") or "",
            )
        )
        return {
            "report_version": EXTERNAL_SYMBOL_CANDIDATE_VERSION,
            "runtime_effect": "research_queue_no_trade_authority",
            "state_path": str(self.state_path),
            "updated_at": state.get("updated_at"),
            "candidate_count": len(candidates),
            "status_counts": {
                status: sum(1 for row in candidates if row.get("status") == status)
                for status in sorted({str(row.get("status") or "unknown") for row in candidates})
            },
            "candidates": candidates[: max(1, limit)],
            "truncated": len(candidates) > limit,
        }
