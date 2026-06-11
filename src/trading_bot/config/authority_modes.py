"""Canonical authority-mode normalization for config surfaces."""

from __future__ import annotations

from trading_bot.runtime.authority import AUTHORITY_VOCABULARY, normalize_authority_mode

LEGACY_GATE_ALIASES = {
    "block": "live_block",
    "hard": "live_block",
    "soft": "size_down",
    "compare": "observe",
    "observe_only": "observe",
    "paper": "paper_block",
}


def normalize_config_authority_mode(value: str | None, *, default: str = "warn") -> str:
    raw = str(value or default).strip().lower()
    canonical = LEGACY_GATE_ALIASES.get(raw, raw)
    return normalize_authority_mode(canonical)


def authority_mode_to_legacy_prediction_gate(value: str | None) -> str:
    mode = normalize_config_authority_mode(value)
    if mode == "off":
        return "off"
    if mode in {"observe", "warn"}:
        return "warn"
    if mode == "size_down":
        return "soft"
    if mode in {"paper_block", "live_block"}:
        return "hard"
    return "warn"


def authority_vocabulary() -> tuple[str, ...]:
    return AUTHORITY_VOCABULARY
