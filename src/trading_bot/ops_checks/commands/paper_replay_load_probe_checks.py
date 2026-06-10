"""Operator report for end-to-end paper replay/load probe."""

from __future__ import annotations

from services.paper_replay_load_probe_service import (
    PaperReplayLoadProbeConfig,
    run_paper_replay_load_probe,
)


def run_paper_replay_load_probe_report(
    *,
    requests: int = 100,
    concurrency: int = 4,
    symbol: str = "AAPL",
    action: str = "buy",
) -> bool:
    payload = run_paper_replay_load_probe(
        PaperReplayLoadProbeConfig(
            requests=requests,
            concurrency=concurrency,
            symbol=symbol,
            action=action,
        )
    )
    print()
    print("=" * 72)
    print("  Paper Replay Load Probe")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"symbol                  : {payload['symbol']}")
    print(f"action                  : {payload['action']}")
    print(f"requests                : {payload['requests']}")
    print(f"concurrency             : {payload['concurrency']}")
    print(f"ok_count                : {payload['ok_count']}")
    print(f"failed_count            : {payload['failed_count']}")
    print(f"signal_rows             : {payload['signal_rows']}")
    print(f"fill_rows               : {payload['fill_rows']}")
    print(f"requests_per_second     : {payload['requests_per_second']}")
    print(f"latency_ms_p95          : {payload['latency_ms_p95']}")
    print(f"status_counts           : {payload['status_counts']}")
    print()
    if payload["passed"]:
        print("[OK] paper replay/load probe completed")
        return True
    print("[FAIL] paper replay/load probe found mismatches")
    return False
