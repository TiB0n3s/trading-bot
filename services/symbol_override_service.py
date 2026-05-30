"""Runtime symbol override cache."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SymbolOverrideService:
    def __init__(self, *, path: Path, overrides: dict[str, Any], log: Any):
        self.path = path
        self.overrides = overrides
        self.log = log
        self.mtime = 0.0

    def load(self) -> None:
        """Lazy-load symbol_overrides.json into the shared override dict."""
        default = {
            "disabled_symbols": [],
            "buy_disabled": [],
            "sell_only": [],
            "notes": {},
        }

        if not self.path.exists():
            self.overrides.clear()
            self.overrides.update(default)
            return

        try:
            current_mtime = self.path.stat().st_mtime
            if current_mtime <= self.mtime:
                return

            raw = json.loads(self.path.read_text())
            self.overrides.clear()
            self.overrides.update(
                {
                    "disabled_symbols": [
                        s.upper() for s in raw.get("disabled_symbols", [])
                    ],
                    "buy_disabled": [s.upper() for s in raw.get("buy_disabled", [])],
                    "sell_only": [s.upper() for s in raw.get("sell_only", [])],
                    "notes": raw.get("notes", {})
                    if isinstance(raw.get("notes", {}), dict)
                    else {},
                }
            )
            self.mtime = current_mtime

            self.log.info(
                "Symbol overrides loaded: "
                f"disabled={len(self.overrides['disabled_symbols'])}, "
                f"buy_disabled={len(self.overrides['buy_disabled'])}, "
                f"sell_only={len(self.overrides['sell_only'])}"
            )
        except Exception as exc:
            self.log.error(f"symbol override load failed: {exc}")
            self.overrides.clear()
            self.overrides.update(default)

    def block_reason(self, symbol: str, action: str) -> str | None:
        """Return a reason string when an override blocks the signal."""
        symbol = symbol.upper()
        action = action.lower()
        self.load()

        disabled = set(self.overrides.get("disabled_symbols", []))
        buy_disabled = set(self.overrides.get("buy_disabled", []))
        sell_only = set(self.overrides.get("sell_only", []))
        notes = self.overrides.get("notes", {}) or {}
        note = notes.get(symbol) or ""

        if symbol in disabled:
            return "symbol disabled by operator override" + (
                f" — {note}" if note else ""
            )

        if action == "buy" and symbol in buy_disabled:
            return "BUY disabled by operator override" + (f" — {note}" if note else "")

        if action == "buy" and symbol in sell_only:
            return "symbol in sell_only mode by operator override" + (
                f" — {note}" if note else ""
            )

        return None
