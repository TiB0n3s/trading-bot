"""Structured exception types for trading-bot boundaries."""

from __future__ import annotations


class TradingBotError(Exception):
    """Base class for expected trading-bot errors."""


class ValidationError(TradingBotError):
    """Invalid user, signal, order, or config input."""


class BrokerError(TradingBotError):
    """Broker/API operation failed."""


class BrokerAuthError(BrokerError):
    """Broker credentials or authorization failed."""


class BrokerRateLimitError(BrokerError):
    """Broker/API rate limit was encountered."""


class BrokerTransientError(BrokerError):
    """Broker/API operation may succeed if retried later."""


class DataAccessError(TradingBotError):
    """Database or file-backed state operation failed."""
