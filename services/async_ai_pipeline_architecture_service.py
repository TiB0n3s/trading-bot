"""Async AI pipeline and storage architecture contracts."""

from __future__ import annotations

from typing import Any


ASYNC_AI_PIPELINE_VERSION = "async_ai_pipeline_architecture_v1"

TIMESCALE_TICK_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stock_ticks (
    timestamp TIMESTAMPTZ NOT NULL,
    ticker VARCHAR(10) NOT NULL,
    price NUMERIC NOT NULL,
    volume INT NOT NULL
);

SELECT create_hypertable('stock_ticks', 'timestamp', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_stock_ticks_ticker_timestamp
ON stock_ticks (ticker, timestamp DESC);
""".strip()


def async_pipeline_contract() -> dict[str, Any]:
    return {
        "version": ASYNC_AI_PIPELINE_VERSION,
        "runtime_effect": "architecture_contract_no_background_worker_started",
        "flow": [
            "alpaca_websocket_ingest",
            "async_queue_or_event_loop",
            "timescale_or_sqlite_feature_store",
            "background_feature_generation",
            "model_prediction_cache",
            "alpaca_rest_execution_engine",
        ],
        "storage": {
            "preferred": "timescale_db",
            "current_repo_default": "sqlite",
            "timescale_schema_sql": TIMESCALE_TICK_SCHEMA_SQL,
            "feature_store_candidate": "feast",
            "status": "contract_defined_not_installed",
        },
        "task_queue": {
            "preferred": "celery_redis",
            "fallback": "asyncio_background_tasks",
            "rule": "heavy ML/NLP work must not run inside order submission path",
            "status": "contract_defined_not_started",
        },
        "backtesting": {
            "preferred": "vectorbt",
            "fallback": "existing_policy_backtest_and_reports",
            "promotion_rule": "model must pass offline validation before live authority",
        },
        "guardrails": {
            "prediction_reads_memory_only": True,
            "order_path_no_network_ml_calls": True,
            "fail_open_to_no_prediction": True,
        },
    }
