"""Runtime startup wiring for the deployed compatibility module."""

from __future__ import annotations

from types import ModuleType
from typing import Any

from prediction_cache import start_prediction_cache_loader
from repositories import context_repo
from services.startup_service import StartupDeps, StartupService
from session_momentum import init_session_momentum_table


def build_runtime_startup_service(
    runtime_module: ModuleType,
    *,
    app_container: Any | None = None,
) -> StartupService:
    """Build startup orchestration against the current runtime context."""
    app_container = app_container or runtime_module.container
    return StartupService(
        StartupDeps(
            container=app_container,
            logger=runtime_module.logger,
            init_core_tables=lambda: context_repo.init_core_tables(runtime_module.DB_PATH),
            ensure_recent_favorable_setups_table=(
                context_repo.ensure_recent_favorable_setups_table
            ),
            prune_recent_favorable_setups=context_repo.prune_recent_favorable_setups,
            recent_favorable_setup_ttl_minutes=(runtime_module.RECENT_FAVORABLE_SETUP_TTL_MINUTES),
            init_session_momentum_table=init_session_momentum_table,
            init_db_performance_indexes=context_repo.init_db_performance_indexes,
            start_prediction_cache_loader=start_prediction_cache_loader,
            prediction_cache_status=runtime_module.prediction_cache_status,
            get_signal_executor=runtime_module._get_signal_executor,
            load_symbol_overrides=runtime_module._load_symbol_overrides,
            build_trend_table=runtime_module._build_trend_table,
            hydrate_cooldowns=runtime_module._hydrate_cooldowns,
            hydrate_recent_sells=runtime_module._hydrate_recent_sells,
            load_market_context=runtime_module._load_market_context,
            env_get=runtime_module.os.environ.get,
            ml_authority_config=runtime_module.public_ml_authority_config,
        )
    )


def run_runtime_startup_tasks(
    runtime_module: ModuleType,
    *,
    app_container: Any | None = None,
) -> None:
    """Run startup tasks and update the runtime compatibility flag."""
    build_runtime_startup_service(
        runtime_module,
        app_container=app_container,
    ).run()
    runtime_module._STARTUP_TASKS_RAN = True
