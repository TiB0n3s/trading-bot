"""Signal-processing gate configuration (app.py inbound webhook path)."""

from __future__ import annotations

from dataclasses import dataclass

from config._env import _check, env_bool, env_float, env_int, env_str
from trading_bot.config.authority_modes import (
    authority_mode_to_legacy_prediction_gate,
    normalize_config_authority_mode,
)

_VALID_GATE_MODES = {"warn", "block", "off", "soft", "hard"}


@dataclass(frozen=True)
class SignalConfig:
    # Prediction gate
    prediction_gate_mode: str = "warn"
    prediction_soft_avoid_min_sample: int = 20

    # Intra-session tape degradation
    intra_session_tape_degradation_enabled: bool = True
    intra_session_start_hour_et: int = 12
    intra_session_min_setup_score: int = 55

    # One-bar confirmation hold
    one_bar_confirmation_hold_enabled: bool = True
    one_bar_confirmation_extension_threshold_pct: float = 0.25
    one_bar_confirmation_timeout_seconds: int = 75

    # Tape exception and fast-lane bypasses
    tape_exception_enabled: bool = True
    open_momentum_fast_lane_enabled: bool = True

    # Second-look (pre-order price/spread checks)
    max_signal_price_drift_pct: float = 0.35
    max_bid_ask_spread_pct: float = 0.10

    # Sell continuation check
    sell_continuation_check_enabled: bool = True
    sell_continuation_min_supports: int = 2

    # Session caps
    session_max_trade_count: int = 3
    signal_worker_count: int = 3

    # Late-quote delay thresholds (inline reads in app.py)
    late_quote_delay_min_blocks: int = 3
    late_quote_delay_min_session_return_pct: float = 0.75
    late_quote_delay_max_session_score: float = 5.0

    def __post_init__(self) -> None:
        _check(
            self.prediction_gate_mode in _VALID_GATE_MODES,
            "prediction_gate_mode",
            "PREDICTION_GATE_MODE",
            self.prediction_gate_mode,
            f"must be one of {sorted(_VALID_GATE_MODES)}",
        )
        _check(
            self.prediction_soft_avoid_min_sample >= 1,
            "prediction_soft_avoid_min_sample",
            "PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE",
            self.prediction_soft_avoid_min_sample,
            "must be >= 1",
        )
        _check(
            0 <= self.intra_session_start_hour_et <= 23,
            "intra_session_start_hour_et",
            "INTRA_SESSION_TAPE_DEGRADATION_START_HOUR_ET",
            self.intra_session_start_hour_et,
            "must be in [0, 23]",
        )
        _check(
            0 <= self.intra_session_min_setup_score <= 100,
            "intra_session_min_setup_score",
            "INTRA_SESSION_TAPE_DEGRADATION_MIN_SETUP_SCORE",
            self.intra_session_min_setup_score,
            "must be in [0, 100]",
        )
        _check(
            self.one_bar_confirmation_extension_threshold_pct >= 0.0,
            "one_bar_confirmation_extension_threshold_pct",
            "ONE_BAR_CONFIRMATION_EXTENSION_THRESHOLD_PCT",
            self.one_bar_confirmation_extension_threshold_pct,
            "must be >= 0.0",
        )
        _check(
            self.one_bar_confirmation_timeout_seconds >= 1,
            "one_bar_confirmation_timeout_seconds",
            "ONE_BAR_CONFIRMATION_TIMEOUT_SECONDS",
            self.one_bar_confirmation_timeout_seconds,
            "must be >= 1",
        )
        _check(
            self.max_signal_price_drift_pct >= 0.0,
            "max_signal_price_drift_pct",
            "MAX_SIGNAL_PRICE_DRIFT_PCT",
            self.max_signal_price_drift_pct,
            "must be >= 0.0",
        )
        _check(
            self.max_bid_ask_spread_pct >= 0.0,
            "max_bid_ask_spread_pct",
            "MAX_BID_ASK_SPREAD_PCT",
            self.max_bid_ask_spread_pct,
            "must be >= 0.0",
        )
        _check(
            self.sell_continuation_min_supports >= 1,
            "sell_continuation_min_supports",
            "SELL_CONTINUATION_MIN_SUPPORTS",
            self.sell_continuation_min_supports,
            "must be >= 1",
        )
        _check(
            self.session_max_trade_count >= 1,
            "session_max_trade_count",
            "SESSION_MAX_TRADE_COUNT",
            self.session_max_trade_count,
            "must be >= 1",
        )
        _check(
            self.signal_worker_count >= 1,
            "signal_worker_count",
            "SIGNAL_WORKER_COUNT",
            self.signal_worker_count,
            "must be >= 1",
        )
        _check(
            self.late_quote_delay_min_blocks >= 0,
            "late_quote_delay_min_blocks",
            "LATE_QUOTE_DELAY_MIN_BLOCKS",
            self.late_quote_delay_min_blocks,
            "must be >= 0",
        )


def load_signal_config(**overrides) -> SignalConfig:
    """Construct SignalConfig from current env, with optional kwarg overrides.

    Production code uses the ``signal_cfg`` singleton from ``config``.
    Tests call this factory directly after patching env (or pass overrides)
    to get a fresh instance without touching the singleton.

    Example::

        cfg = load_signal_config(prediction_gate_mode="block")
    """
    kwargs: dict = dict(
        prediction_gate_mode=authority_mode_to_legacy_prediction_gate(
            normalize_config_authority_mode(
                env_str("PREDICTION_GATE_MODE", "warn"),
                default="warn",
            )
        ).replace("hard", "block"),
        prediction_soft_avoid_min_sample=env_int("PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE", 20),
        intra_session_tape_degradation_enabled=env_bool(
            "INTRA_SESSION_TAPE_DEGRADATION_ENABLED", True
        ),
        intra_session_start_hour_et=int(
            env_float("INTRA_SESSION_TAPE_DEGRADATION_START_HOUR_ET", 12)
        ),
        intra_session_min_setup_score=int(
            env_float("INTRA_SESSION_TAPE_DEGRADATION_MIN_SETUP_SCORE", 55)
        ),
        one_bar_confirmation_hold_enabled=env_bool("ONE_BAR_CONFIRMATION_HOLD_ENABLED", True),
        one_bar_confirmation_extension_threshold_pct=env_float(
            "ONE_BAR_CONFIRMATION_EXTENSION_THRESHOLD_PCT", 0.25
        ),
        one_bar_confirmation_timeout_seconds=env_int("ONE_BAR_CONFIRMATION_TIMEOUT_SECONDS", 75),
        tape_exception_enabled=env_bool("TAPE_EXCEPTION_ENABLED", True),
        open_momentum_fast_lane_enabled=env_bool("OPEN_MOMENTUM_FAST_LANE_ENABLED", True),
        max_signal_price_drift_pct=env_float("MAX_SIGNAL_PRICE_DRIFT_PCT", 0.35),
        max_bid_ask_spread_pct=env_float("MAX_BID_ASK_SPREAD_PCT", 0.10),
        sell_continuation_check_enabled=env_bool("SELL_CONTINUATION_CHECK_ENABLED", True),
        sell_continuation_min_supports=env_int("SELL_CONTINUATION_MIN_SUPPORTS", 2),
        session_max_trade_count=env_int("SESSION_MAX_TRADE_COUNT", 3),
        signal_worker_count=env_int("SIGNAL_WORKER_COUNT", 3),
        late_quote_delay_min_blocks=env_int("LATE_QUOTE_DELAY_MIN_BLOCKS", 3),
        late_quote_delay_min_session_return_pct=env_float(
            "LATE_QUOTE_DELAY_MIN_SESSION_RETURN_PCT", 0.75
        ),
        late_quote_delay_max_session_score=env_float("LATE_QUOTE_DELAY_MAX_SESSION_SCORE", 5.0),
    )
    kwargs.update(overrides)
    return SignalConfig(**kwargs)
