"""Local diagnostic load probes for HTTP routing.

These probes intentionally stop at route/dependency boundaries. They validate
that request parsing and callback wiring hold under bursty local traffic without
submitting orders, touching broker APIs, or mutating trading state.
"""

from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from threading import Lock
from typing import Any

from flask import Flask, abort

from api.register_routes import RouteRegistrationDeps, register_routes
from symbols_config import APPROVED_SYMBOLS, PRICE_RANGES


@dataclass(frozen=True)
class LoadProbeConfig:
    requests: int = 100
    concurrency: int = 4
    symbol: str = "AAPL"
    action: str = "buy"
    secret: str = "local-load-probe-secret"


def _safe_price(symbol: str) -> float:
    low, high = PRICE_RANGES.get(symbol, (100.0, 200.0))
    return round((low + high) / 2, 2)


class _ProbeLogger:
    def warning(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def error(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def info(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _build_probe_app(config: LoadProbeConfig, counters: dict[str, int], lock: Lock) -> Flask:
    app = Flask("local_load_probe")

    def validate_secret(req: Any) -> None:
        if req.headers.get("X-Webhook-Secret") != config.secret:
            abort(401)

    def record_webhook_event(_dedupe_key: str, _payload: dict[str, Any]) -> bool:
        with lock:
            counters["recorded"] += 1
        return True

    def mark_webhook_event_status(*_args: Any, **_kwargs: Any) -> None:
        with lock:
            counters["marked"] += 1

    def submit_signal(_payload: dict[str, Any]) -> None:
        with lock:
            counters["submitted"] += 1

    register_routes(
        app,
        RouteRegistrationDeps(
            validate_secret=validate_secret,
            approved_symbols=set(APPROVED_SYMBOLS),
            price_ranges=dict(PRICE_RANGES),
            logger=_ProbeLogger(),
            make_dedupe_key=lambda payload: f"{payload.get('symbol')}:{payload.get('action')}",
            record_webhook_event=record_webhook_event,
            mark_webhook_event_status=mark_webhook_event_status,
            submit_signal=submit_signal,
            health_payload=lambda: {"status": "ok"},
            status_payload=lambda: {"status": "ok"},
            positions_payload=lambda: {"positions": []},
            debug_symbol_payload=lambda symbol: {"symbol": symbol},
        ),
    )
    app.testing = True
    return app


def run_local_webhook_load_probe(config: LoadProbeConfig) -> dict[str, Any]:
    requests = max(1, int(config.requests))
    concurrency = max(1, min(int(config.concurrency), requests))
    symbol = config.symbol.upper()
    action = config.action.lower()
    payload = {
        "symbol": symbol,
        "action": action,
        "price": _safe_price(symbol),
        "source": "local_load_probe",
    }
    counters = {"recorded": 0, "marked": 0, "submitted": 0}
    lock = Lock()
    app = _build_probe_app(
        LoadProbeConfig(
            requests=requests,
            concurrency=concurrency,
            symbol=symbol,
            action=action,
            secret=config.secret,
        ),
        counters,
        lock,
    )

    def post_one(index: int) -> tuple[int, float]:
        request_payload = dict(payload, dedupe_key=f"local-load-probe-{index}")
        start = time.perf_counter()
        with app.test_client() as client:
            response = client.post(
                "/webhook",
                headers={"X-Webhook-Secret": config.secret},
                json=request_payload,
            )
        return response.status_code, (time.perf_counter() - start) * 1000

    started = time.perf_counter()
    latencies_ms: list[float] = []
    status_counts: dict[int, int] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(post_one, index) for index in range(requests)]
        for future in as_completed(futures):
            status_code, latency_ms = future.result()
            latencies_ms.append(latency_ms)
            status_counts[status_code] = status_counts.get(status_code, 0) + 1

    elapsed_sec = max(time.perf_counter() - started, 0.000001)
    sorted_latencies = sorted(latencies_ms)
    p95_index = min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95))
    ok_count = status_counts.get(200, 0)
    failed_count = requests - ok_count
    return {
        "report_version": "local_webhook_load_probe_v1",
        "runtime_effect": "diagnostic_only_no_order_submission",
        "requests": requests,
        "concurrency": concurrency,
        "symbol": symbol,
        "action": action,
        "ok_count": ok_count,
        "failed_count": failed_count,
        "status_counts": status_counts,
        "requests_per_second": round(requests / elapsed_sec, 2),
        "latency_ms_avg": round(statistics.fmean(latencies_ms), 3),
        "latency_ms_p95": round(sorted_latencies[p95_index], 3),
        "latency_ms_max": round(max(latencies_ms), 3),
        "callbacks": counters,
        "passed": failed_count == 0
        and counters["recorded"] == requests
        and counters["submitted"] == requests,
    }
