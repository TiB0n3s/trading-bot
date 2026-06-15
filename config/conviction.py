"""Conviction-mode configuration.

Conviction mode reshapes the bot from a frequent scanner into a low-frequency,
high-selectivity strategy: enter only on convergence of independent evidence,
hold a single concentrated position, and exit on a trailing/structure basis
rather than a fast scalp target.

Defaults are intentionally conservative and the mode ships **disabled**. It is
also ``paper_only`` by default so it cannot affect a live/cash execution mode
until explicitly opted in. This mirrors the env-driven, frozen-dataclass
pattern used by ``config/auto_buy.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from config._env import _check, env_bool, env_float, env_int


@dataclass(frozen=True)
class ConvictionConfig:
    # --- Activation ---------------------------------------------------------
    enabled: bool = False
    # When True, the policy only takes authority while EXECUTION_MODE is a
    # paper/dry-run mode. The caller is responsible for passing the current
    # mode in; see `conviction_active_for_mode`.
    paper_only: bool = True

    # --- Entry selectivity (all are mandatory gates) ------------------------
    # Heuristic composite score bar. Calibrated near the top of observed
    # auto-buy score history so the gate can produce paper validation data
    # without accepting ordinary "best of scan" candidates.
    min_score: float = 23.0
    # Learned probability bar (percent, 0-100). Sourced from the existing
    # profit-probability or layered-ML context.
    min_probability_pct: float = 62.0
    # Fallback probability bar for system probabilities such as approval/order.
    # These are not profit probabilities, so they require a stricter threshold
    # when used only to avoid dropping otherwise rare score-qualified setups.
    min_system_probability_pct: float = 80.0
    # If True, a candidate with no learned probability is blocked rather than
    # waved through on the heuristic alone.
    require_probability: bool = True
    # Block when the ML authority gate vetoes the candidate.
    block_on_ml_veto: bool = True
    # Block when market-context evidence is not favorable.
    require_market_context_ok: bool = True

    # --- Trade scarcity -----------------------------------------------------
    # Hold at most this many positions concurrently. 1 == one-at-a-time.
    max_concurrent_positions: int = 1
    # Refractory period after the last entry. 240 == 4 hours; keeps trades
    # from clustering and enforces "as few trades as possible".
    min_minutes_between_entries: int = 240

    # --- Sizing -------------------------------------------------------------
    # Percent of account balance to deploy per position. High by design so a
    # small account buys whole shares of most sub-balance symbols (Path A).
    position_size_pct: float = 90.0

    # --- Exit policy --------------------------------------------------------
    # Minimum hold before any non-stop exit is allowed (minutes). Longer than
    # the scalp default of 15 because these are conviction holds.
    min_hold_minutes: int = 60
    # Optional time stop (minutes). 0 disables it (let the trade develop).
    max_hold_minutes: int = 0
    # Protective hard stop: exit if unrealized P&L falls to -hard_stop_pct.
    hard_stop_pct: float = 3.0
    # Trailing engages only once peak unrealized gain reaches this percent.
    trail_activate_pct: float = 3.0
    # Once engaged, exit if the position gives back this fraction of its peak
    # gain (0.35 == give back 35% of the high-water gain). Lets winners run
    # while protecting the bulk of the move.
    trail_giveback_frac: float = 0.35
    # Optional fixed take-profit ceiling (percent). 0 disables it so trailing
    # governs the upside instead of capping it.
    take_profit_pct: float = 0.0
    # Exit (protect profit) when a momentum reversal or bearish learned signal
    # appears while in profit.
    exit_on_reversal: bool = True

    def __post_init__(self) -> None:
        _check(
            self.min_score > 0,
            "min_score",
            "CONVICTION_MIN_SCORE",
            self.min_score,
            "must be > 0",
        )
        _check(
            0.0 <= self.min_probability_pct <= 100.0,
            "min_probability_pct",
            "CONVICTION_MIN_PROBABILITY_PCT",
            self.min_probability_pct,
            "must be within [0, 100]",
        )
        _check(
            0.0 <= self.min_system_probability_pct <= 100.0,
            "min_system_probability_pct",
            "CONVICTION_MIN_SYSTEM_PROBABILITY_PCT",
            self.min_system_probability_pct,
            "must be within [0, 100]",
        )
        _check(
            self.max_concurrent_positions >= 1,
            "max_concurrent_positions",
            "CONVICTION_MAX_CONCURRENT_POSITIONS",
            self.max_concurrent_positions,
            "must be >= 1",
        )
        _check(
            self.min_minutes_between_entries >= 0,
            "min_minutes_between_entries",
            "CONVICTION_MIN_MINUTES_BETWEEN_ENTRIES",
            self.min_minutes_between_entries,
            "must be >= 0",
        )
        _check(
            0.0 < self.position_size_pct <= 100.0,
            "position_size_pct",
            "CONVICTION_POSITION_SIZE_PCT",
            self.position_size_pct,
            "must be within (0, 100]",
        )
        _check(
            self.min_hold_minutes >= 0,
            "min_hold_minutes",
            "CONVICTION_MIN_HOLD_MINUTES",
            self.min_hold_minutes,
            "must be >= 0",
        )
        _check(
            self.max_hold_minutes >= 0,
            "max_hold_minutes",
            "CONVICTION_MAX_HOLD_MINUTES",
            self.max_hold_minutes,
            "must be >= 0",
        )
        _check(
            self.hard_stop_pct > 0,
            "hard_stop_pct",
            "CONVICTION_HARD_STOP_PCT",
            self.hard_stop_pct,
            "must be > 0",
        )
        _check(
            self.trail_activate_pct > 0,
            "trail_activate_pct",
            "CONVICTION_TRAIL_ACTIVATE_PCT",
            self.trail_activate_pct,
            "must be > 0",
        )
        _check(
            0.0 < self.trail_giveback_frac < 1.0,
            "trail_giveback_frac",
            "CONVICTION_TRAIL_GIVEBACK_FRAC",
            self.trail_giveback_frac,
            "must be within (0, 1)",
        )
        _check(
            self.take_profit_pct >= 0,
            "take_profit_pct",
            "CONVICTION_TAKE_PROFIT_PCT",
            self.take_profit_pct,
            "must be >= 0",
        )


def load_conviction_config(**overrides) -> ConvictionConfig:
    """Construct ConvictionConfig from current env, with optional overrides.

    Tests call this after patching env (or pass overrides) to get a fresh
    instance without a process-wide singleton.

    Example::

        cfg = load_conviction_config(enabled=True, min_score=23.0)
    """
    kwargs: dict = dict(
        enabled=env_bool("CONVICTION_MODE_ENABLED", False),
        paper_only=env_bool("CONVICTION_PAPER_ONLY", True),
        min_score=env_float("CONVICTION_MIN_SCORE", 23.0),
        min_probability_pct=env_float("CONVICTION_MIN_PROBABILITY_PCT", 62.0),
        min_system_probability_pct=env_float("CONVICTION_MIN_SYSTEM_PROBABILITY_PCT", 80.0),
        require_probability=env_bool("CONVICTION_REQUIRE_PROBABILITY", True),
        block_on_ml_veto=env_bool("CONVICTION_BLOCK_ON_ML_VETO", True),
        require_market_context_ok=env_bool("CONVICTION_REQUIRE_MARKET_CONTEXT_OK", True),
        max_concurrent_positions=env_int("CONVICTION_MAX_CONCURRENT_POSITIONS", 1),
        min_minutes_between_entries=env_int("CONVICTION_MIN_MINUTES_BETWEEN_ENTRIES", 240),
        position_size_pct=env_float("CONVICTION_POSITION_SIZE_PCT", 90.0),
        min_hold_minutes=env_int("CONVICTION_MIN_HOLD_MINUTES", 60),
        max_hold_minutes=env_int("CONVICTION_MAX_HOLD_MINUTES", 0),
        hard_stop_pct=env_float("CONVICTION_HARD_STOP_PCT", 3.0),
        trail_activate_pct=env_float("CONVICTION_TRAIL_ACTIVATE_PCT", 3.0),
        trail_giveback_frac=env_float("CONVICTION_TRAIL_GIVEBACK_FRAC", 0.35),
        take_profit_pct=env_float("CONVICTION_TAKE_PROFIT_PCT", 0.0),
        exit_on_reversal=env_bool("CONVICTION_EXIT_ON_REVERSAL", True),
    )
    kwargs.update(overrides)
    return ConvictionConfig(**kwargs)
