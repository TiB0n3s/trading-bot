#!/usr/bin/env python3
"""Contract checks for the checked-in operator crontab reference."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CRONTAB = ROOT / "ops" / "crontab.tradingbot.current.txt"


def _cron_command_lines() -> list[str]:
    lines = []
    for raw in CRONTAB.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def test_flock_jobs_log_lock_busy_skips():
    offenders = [
        line
        for line in _cron_command_lines()
        if "flock -n " in line and "lock-busy:" not in line
    ]
    assert not offenders, offenders


def test_wrapper_scripts_are_invoked_through_bash():
    wrapper_paths = (
        "/home/tradingbot/trading-bot/run_after_close_learning.sh",
        "/home/tradingbot/trading-bot/run_label_features.sh",
        "/home/tradingbot/trading-bot/run_live_features.sh",
        "/home/tradingbot/trading-bot/run_position_manager.sh",
        "/home/tradingbot/trading-bot/run_post_session_review.sh",
    )
    offenders = []
    for line in _cron_command_lines():
        for path in wrapper_paths:
            if path in line and f"bash {path}" not in line:
                offenders.append(line)
    assert not offenders, offenders


def test_after_close_and_post_session_share_lock():
    lines = _cron_command_lines()
    after_close = [line for line in lines if "run_after_close_learning.sh" in line]
    post_session = [line for line in lines if "run_post_session_review.sh" in line]
    assert len(after_close) == 1, after_close
    assert len(post_session) == 1, post_session
    assert "/tmp/tradingbot_after_close.lock" in after_close[0]
    assert "/tmp/tradingbot_after_close.lock" in post_session[0]


def main():
    tests = [
        test_flock_jobs_log_lock_busy_skips,
        test_wrapper_scripts_are_invoked_through_bash,
        test_after_close_and_post_session_share_lock,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} cron contract tests passed.")


if __name__ == "__main__":
    main()
