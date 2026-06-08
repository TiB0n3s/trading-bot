"""Full-session paper replay planning and bounded local execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.paper_replay_load_probe_service import (
    PaperReplayLoadProbeConfig,
    run_paper_replay_load_probe,
)

REGULAR_SESSION_MINUTES = 390


@dataclass(frozen=True)
class FullSessionReplayConfig:
    symbols: tuple[str, ...] = ("AAPL",)
    events_per_symbol_per_minute: int = 1
    session_minutes: int = REGULAR_SESSION_MINUTES
    concurrency: int = 4
    execute: bool = False
    max_execute_requests: int = 1000


def build_full_session_paper_replay_payload(config: FullSessionReplayConfig) -> dict[str, Any]:
    symbols = tuple(symbol.upper() for symbol in config.symbols if symbol.strip())
    symbol_count = len(symbols)
    session_minutes = max(1, int(config.session_minutes))
    events_per_symbol_per_minute = max(1, int(config.events_per_symbol_per_minute))
    planned_requests = symbol_count * session_minutes * events_per_symbol_per_minute
    execution_cap = max(1, int(config.max_execute_requests))
    executed_requests = min(planned_requests, execution_cap) if config.execute else 0
    replay_result = None
    if config.execute and executed_requests:
        replay_result = run_paper_replay_load_probe(
            PaperReplayLoadProbeConfig(
                requests=executed_requests,
                concurrency=config.concurrency,
                symbol=symbols[0],
                action="buy",
            )
        )
    return {
        "report_version": "full_session_paper_replay_v1",
        "runtime_effect": "diagnostic_only_no_broker_orders",
        "symbols": list(symbols),
        "symbol_count": symbol_count,
        "session_minutes": session_minutes,
        "events_per_symbol_per_minute": events_per_symbol_per_minute,
        "planned_requests": planned_requests,
        "execute": config.execute,
        "execution_cap": execution_cap,
        "executed_requests": executed_requests,
        "replay_result": replay_result,
        "ready": symbol_count > 0
        and planned_requests > 0
        and (not config.execute or bool(replay_result and replay_result.get("passed"))),
        "notes": [
            "This is a local paper replay diagnostic and cannot submit broker orders.",
            "Use --execute for bounded callback/database exercise; omit it for cadence planning.",
        ],
    }
