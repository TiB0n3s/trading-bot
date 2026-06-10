"""Async TimescaleDB tick writer.

This service is optional infrastructure. It writes market ticks/features only
when TIMESCALE_DB_URI is configured and asyncpg is installed. It never places
orders and should run outside the live order path.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from services.async_ai_pipeline_architecture_service import TIMESCALE_TICK_SCHEMA_SQL

TIMESCALE_TICK_WRITER_VERSION = "timescale_tick_writer_v1"


@dataclass(frozen=True)
class TimescaleWriteResult:
    version: str
    ok: bool
    enabled: bool
    rows_written: int
    reason: str
    runtime_effect: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def timescale_enabled() -> bool:
    return bool(os.getenv("TIMESCALE_DB_URI"))


def _disabled(reason: str) -> TimescaleWriteResult:
    return TimescaleWriteResult(
        version=TIMESCALE_TICK_WRITER_VERSION,
        ok=False,
        enabled=False,
        rows_written=0,
        reason=reason,
        runtime_effect="optional_async_storage_no_trade_authority",
    )


async def ensure_timescale_schema(db_uri: str | None = None) -> TimescaleWriteResult:
    uri = db_uri or os.getenv("TIMESCALE_DB_URI")
    if not uri:
        return _disabled("TIMESCALE_DB_URI not configured")
    try:
        import asyncpg
    except Exception as exc:
        return _disabled(f"asyncpg unavailable: {exc}")

    conn = await asyncpg.connect(uri)
    try:
        for statement in [
            part.strip() for part in TIMESCALE_TICK_SCHEMA_SQL.split(";") if part.strip()
        ]:
            await conn.execute(statement)
    finally:
        await conn.close()
    return TimescaleWriteResult(
        version=TIMESCALE_TICK_WRITER_VERSION,
        ok=True,
        enabled=True,
        rows_written=0,
        reason="schema ready",
        runtime_effect="optional_async_storage_no_trade_authority",
    )


async def write_ticks(
    ticks: list[dict[str, Any]],
    *,
    db_uri: str | None = None,
) -> TimescaleWriteResult:
    uri = db_uri or os.getenv("TIMESCALE_DB_URI")
    if not uri:
        return _disabled("TIMESCALE_DB_URI not configured")
    try:
        import asyncpg
    except Exception as exc:
        return _disabled(f"asyncpg unavailable: {exc}")
    if not ticks:
        return TimescaleWriteResult(
            version=TIMESCALE_TICK_WRITER_VERSION,
            ok=True,
            enabled=True,
            rows_written=0,
            reason="no ticks supplied",
            runtime_effect="optional_async_storage_no_trade_authority",
        )

    rows = []
    for tick in ticks:
        ts = tick.get("timestamp") or datetime.now(timezone.utc)
        if isinstance(ts, str):
            ts_value = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            ts_value = ts
        rows.append(
            (
                ts_value,
                str(tick.get("ticker") or tick.get("symbol") or "").upper(),
                float(tick.get("price")),
                int(tick.get("volume") or 0),
            )
        )

    pool = await asyncpg.create_pool(uri, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO stock_ticks (timestamp, ticker, price, volume)
                VALUES ($1, $2, $3, $4)
                """,
                rows,
            )
    finally:
        await pool.close()

    return TimescaleWriteResult(
        version=TIMESCALE_TICK_WRITER_VERSION,
        ok=True,
        enabled=True,
        rows_written=len(rows),
        reason="ticks written",
        runtime_effect="optional_async_storage_no_trade_authority",
    )


def write_ticks_sync(
    ticks: list[dict[str, Any]],
    *,
    db_uri: str | None = None,
) -> dict[str, Any]:
    """Synchronous wrapper for cron-style collectors."""
    import asyncio

    return asyncio.run(write_ticks(ticks, db_uri=db_uri)).to_dict()
