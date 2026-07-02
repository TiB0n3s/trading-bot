#!/usr/bin/env python3
"""Contract checks for the checked-in operator crontab reference."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.ops_checks.commands.scheduler_drift_checks import compare_crontabs  # noqa: E402

CRONTAB = ROOT / "ops" / "crontab.tradingbot.current.txt"
INSTALLER = ROOT / "scripts" / "install_operator_crontab.py"
OPS_README = ROOT / "ops" / "README.md"
SQLITE_WRITER_LOCK = "/tmp/tradingbot_sqlite_writer.lock"


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
    research = [line for line in lines if "--job-name after_close_research_batch" in line]
    assert len(after_close) == 1, after_close
    assert len(post_session) == 1, post_session
    assert len(research) == 1, research
    assert "/tmp/tradingbot_after_close.lock" in after_close[0]
    assert "/tmp/tradingbot_after_close.lock" in post_session[0]
    assert "/tmp/tradingbot_after_close.lock" in research[0]
    assert research[0].startswith("30 4 * * 6"), research
    assert "pipeline/after_close_learning.py --lane research" in research[0]
    assert "--timeout-seconds 14400" in research[0]


def test_job_runner_lines_have_job_name():
    offenders = [
        line
        for line in _cron_command_lines()
        if "job_runner.py" in line and "--job-name" not in line
    ]
    assert not offenders, offenders


def test_auto_buy_live_cron_is_disabled_for_storage_fault():
    crontab_text = CRONTAB.read_text()
    lines = [line for line in _cron_command_lines() if "auto_buy_manager.py" in line]
    assert not lines, lines
    assert "AUTO-BUY DISABLED 2026-07-02" in crontab_text
    assert "manifest-backed database backup passes restore verification" in crontab_text


def test_auto_buy_is_regular_session_only():
    lines = [line for line in _cron_command_lines() if "--job-name auto_buy_manager" in line]
    assert not lines, lines


def test_fill_poller_is_regular_session_only():
    lines = [line for line in _cron_command_lines() if "--job-name fill_poller" in line]
    assert len(lines) == 2, lines
    assert all("scripts/fill_poller.py" in line for line in lines)
    assert all(f"--writer-lock-file {SQLITE_WRITER_LOCK}" in line for line in lines), lines
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
    assert any(line.startswith("31-59/5 8 * * 1-5") for line in live_lines), live_lines
    assert any(line.startswith("1-59/5 9-14 * * 1-5") for line in live_lines), live_lines
    assert all("--ionice-idle --nice 10" in line for line in live_lines), live_lines
    assert all(f"--writer-lock-file {SQLITE_WRITER_LOCK}" in line for line in live_lines), (
        live_lines
    )
    assert all(
        "--defer-while-locked /tmp/tradingbot_auto_buy_manager.lock" in line for line in live_lines
    ), live_lines
    assert any(line.startswith("34-59/10 8 * * 1-5") for line in label_lines), label_lines
    assert any(line.startswith("4-59/10 9-14 * * 1-5") for line in label_lines), label_lines
    assert all("--ionice-idle --nice 10" in line for line in label_lines), label_lines
    assert all(f"--writer-lock-file {SQLITE_WRITER_LOCK}" in line for line in label_lines), (
        label_lines
    )
    assert all(
        "--defer-while-locked /tmp/tradingbot_auto_buy_manager.lock" in line for line in label_lines
    ), label_lines
    assert not any(line.startswith("*/2 8-14") for line in live_lines), live_lines
    assert not any(line.startswith("*/5 8-14") for line in label_lines), label_lines


def test_intraday_evidence_writers_are_staggered_and_deprioritized():
    lines = _cron_command_lines()
    rolling_lines = [line for line in lines if "--job-name rolling_momentum" in line]
    session_lines = [line for line in lines if "--job-name session_momentum" in line]
    checkpoint_lines = [line for line in lines if "--job-name sqlite_wal_checkpoint" in line]

    assert len(rolling_lines) == 2, rolling_lines
    assert len(session_lines) == 2, session_lines
    assert len(checkpoint_lines) == 1, checkpoint_lines
    assert any(line.startswith("32-59/10 8 * * 1-5") for line in rolling_lines), rolling_lines
    assert any(line.startswith("2-59/10 9-14 * * 1-5") for line in rolling_lines), rolling_lines
    assert any(line.startswith("36-59/10 8 * * 1-5") for line in session_lines), session_lines
    assert any(line.startswith("6-59/10 9-14 * * 1-5") for line in session_lines), session_lines
    assert all("--ionice-idle --nice 10" in line for line in rolling_lines)
    assert all("--ionice-idle --nice 10" in line for line in session_lines)
    assert all(
        f"--writer-lock-file {SQLITE_WRITER_LOCK}" in line for line in rolling_lines + session_lines
    )
    assert all(
        "--defer-while-locked /tmp/tradingbot_auto_buy_manager.lock" in line
        for line in rolling_lines
    )
    assert all(
        "--defer-while-locked /tmp/tradingbot_auto_buy_manager.lock" in line
        for line in session_lines
    )
    assert checkpoint_lines[0].startswith("7,22,37,52 9-14 * * 1-5"), checkpoint_lines
    assert "scripts/sqlite_checkpoint.py" in checkpoint_lines[0]
    assert "--defer-while-locked /tmp/tradingbot_auto_buy_manager.lock" in checkpoint_lines[0]
    assert f"--writer-lock-file {SQLITE_WRITER_LOCK}" in checkpoint_lines[0]


def test_position_management_jobs_are_regular_session_only():
    lines = _cron_command_lines()
    monitor_lines = [line for line in lines if "--job-name position_momentum_monitor" in line]
    manager_lines = [line for line in lines if "--job-name run_position_manager" in line]
    rotation_lines = [line for line in lines if "--job-name portfolio_rotation" in line]

    assert len(monitor_lines) == 2, monitor_lines
    assert len(manager_lines) == 2, manager_lines
    assert len(rotation_lines) == 2, rotation_lines
    assert any(line.startswith("31-59/5 8 * * 1-5") for line in monitor_lines), monitor_lines
    assert any(line.startswith("1-59/5 9-14 * * 1-5") for line in monitor_lines), monitor_lines
    assert any(line.startswith("30-59/2 8 * * 1-5") for line in manager_lines), manager_lines
    assert any(line.startswith("*/2 9-14 * * 1-5") for line in manager_lines), manager_lines
    assert any(line.startswith("30,45 8 * * 1-5") for line in rotation_lines), rotation_lines
    assert any(line.startswith("*/15 9-14 * * 1-5") for line in rotation_lines), rotation_lines
    assert all(
        f"--writer-lock-file {SQLITE_WRITER_LOCK}" in line
        for line in monitor_lines + manager_lines + rotation_lines
    )
    offenders = monitor_lines + manager_lines + rotation_lines
    assert not any(line.startswith("*/2 8-15") for line in offenders), offenders
    assert not any(line.startswith("1-59/2 8-15") for line in offenders), offenders


def test_context_jobs_keep_afterhours_and_weekend_coverage():
    lines = _cron_command_lines()
    intraday = [line for line in lines if "--job-name intraday_context_refresh" in line]
    noon_learning = [line for line in lines if "--job-name noon_intraday_learning" in line]
    afterhours = [
        line for line in lines if "--job-name collect_and_score_events_afterhours" in line
    ]
    friday = [
        line for line in lines if "--job-name collect_and_score_events_friday_afterhours" in line
    ]
    weekend = [line for line in lines if "--job-name collect_and_score_events_weekend" in line]

    assert len(intraday) == 2, intraday
    assert len(noon_learning) == 1, noon_learning
    assert any(line.startswith("35 8 * * 1-5") for line in intraday), intraday
    assert any(line.startswith("*/45 9-14 * * 1-5") for line in intraday), intraday
    assert all(f"--writer-lock-file {SQLITE_WRITER_LOCK}" in line for line in intraday), intraday
    assert f"--writer-lock-file {SQLITE_WRITER_LOCK}" in noon_learning[0]
    assert len(afterhours) == 1 and afterhours[0].startswith("0 18 * * 1-4"), afterhours
    assert len(friday) == 1 and friday[0].startswith("0 18 * * 5"), friday
    assert len(weekend) == 1 and weekend[0].startswith("0 10,18 * * 6,0"), weekend


def test_live_service_watchdog_is_regular_session_only():
    lines = [line for line in _cron_command_lines() if "--job-name service_health_watchdog" in line]
    assert len(lines) == 2, lines
    assert any(line.startswith("30-59/10 8 * * 1-5") for line in lines), lines
    assert any(line.startswith("*/10 9-14 * * 1-5") for line in lines), lines
    assert all("scripts/fill_stream_runtime_guard.py --ensure" in line for line in lines), lines
    assert not any("WARNING: fill-stream is not active" in line for line in lines), lines
    assert not any(line.startswith("*/10 * * * *") for line in lines), lines


def test_fill_stream_fallback_stop_runs_after_regular_session():
    lines = [
        line for line in _cron_command_lines() if "--job-name fill_stream_runtime_stop" in line
    ]
    assert len(lines) == 1, lines
    assert lines[0].startswith("5 15 * * 1-5"), lines
    assert "scripts/fill_stream_runtime_guard.py --stop" in lines[0], lines


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
    assert all("--timeout-seconds 3600" in line for line in lines)
    assert all("--ionice-idle" in line for line in lines)
    assert all("--nice 10" in line for line in lines)
    assert not any("--job-name daily_db_backup_son" in line for line in lines)

    raw_copy_tokens = (" cp ", " rsync ", " trades.db-wal", " trades.db-shm")
    offenders = [
        line
        for line in _cron_command_lines()
        if any(token in f" {line} " for token in raw_copy_tokens)
    ]
    assert not offenders, offenders


def test_scheduler_drift_check_runs_before_regular_session():
    lines = [line for line in _cron_command_lines() if "--job-name scheduler_drift_check" in line]
    assert len(lines) == 1, lines
    line = lines[0]
    assert line.startswith("20 8 * * 1-5"), line
    assert "--timeout-seconds 30" in line
    assert "ops_check.py cron-drift" in line


def test_compare_crontabs_flags_missing_and_extra_lines():
    reference = """
    # comment
    * * * * * echo expected
    5 * * * * echo another
    """
    installed = """
    * * * * * echo expected
    10 * * * * echo stale
    """
    drift = compare_crontabs(reference, installed)
    assert drift.missing == ["5 * * * * echo another"]
    assert drift.extra == ["10 * * * * echo stale"]


def test_crontab_installation_is_repo_backed():
    crontab_text = CRONTAB.read_text()
    readme_text = OPS_README.read_text()

    assert INSTALLER.exists()
    assert "scripts/install_operator_crontab.py --apply" in crontab_text
    assert "scripts/install_operator_crontab.py --check" in readme_text
    assert "scripts/install_operator_crontab.py --apply" in readme_text
    assert "crontab ops/crontab.tradingbot.current.txt" not in readme_text


def test_db_right_size_runs_dark_hours_with_rollback_pruning():
    lines = [
        line for line in _cron_command_lines() if "--job-name db_right_size_maintenance" in line
    ]
    assert len(lines) == 1, lines
    line = lines[0]
    assert line.startswith("30 3 * * 2-6"), line
    assert "pipeline/db_right_size_maintenance.py" in line
    assert "--execute-archive" in line
    assert "--checkpoint" in line
    assert "--prune-rollbacks" in line
    assert "--rollback-retention-days 2" in line
    assert "--rollback-min-keep 0" in line
    assert "--max-chunks 20" in line


def main():
    tests = [
        test_no_raw_flock_jobs_remain,
        test_locked_jobs_use_job_runner_with_logs,
        test_wrapper_scripts_are_invoked_through_bash,
        test_after_close_and_post_session_share_lock,
        test_job_runner_lines_have_job_name,
        test_auto_buy_live_cron_is_disabled_for_storage_fault,
        test_auto_buy_is_regular_session_only,
        test_fill_poller_is_regular_session_only,
        test_live_and_label_features_are_regular_session_only,
        test_intraday_evidence_writers_are_staggered_and_deprioritized,
        test_position_management_jobs_are_regular_session_only,
        test_context_jobs_keep_afterhours_and_weekend_coverage,
        test_live_service_watchdog_is_regular_session_only,
        test_premarket_dependency_chain_uses_single_pipeline,
        test_database_backups_use_safe_gfs_tiers,
        test_scheduler_drift_check_runs_before_regular_session,
        test_compare_crontabs_flags_missing_and_extra_lines,
        test_crontab_installation_is_repo_backed,
        test_db_right_size_runs_dark_hours_with_rollback_pruning,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} cron contract tests passed.")


if __name__ == "__main__":
    main()
