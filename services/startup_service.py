"""Startup orchestration for the trading app."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class StartupDeps:
    container: Any
    logger: Any
    init_core_tables: Callable[[], Any]
    ensure_recent_favorable_setups_table: Callable[[], Any]
    prune_recent_favorable_setups: Callable[[int], Any]
    recent_favorable_setup_ttl_minutes: int
    init_session_momentum_table: Callable[[], Any]
    init_db_performance_indexes: Callable[[], Any]
    start_prediction_cache_loader: Callable[[], Any]
    prediction_cache_status: Callable[[], Any]
    get_signal_executor: Callable[[], Any]
    load_symbol_overrides: Callable[[], Any]
    build_trend_table: Callable[[], Any]
    hydrate_cooldowns: Callable[[], Any]
    hydrate_recent_sells: Callable[[], Any]
    load_market_context: Callable[[], Any]
    env_get: Callable[[str], str | None]
    required_env_keys: tuple[str, ...] = (
        "ANTHROPIC_API_KEY",
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
    )


class StartupService:
    def __init__(self, deps: StartupDeps):
        self.deps = deps
        self.log = deps.logger

    def run(self) -> None:
        self._run_step("DB init", self.deps.init_core_tables)
        self._run_step("Recent favorable setups init", self._init_recent_favorable_setups)
        self._run_step("Session momentum table initialization", self.deps.init_session_momentum_table)
        self._run_step("DB performance index initialization", self._init_performance_indexes)
        self._run_step("Prediction cache loader startup", self._start_prediction_cache_loader)
        self._run_step("Signal executor startup", self.deps.get_signal_executor)
        self._run_step("Startup reconciliation hook", self.reconcile_positions)
        self._run_step("Symbol override startup load", self.deps.load_symbol_overrides)
        self._run_step("Trend-table startup build", self.deps.build_trend_table)
        self._run_step("Cooldown startup hydration", self.deps.hydrate_cooldowns)
        self._run_step("Recent-sell startup hydration", self.deps.hydrate_recent_sells)
        self._run_step("Market-context startup load", self.deps.load_market_context)

    def _run_step(self, label: str, func: Callable[[], Any]) -> None:
        try:
            func()
        except Exception as exc:
            self.log.error(f"{label} failed: {exc}")

    def _init_recent_favorable_setups(self) -> None:
        self.deps.ensure_recent_favorable_setups_table()
        self.deps.prune_recent_favorable_setups(
            self.deps.recent_favorable_setup_ttl_minutes
        )

    def _init_performance_indexes(self) -> None:
        self.deps.init_db_performance_indexes()
        self.log.info("DB performance indexes initialized")

    def _start_prediction_cache_loader(self) -> None:
        self.deps.start_prediction_cache_loader()
        self.log.info(f"Prediction cache loader started: {self.deps.prediction_cache_status()}")

    def reconcile_positions(self) -> None:
        try:
            for key in self.deps.required_env_keys:
                if not self.deps.env_get(key):
                    self.log.error(f"Startup: missing required environment variable {key}")

            try:
                alpaca_positions = self.deps.container.broker_service.list_positions()
                alpaca_symbols = {p.symbol for p in alpaca_positions}
            except Exception as exc:
                self.log.error(
                    f"Startup reconciliation: failed to fetch Alpaca positions: {exc}"
                )
                alpaca_symbols = set()
                alpaca_positions = []

            try:
                rows = self.deps.container.repositories.context.startup_db_open_symbols()
                db_symbols = {row["symbol"] for row in rows if row["symbol"]}
            except Exception as exc:
                self.log.error(f"Startup reconciliation: failed to query trades.db: {exc}")
                db_symbols = set()

            in_alpaca_not_db = alpaca_symbols - db_symbols
            in_db_not_alpaca = db_symbols - alpaca_symbols
            for sym in sorted(in_alpaca_not_db):
                self.log.warning(
                    "Startup reconciliation: "
                    f"{sym} held in Alpaca but no open position tracked in trades.db"
                )
            for sym in sorted(in_db_not_alpaca):
                self.log.warning(
                    "Startup reconciliation: "
                    f"{sym} tracked as open in trades.db but not found in Alpaca positions"
                )

            discrepancies = len(in_alpaca_not_db) + len(in_db_not_alpaca)
            self.log.info(
                f"Startup reconciliation: {len(alpaca_symbols)} positions in Alpaca, "
                f"{len(db_symbols)} tracked in DB, {discrepancies} discrepancies"
            )
        except Exception as exc:
            self.log.error(f"Startup reconciliation failed unexpectedly: {exc}")
