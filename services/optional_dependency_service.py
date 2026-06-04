"""Optional AI/infra dependency readiness checks."""

from __future__ import annotations

import importlib.util
from typing import Any


OPTIONAL_AI_DEPENDENCIES = {
    "numpy": "array_math",
    "pandas": "dataframe_feature_pipeline",
    "alpaca": "alpaca_py_live_bar_streaming",
    "yfinance": "free_historical_daily_market_data",
    "sklearn": "random_forest_and_classical_ml",
    "xgboost": "gradient_boosted_tree_model",
    "lightgbm": "gradient_boosted_tree_model",
    "torch": "lstm_transformer_models",
    "hmmlearn": "hmm_regime_detection",
    "transformers": "finbert_sentiment",
    "bs4": "html_news_scraping",
    "scrapy": "crawler_news_scraping",
    "asyncpg": "async_timescale_writer",
    "celery": "distributed_task_queue",
    "redis": "queue_broker_and_lock_state",
    "vectorbt": "vectorized_backtesting",
    "backtrader": "event_driven_backtesting",
}


def optional_dependency_status() -> dict[str, Any]:
    packages = {}
    missing = []
    available = []
    for module_name, capability in OPTIONAL_AI_DEPENDENCIES.items():
        present = importlib.util.find_spec(module_name) is not None
        packages[module_name] = {
            "available": present,
            "capability": capability,
        }
        if present:
            available.append(module_name)
        else:
            missing.append(module_name)

    return {
        "runtime_effect": "readiness_only_no_import_side_effects",
        "available_count": len(available),
        "missing_count": len(missing),
        "available": available,
        "missing": missing,
        "packages": packages,
        "install_policy": (
            "optional dependencies must be installed and validated outside the "
            "order path before any live authority is enabled"
        ),
    }
