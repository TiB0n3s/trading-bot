"""Legacy subprocess command definitions for ops checks."""

from __future__ import annotations

from pathlib import Path


def script_path(script_dir: Path, name: str) -> str:
    return str(script_dir / name)


def build_legacy_subprocess_commands(script_dir: Path) -> dict[str, list[str]]:
    """Return ops commands that still execute script entrypoints in subprocesses."""

    def script(name: str) -> str:
        return script_path(script_dir, name)

    return {
        "morning": [script("morning_check.py")],
        "positions": [script("position_review.py")],
        "session": [script("session_momentum.py"), "--all"],
        "position-momentum": [script("position_momentum_monitor.py")],
        "post": [script("post_session_check.py")],
        "events": [script("bot_events.py"), "--limit", "25"],
        "bot-events": [script("bot_events.py"), "--limit", "25"],
        "regime": [script("regime_status.py")],
        "regime-json": [script("regime_status.py"), "--json"],
        "regime-matrix": [script("regime_status.py"), "--routing-matrix"],
    }
