"""Operator report for full-session paper replay diagnostics."""

from __future__ import annotations

from services.full_session_paper_replay_service import (
    FullSessionReplayConfig,
    build_full_session_paper_replay_payload,
)


def run_full_session_paper_replay_report(
    *,
    symbols: tuple[str, ...],
    events_per_symbol_per_minute: int = 1,
    session_minutes: int = 390,
    concurrency: int = 4,
    execute: bool = False,
    max_execute_requests: int = 1000,
) -> bool:
    payload = build_full_session_paper_replay_payload(
        FullSessionReplayConfig(
            symbols=symbols,
            events_per_symbol_per_minute=events_per_symbol_per_minute,
            session_minutes=session_minutes,
            concurrency=concurrency,
            execute=execute,
            max_execute_requests=max_execute_requests,
        )
    )
    print()
    print("=" * 72)
    print("  Full-Session Paper Replay")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"symbol_count            : {payload['symbol_count']}")
    print(f"session_minutes         : {payload['session_minutes']}")
    print(f"events_per_symbol_min   : {payload['events_per_symbol_per_minute']}")
    print(f"planned_requests        : {payload['planned_requests']}")
    print(f"execute                 : {payload['execute']}")
    print(f"execution_cap           : {payload['execution_cap']}")
    print(f"executed_requests       : {payload['executed_requests']}")
    if payload["replay_result"]:
        replay = payload["replay_result"]
        print(f"replay_passed           : {replay['passed']}")
        print(f"replay_ok_count         : {replay['ok_count']}")
        print(f"replay_failed_count     : {replay['failed_count']}")
        print(f"latency_ms_p95          : {replay['latency_ms_p95']}")
    print()
    for note in payload["notes"]:
        print(f"  note: {note}")
    print()
    if payload["ready"]:
        print("[OK] full-session paper replay diagnostic is ready")
        return True
    print("[WARN] full-session paper replay diagnostic found blockers")
    return False
