"""Application composition root.

This module owns construction of runtime services and repositories. Flask route
registration and signal processing receive dependencies from this container
instead of importing concrete singletons directly.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Callable

import broker
from repositories import context_repo, cooldown_repo, rejections_repo, snapshots_repo, trades_repo
from services.broker_service import BrokerService
from services.market_data_service import MarketDataService
from services.signal_pipeline import SignalPipeline, SignalPipelineDeps
from services.tape_service import TapeService


@dataclass
class RepositoryContainer:
    trades: object
    rejections: object
    snapshots: object
    context: object
    cooldowns: object


class ApplicationContainer:
    def __init__(
        self,
        *,
        logger: logging.Logger,
        broker_service: BrokerService,
        market_data_service: MarketDataService,
        tape_service: TapeService,
        repositories: RepositoryContainer,
        signal_executor_factory: Callable[[], object],
    ):
        self.logger = logger
        self.broker_service = broker_service
        self.market_data_service = market_data_service
        self.tape_service = tape_service
        self.repositories = repositories
        self.signal_executor_factory = signal_executor_factory

    @classmethod
    def create_default(
        cls,
        *,
        logger: logging.Logger,
        signal_executor_factory: Callable[[], object],
    ) -> "ApplicationContainer":
        market_data = MarketDataService(client=broker.api, log=logger)
        return cls(
            logger=logger,
            broker_service=BrokerService(broker_module=broker),
            market_data_service=market_data,
            tape_service=TapeService(market_data),
            repositories=RepositoryContainer(
                trades=trades_repo,
                rejections=rejections_repo,
                snapshots=snapshots_repo,
                context=context_repo,
                cooldowns=cooldown_repo,
            ),
            signal_executor_factory=signal_executor_factory,
        )

    def build_signal_pipeline(self, deps: SignalPipelineDeps) -> SignalPipeline:
        return SignalPipeline(deps)
