"""End-to-end paper replay/load probe with local DB and fill callbacks."""

from __future__ import annotations

import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from repositories.paper_replay_probe_repo import count_rows, init_probe_db, record_signal_and_fill
from services.local_load_probe_service import LoadProbeConfig, _build_probe_app, _safe_price


@dataclass(frozen=True)
class PaperReplayLoadProbeConfig:
    requests: int = 100
    concurrency: int = 4
    symbol: str = "AAPL"
    action: str = "buy"
    db_path: Path | None = None


def run_paper_replay_load_probe(config: PaperReplayLoadProbeConfig) -> dict[str, Any]:
    requests = max(1, int(config.requests))
    concurrency = max(1, min(int(config.concurrency), requests))
    symbol = config.symbol.upper()
    action = config.action.lower()
    temp_dir_ctx = tempfile.TemporaryDirectory() if config.db_path is None else None
    db_path = config.db_path or Path(temp_dir_ctx.name) / "paper_replay_probe.db"  # type: ignore[union-attr]
    init_probe_db(db_path)
    lock = Lock()
    counters = {"recorded": 0, "marked": 0, "submitted": 0}
    app = _build_probe_app(
        LoadProbeConfig(
            requests=requests,
            concurrency=concurrency,
            symbol=symbol,
            action=action,
        ),
        counters,
        lock,
    )
    base_price = _safe_price(symbol)

    def post_one(index: int) -> tuple[int, float]:
        dedupe_key = f"paper-replay-load-probe-{index}"
        payload = {
            "symbol": symbol,
            "action": action,
            "price": base_price,
            "dedupe_key": dedupe_key,
            "source": "paper_replay_load_probe",
        }
        start = time.perf_counter()
        with app.test_client() as client:
            response = client.post(
                "/webhook",
                headers={"X-Webhook-Secret": "local-load-probe-secret"},
                json=payload,
            )
        record_signal_and_fill(
            db_path,
            dedupe_key=dedupe_key,
            symbol=symbol,
            action=action,
            price=base_price,
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
    signal_rows = count_rows(db_path, "paper_replay_signals")
    fill_rows = count_rows(db_path, "paper_replay_fills")
    if temp_dir_ctx is not None:
        temp_dir_ctx.cleanup()
    return {
        "report_version": "paper_replay_load_probe_v1",
        "runtime_effect": "diagnostic_only_temp_db_no_broker_orders",
        "requests": requests,
        "concurrency": concurrency,
        "symbol": symbol,
        "action": action,
        "ok_count": status_counts.get(200, 0),
        "failed_count": requests - status_counts.get(200, 0),
        "status_counts": status_counts,
        "signal_rows": signal_rows,
        "fill_rows": fill_rows,
        "requests_per_second": round(requests / elapsed_sec, 2),
        "latency_ms_avg": round(statistics.fmean(latencies_ms), 3),
        "latency_ms_p95": round(sorted_latencies[p95_index], 3),
        "latency_ms_max": round(max(latencies_ms), 3),
        "passed": status_counts.get(200, 0) == requests
        and signal_rows == requests
        and fill_rows == requests,
    }
