"""Operator command for local webhook load diagnostics."""

from __future__ import annotations

from services.local_load_probe_service import LoadProbeConfig, run_local_webhook_load_probe


def run_local_load_probe_report(
    *,
    requests: int = 100,
    concurrency: int = 4,
    symbol: str = "AAPL",
    action: str = "buy",
) -> bool:
    payload = run_local_webhook_load_probe(
        LoadProbeConfig(
            requests=requests,
            concurrency=concurrency,
            symbol=symbol,
            action=action,
        )
    )

    print()
    print("=" * 72)
    print("  Local Webhook Load Probe")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"symbol                  : {payload['symbol']}")
    print(f"action                  : {payload['action']}")
    print(f"requests                : {payload['requests']}")
    print(f"concurrency             : {payload['concurrency']}")
    print(f"ok_count                : {payload['ok_count']}")
    print(f"failed_count            : {payload['failed_count']}")
    print(f"requests_per_second     : {payload['requests_per_second']}")
    print(f"latency_ms_avg          : {payload['latency_ms_avg']}")
    print(f"latency_ms_p95          : {payload['latency_ms_p95']}")
    print(f"latency_ms_max          : {payload['latency_ms_max']}")
    print(f"status_counts           : {payload['status_counts']}")
    print(f"callbacks               : {payload['callbacks']}")
    print()
    if payload["passed"]:
        print("[OK] local webhook load probe completed without route/callback failures")
        return True
    print("[FAIL] local webhook load probe found route/callback failures")
    return False
