"""Central authority matrix for runtime decision layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

AUTHORITY_VOCABULARY = (
    "off",
    "observe",
    "warn",
    "size_down",
    "paper_block",
    "live_block",
)


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
        self.layers = dict(layers or DEFAULT_LAYER_AUTHORITY)

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
