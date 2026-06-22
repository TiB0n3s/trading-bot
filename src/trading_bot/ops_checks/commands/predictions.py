"""Prediction, shadow-model, and authority ops-check command specs."""

from __future__ import annotations

from trading_bot.ops_checks.commands.base import OpsCommandSpec, noarg, spec

COMMAND_SPECS: dict[str, OpsCommandSpec] = {
    "transformer-authority": noarg("transformer-authority"),
    "shadow-predictions": spec("shadow-predictions"),
    "prediction-coverage": spec("prediction-coverage"),
    "symbol-affordability": noarg("symbol-affordability"),
}
