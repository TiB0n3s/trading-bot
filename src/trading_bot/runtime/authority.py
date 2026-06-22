"""Central authority matrix for runtime decision layers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AUTHORITY_VOCABULARY = (
    "off",
    "observe",
    "warn",
    "size_down",
    "paper_block",
    "live_block",
)

# Rank of each authority mode (higher = more powerful). Used to detect a config
# override that tries to RAISE a layer's permission above a safe ceiling.
_AUTHORITY_RANK = {mode: index for index, mode in enumerate(AUTHORITY_VOCABULARY)}

# ML / heuristic layers that must never reach cash-live authority via a config
# file alone. A JSON override raising any of these above `paper_block` is capped
# back to `paper_block` unless the config explicitly opts in with
# `"allow_ml_live_promotion": true`. Promotion to live ML authority is a
# human-owned decision, not a config edit.
_ML_PROMOTION_GATED_LAYERS = frozenset(
    {
        "ml_prediction",
        "decision_policy",
        "paper_exploration",
        "historical_bar_meta_label",
        "layered_model_authority",
        "transformer",
    }
)
_ML_MAX_AUTHORITY_MODE = "paper_block"


def normalize_authority_mode(value: str | None) -> str:
    raw = str(value or "observe").strip().lower()
    aliases = {
        "": "observe",
        "none": "off",
        "disabled": "off",
        "compare": "observe",
        "observe_only": "observe",
        "observe_only_compare": "observe",
        "soft": "size_down",
        "hard": "live_block",
        "block": "live_block",
        "paper": "paper_block",
    }
    return aliases.get(raw, raw if raw in AUTHORITY_VOCABULARY else "observe")


@dataclass(frozen=True)
class LayerAuthority:
    can_block: str = "off"
    can_size_down: str = "off"
    can_approve: str = "off"
    can_increase_size: str = "off"
    can_submit_order: str = "off"

    def permission_for(self, action: str) -> str:
        return normalize_authority_mode(getattr(self, f"can_{action}", "off"))


DEFAULT_LAYER_AUTHORITY: dict[str, LayerAuthority] = {
    "deterministic_risk": LayerAuthority(
        can_block="live_block",
        can_size_down="live_block",
    ),
    "ml_prediction": LayerAuthority(
        can_size_down="size_down",
    ),
    "decision_policy": LayerAuthority(
        can_block="paper_block",
        can_size_down="paper_block",
    ),
    "paper_exploration": LayerAuthority(
        can_approve="paper_block",
        can_increase_size="paper_block",
    ),
    "historical_bar_meta_label": LayerAuthority(
        can_block="paper_block",
        can_approve="paper_block",
        can_increase_size="paper_block",
    ),
    "layered_model_authority": LayerAuthority(
        can_block="paper_block",
        can_approve="paper_block",
        can_increase_size="paper_block",
    ),
    "claude": LayerAuthority(
        can_block="live_block",
        can_approve="paper_block",
    ),
    "transformer": LayerAuthority(
        can_size_down="paper_block",
    ),
    "execution_guard": LayerAuthority(
        can_block="live_block",
        can_submit_order="live_block",
    ),
}


class AuthorityMatrix:
    def __init__(self, layers: dict[str, LayerAuthority] | None = None):
        self.layers = dict(layers or load_authority_layers_from_config() or DEFAULT_LAYER_AUTHORITY)

    @staticmethod
    def _mode_allows(permission: str, execution_mode: str) -> bool:
        mode = normalize_authority_mode(permission)
        execution = str(execution_mode or "").lower()
        if mode == "off":
            return False
        if mode in {"observe", "warn"}:
            return False
        if mode == "size_down":
            return True
        if mode == "paper_block":
            return execution in {"paper", "dry_run"}
        if mode == "live_block":
            return True
        return False

    def can(self, layer: str, action: str, execution_mode: str) -> bool:
        authority = self.layers.get(layer)
        if authority is None:
            return False
        return self._mode_allows(authority.permission_for(action), execution_mode)

    def decision(self, layer: str, action: str, execution_mode: str) -> dict[str, Any]:
        authority = self.layers.get(layer)
        permission = authority.permission_for(action) if authority else "off"
        return {
            "layer": layer,
            "action": action,
            "execution_mode": execution_mode,
            "permission": permission,
            "allowed": self.can(layer, action, execution_mode),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "authority_matrix_v1",
            "config_path": os.getenv("AUTHORITY_MATRIX_CONFIG"),
            "vocabulary": list(AUTHORITY_VOCABULARY),
            "layers": {
                key: {
                    "can_block": value.can_block,
                    "can_size_down": value.can_size_down,
                    "can_approve": value.can_approve,
                    "can_increase_size": value.can_increase_size,
                    "can_submit_order": value.can_submit_order,
                }
                for key, value in sorted(self.layers.items())
            },
        }


def _layer_from_dict(
    payload: dict[str, Any], *, base: LayerAuthority | None = None
) -> LayerAuthority:
    base = base or LayerAuthority()
    values = {}
    for field_name in (
        "can_block",
        "can_size_down",
        "can_approve",
        "can_increase_size",
        "can_submit_order",
    ):
        values[field_name] = normalize_authority_mode(
            payload.get(field_name) or getattr(base, field_name)
        )
    return LayerAuthority(**values)


def _cap_ml_layer_authority(layer: LayerAuthority) -> LayerAuthority:
    """Cap an ML-gated layer's trade-ENABLING permissions at `paper_block`.

    Prevents a config override from raising an ML/heuristic layer to cash-live
    authority for actions that can cause or grow a trade (approve / increase
    size / submit order). The purely protective permissions (block, size_down)
    are NOT capped — they only ever stop or shrink a trade, so they are safe at
    any level. Non-ML control layers (deterministic_risk, claude,
    execution_guard) are unaffected entirely.
    """
    ceiling = _AUTHORITY_RANK[_ML_MAX_AUTHORITY_MODE]
    values: dict[str, str] = {
        "can_block": layer.can_block,
        "can_size_down": layer.can_size_down,
        "can_approve": layer.can_approve,
        "can_increase_size": layer.can_increase_size,
        "can_submit_order": layer.can_submit_order,
    }
    for field_name in ("can_approve", "can_increase_size", "can_submit_order"):
        mode = normalize_authority_mode(values[field_name])
        if _AUTHORITY_RANK.get(mode, 0) > ceiling:
            mode = _ML_MAX_AUTHORITY_MODE
        values[field_name] = mode
    return LayerAuthority(**values)


def load_authority_layers_from_config(
    path: str | Path | None = None,
) -> dict[str, LayerAuthority] | None:
    raw_path = path or os.getenv("AUTHORITY_MATRIX_CONFIG")
    if not raw_path:
        return None
    config_path = Path(raw_path)
    if not config_path.exists():
        return None
    try:
        payload = json.loads(config_path.read_text())
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    raw_layers = payload.get("layers") if isinstance(payload.get("layers"), dict) else payload
    if not isinstance(raw_layers, dict):
        return None

    # A config file alone may not promote ML layers to cash-live authority.
    allow_ml_live_promotion = bool(payload.get("allow_ml_live_promotion"))

    layers = dict(DEFAULT_LAYER_AUTHORITY)
    for layer, raw in raw_layers.items():
        if not isinstance(raw, dict):
            continue
        layer_name = str(layer)
        built = _layer_from_dict(raw, base=layers.get(layer_name))
        if layer_name in _ML_PROMOTION_GATED_LAYERS and not allow_ml_live_promotion:
            built = _cap_ml_layer_authority(built)
        layers[layer_name] = built
    return layers
