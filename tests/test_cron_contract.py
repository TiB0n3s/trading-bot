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


def test_no_raw_flock_jobs_remain():
    offenders = [line for line in _cron_command_lines() if "flock -n " in line]
    assert not offenders, offenders


def test_locked_jobs_use_job_runner_with_logs():
    offenders = [
        line
        for line in _cron_command_lines()
        if "job_runner.py" in line and "--lock-file" in line and "--log-file" not in line
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


def test_job_runner_lines_have_job_name():
    offenders = [
        line
        for line in _cron_command_lines()
        if "job_runner.py" in line and "--job-name" not in line
    ]
    assert not offenders, offenders


def test_auto_buy_captures_full_candidate_universe():
    lines = [line for line in _cron_command_lines() if "auto_buy_manager.py" in line]
    assert len(lines) == 2, lines
    assert all("--scope all" in line for line in lines)
    assert all("AUTO_BUY_MAX_ACTIVE_POSITIONS_OVERRIDE:-3" not in line for line in lines)
    assert all("AUTO_BUY_MAX_DAILY_ORDERS_OVERRIDE:-12" not in line for line in lines)
    assert all('if [ -n "${AUTO_BUY_MAX_ACTIVE_POSITIONS_OVERRIDE:-}" ]' in line for line in lines)
    assert all('if [ -n "${AUTO_BUY_MAX_DAILY_ORDERS_OVERRIDE:-}" ]' in line for line in lines)


def test_auto_buy_is_regular_session_only():
    lines = [line for line in _cron_command_lines() if "--job-name auto_buy_manager" in line]
    assert len(lines) == 2, lines
    assert any(line.startswith("30-59/2 8 * * 1-5") for line in lines), lines
    assert any(line.startswith("*/2 9-14 * * 1-5") for line in lines), lines
    assert not any(line.startswith("*/2 8-15") for line in lines), lines


def test_fill_poller_is_regular_session_only():
    lines = [line for line in _cron_command_lines() if "--job-name fill_poller" in line]
    assert len(lines) == 2, lines
    assert all("scripts/fill_poller.py" in line for line in lines)
    assert not any(line.startswith("*/2 * * * *") for line in lines), lines
    assert any(line.startswith("30-59/2 8 * * 1-5") for line in lines), lines
    assert any(line.startswith("*/2 9-14 * * 1-5") for line in lines), lines


def test_live_and_label_features_are_regular_session_only():
    live_lines = [line for line in _cron_command_lines() if "--job-name run_live_features" in line]
    label_lines = [
        line for line in _cron_command_lines() if "--job-name run_label_features" in line
    ]
    assert len(live_lines) == 2, live_lines
    assert len(label_lines) == 2, label_lines
    assert any(line.startswith("30-59/2 8 * * 1-5") for line in live_lines), live_lines
    assert any(line.startswith("*/2 9-14 * * 1-5") for line in live_lines), live_lines
    assert any(line.startswith("30-59/5 8 * * 1-5") for line in label_lines), label_lines
    assert any(line.startswith("*/5 9-14 * * 1-5") for line in label_lines), label_lines
    assert not any(line.startswith("*/2 8-14") for line in live_lines), live_lines
    assert not any(line.startswith("*/5 8-14") for line in label_lines), label_lines


def test_premarket_dependency_chain_uses_single_pipeline():
    lines = _cron_command_lines()
    pipeline = [line for line in lines if "pipeline/pre_market.py" in line]
    assert len(pipeline) == 1, pipeline
    assert "--job-name pre_market_pipeline" in pipeline[0]
    assert "/tmp/tradingbot_pre_market_pipeline.lock" in pipeline[0]
    assert "pre_market_pipeline.log" in pipeline[0]

    replaced_jobs = (
        "pre_market_research_data.py --raw-output",
        "archive_context_state.py --reason premarket_context_refresh",
        "collect_and_score_events.py --date $(date +\\%F)",
        "prediction_cache.py preload --date",
    )
    offenders = [line for line in lines for replaced in replaced_jobs if replaced in line]
    assert not offenders, offenders


def test_database_backups_use_safe_gfs_tiers():
    lines = [line for line in _cron_command_lines() if "pipeline/database_backup.py" in line]
    assert len(lines) == 2, lines
    assert any("--backup-tier father" in line and "--retention-days 28" in line for line in lines)
    assert any(
        "--backup-tier grandfather" in line and "--retention-days 2555" in line for line in lines
    )

    raw_copy_tokens = (" cp ", " rsync ", " trades.db-wal", " trades.db-shm")
    offenders = [
        line
        for line in _cron_command_lines()
        if any(token in f" {line} " for token in raw_copy_tokens)
    ]
    assert not offenders, offenders


def main():
    tests = [
        test_no_raw_flock_jobs_remain,
        test_locked_jobs_use_job_runner_with_logs,
        test_wrapper_scripts_are_invoked_through_bash,
        test_after_close_and_post_session_share_lock,
        test_job_runner_lines_have_job_name,
        test_auto_buy_captures_full_candidate_universe,
        test_auto_buy_is_regular_session_only,
        test_fill_poller_is_regular_session_only,
        test_live_and_label_features_are_regular_session_only,
        test_premarket_dependency_chain_uses_single_pipeline,
        test_database_backups_use_safe_gfs_tiers,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} cron contract tests passed.")


if __name__ == "__main__":
    main()
