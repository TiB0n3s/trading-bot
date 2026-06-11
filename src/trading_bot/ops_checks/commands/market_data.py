"""Market-data, historical-bar, and microstructure ops-check command specs."""

from __future__ import annotations

from trading_bot.ops_checks.commands.base import OpsCommandSpec, noarg, spec

COMMAND_SPECS: dict[str, OpsCommandSpec] = {
    "live-bar-pattern-capture": spec("live-bar-pattern-capture"),
    "signal-source-readiness": spec("signal-source-readiness"),
    "context-freshness": spec("context-freshness"),
    "data-freshness-gate": spec("data-freshness-gate"),
    "event-source-coverage": spec("event-source-coverage"),
    "event-context-validation": spec("event-context-validation"),
    "external-symbol-discovery": spec("external-symbol-discovery"),
    "external-symbol-candidates": noarg("external-symbol-candidates"),
    "advanced-alpha-readiness": spec("advanced-alpha-readiness"),
    "advanced-alpha-comparison": spec("advanced-alpha-comparison"),
    "friction-heatmap": spec("friction-heatmap"),
    "volume-clock-vpin": spec("volume-clock-vpin"),
    "volatile-session-intelligence": spec("volatile-session-intelligence"),
    "cross-asset-lead-map": noarg("cross-asset-lead-map", "cross_asset_lead_map"),
    "market-data-parity": spec("market-data-parity", "market_data_parity", "symbol_arg"),
    "live-quote-quality": spec("live-quote-quality", "run_live_quote_quality", "symbol_arg"),
    "webull-readiness": noarg("webull-readiness", "run_webull_readiness"),
    "webull-market-data-parity": spec(
        "webull-market-data-parity",
        "run_webull_market_data_parity",
        "symbol_arg",
    ),
    "webull-rsi-calibration": spec(
        "webull-rsi-calibration",
        "run_webull_rsi_calibration",
        "symbol_arg",
    ),
    "bar-pattern-backfill": spec("bar-pattern-backfill"),
    "historical-bar-archive": spec("historical-bar-archive"),
    "historical-bar-coverage": spec(
        "historical-bar-coverage", "historical_bar_coverage", "start_arg"
    ),
    "historical-bar-progress": spec(
        "historical-bar-progress", "historical_bar_progress", "start_arg"
    ),
    "historical-bar-readiness": spec(
        "historical-bar-readiness", "historical_bar_readiness", "start_arg"
    ),
    "historical-bar-models": noarg("historical-bar-models", "historical_bar_models"),
    "historical-bar-paper-strategy": spec(
        "historical-bar-paper-strategy", "historical_bar_paper_strategy"
    ),
    "historical-bar-paper-validation": spec(
        "historical-bar-paper-validation", "historical_bar_paper_validation"
    ),
    "historical-bar-walk-forward": spec(
        "historical-bar-walk-forward", "historical_bar_walk_forward"
    ),
    "historical-bar-validation": spec("historical-bar-validation", "historical_bar_validation"),
}
