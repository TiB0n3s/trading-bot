#!/usr/bin/env python3
"""test_dt_trigger.py — unit tests for the SAFE-job trigger wrapper (PROPOSAL).

Stdlib/pytest only; a FAKE runner — no WSL, no job_runner.py, no network. Proves the
contract's load-bearing safety properties:

  1. every enum key maps to a SAFE, well-formed argv (shell=False list);
  2. an unknown key is rejected before any dispatch;
  3. a denied command hard-aborts (deny-scan backstop);
  4. params cannot inject shell (date is a separate argv element; bad dates rejected);

plus market-hours guard, rate-limit, idempotency, and the _dt provenance suffix.

Run:  pytest -q proposals/trading-bot/test_dt_trigger.py
(when merged into the bot tree it lives next to scripts/dt_trigger.py).
"""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime

import pytest

# Import scripts/dt_trigger.py regardless of how the test is invoked.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_spec = importlib.util.spec_from_file_location(
    "dt_trigger", os.path.join(_ROOT, "scripts", "dt_trigger.py"))
dt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dt)


# --------------------------------------------------------------------------- fakes
class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RecordingRunner:
    """Records the argv it was called with; never executes anything."""

    def __init__(self, returncode=0):
        self.calls = []
        self.returncode = returncode

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return FakeProc(returncode=self.returncode, stdout='{"ok": true}')


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    """Point the rate/idempotency ledger at a throwaway file per test."""
    monkeypatch.setattr(dt, "_LEDGER_PATH", str(tmp_path / "ledger.json"))
    yield


# A weekend evening: outside the live trading band, so the market-hours guard passes by
# default. (Sat 2026-06-27 20:00.)
SAFE_NOW = datetime(2026, 6, 27, 20, 0)


# --------------------------------------------------------------------------- expected set
EXPECTED_KEYS = {
    "after_close_learning", "after_close_research_batch", "intraday_learning_noon",
    "collect_and_score_events_afterhours", "collect_and_score_events_friday_afterhours",
    "collect_and_score_events_weekend",
    "pead_benzinga_snapshot", "post_earnings_drift_scan", "daily_summary",
    "weekly_summary", "trade_matcher", "historical_bar_archive",
}


def test_allowlist_is_exactly_the_twelve_keys():
    assert set(dt.ALLOWLIST) == EXPECTED_KEYS
    assert len(dt.ALLOWLIST) == 12


def test_friday_afterhours_event_argv_matches_cron_verbatim():
    # The Friday variant (cron: Fri 18:00) mirrors its afterhours/weekend siblings: same
    # lock-file, log-file, and collect_and_score_events.py flags — only the --output basename
    # differs (_friday_afterhours.json). Provenance suffix applied to --job-name.
    argv = dt.build_argv("collect_and_score_events_friday_afterhours")
    jn = argv[argv.index("--job-name") + 1]
    assert jn == "collect_and_score_events_friday_afterhours" + dt.DT_SUFFIX
    assert argv[argv.index("--lock-file") + 1] == "/tmp/tradingbot_event_collection.lock"
    assert argv[argv.index("--log-file") + 1] == f"{dt.BOT_DIR}/event_collection.log"
    bash_str = argv[argv.index("-lc") + 1]
    assert 'TARGET_DATE=$(' in bash_str and "scripts/next_trading_date.py" in bash_str
    assert "scripts/collect_and_score_events.py" in bash_str
    assert "--max-per-symbol 2 --include-context-symbols --apply-context --predict" in bash_str
    assert "--ai-interpret-events --ai-event-provider hybrid" in bash_str
    assert '--output /tmp/events_"$TARGET_DATE"_friday_afterhours.json' in bash_str
    # Same research family as its siblings, and deny-scan-clean.
    assert dt.ALLOWLIST["collect_and_score_events_friday_afterhours"]["family"] == "research"
    dt.deny_scan(argv)


# --------------------------------------------------------------------------- (1) every enum → safe argv
@pytest.mark.parametrize("job", sorted(EXPECTED_KEYS))
def test_every_enum_maps_to_safe_argv(job):
    argv = dt.build_argv(job)
    # It is a list of strings (shell=False ready), never a single string.
    assert isinstance(argv, list)
    assert all(isinstance(a, str) for a in argv)
    # Begins with the bot python + job_runner.
    assert argv[0] == dt.PY
    assert argv[1] == dt.JOB_RUNNER
    # Carries the _dt provenance suffix on --job-name.
    jn_idx = argv.index("--job-name")
    assert argv[jn_idx + 1].endswith(dt.DT_SUFFIX)
    # Carries a lock-file flag (every safe job inherits its cron lock).
    assert "--lock-file" in argv
    # The fixed command is present after the `--` separator.
    assert "--" in argv
    # Deny-scan passes for every legitimate safe job.
    dt.deny_scan(argv)


@pytest.mark.parametrize("job", sorted(EXPECTED_KEYS))
def test_dispatch_invokes_runner_with_shell_false_list(job):
    runner = RecordingRunner()
    result = dt.dispatch(job, validated_date=None, idempotency_key=None,
                         force_market_hours=False, runner=runner, now=SAFE_NOW)
    assert result["dispatched"] is True
    assert len(runner.calls) == 1
    called_argv, kwargs = runner.calls[0]
    assert isinstance(called_argv, list)
    # The wrapper never passes shell=True; the real runner pins shell=False.
    assert kwargs.get("shell", False) is False


def test_verbatim_throttle_flags_preserved():
    # after_close_research_batch must carry its exact cron throttle flags, unrelaxed.
    argv = dt.build_argv("after_close_research_batch")
    assert "--timeout-seconds" in argv and "14400" in argv
    assert "--ionice-idle" in argv
    assert "--nice" in argv and "10" in argv
    # post_earnings_drift_scan keeps its 10800 timeout.
    argv2 = dt.build_argv("post_earnings_drift_scan")
    assert "--timeout-seconds" in argv2 and "10800" in argv2


def test_phase_is_fixed_to_noon_and_not_caller_controllable():
    argv = dt.build_argv("intraday_learning_noon")
    joined = " ".join(argv)
    assert "--phase noon" in joined
    # There is no caller --phase surface at all (argparse has no such option).
    assert not any(a == "--phase" and i + 1 < len(argv) and argv[i + 1] != "noon"
                   for i, a in enumerate(argv))


# --------------------------------------------------------------------------- (2) unknown key rejected
def test_unknown_key_rejected_before_dispatch():
    runner = RecordingRunner()
    with pytest.raises(dt.TriggerError):
        dt.validate_job("auto_buy_manager")
    with pytest.raises(dt.TriggerError):
        dt.dispatch("totally_made_up", validated_date=None, idempotency_key=None,
                    force_market_hours=False, runner=runner, now=SAFE_NOW)
    assert runner.calls == []  # nothing dispatched


@pytest.mark.parametrize("evil", [
    "auto_buy_manager", "run_position_manager", "position_momentum_monitor",
    "portfolio_rotation", "fill_poller", "run_live_features", "run_label_features",
    "rolling_momentum", "session_momentum", "sqlite_wal_checkpoint",
    "db_right_size_maintenance", "weekly_db_backup_father",
])
def test_excluded_jobs_are_not_in_the_enum(evil):
    assert evil not in dt.ALLOWLIST
    with pytest.raises(dt.TriggerError):
        dt.validate_job(evil)


# --------------------------------------------------------------------------- (3) denied command hard-aborts
def test_deny_scan_aborts_on_forbidden_token():
    poisoned = [dt.PY, dt.JOB_RUNNER, "--job-name", "daily_summary_dt", "--",
                "bash", "-lc", "python scripts/auto_buy_manager.py --scope all --live"]
    with pytest.raises(dt.TriggerError):
        dt.deny_scan(poisoned)


@pytest.mark.parametrize("token", ["auto_buy", "--live", "promote", "registry",
                                   "run_position_manager", "session_momentum"])
def test_deny_scan_catches_each_token(token):
    argv = [dt.PY, dt.JOB_RUNNER, "--", "bash", "-lc", f"do_something {token} now"]
    with pytest.raises(dt.TriggerError):
        dt.deny_scan(argv)


def test_dispatch_hard_aborts_if_allowlist_were_poisoned(monkeypatch):
    # Simulate a future bad edit that wired a dangerous command behind a safe key.
    poisoned = dt._entry(
        "reporting", "daily_summary",
        ["--lock-file", "/tmp/x.lock"],
        ["--", "bash", "-lc", "python scripts/auto_buy_manager.py --live"])
    monkeypatch.setitem(dt.ALLOWLIST, "daily_summary", poisoned)
    runner = RecordingRunner()
    with pytest.raises(dt.TriggerError):
        dt.dispatch("daily_summary", validated_date=None, idempotency_key=None,
                    force_market_hours=False, runner=runner, now=SAFE_NOW)
    assert runner.calls == []  # deny-scan fired before any exec


# --------------------------------------------------------------------------- (4) params can't inject shell
@pytest.mark.parametrize("bad", [
    "2026-06-28; rm -rf /", "$(whoami)", "2026-13-99", "not-a-date",
    "2026-06-28 && curl evil", "../../etc/passwd", "2026-06-28'", '2026-06-28"',
])
def test_bad_date_rejected(bad):
    with pytest.raises(dt.TriggerError):
        dt.validate_date(bad)


def test_valid_date_is_separate_argv_element_not_spliced():
    # after_close_research_batch declares no date_param, so a date is refused outright.
    with pytest.raises(dt.TriggerError):
        dt.build_argv("after_close_research_batch", validated_date="2026-06-28")


def test_date_param_when_accepted_is_a_distinct_element(monkeypatch):
    # Construct a synthetic entry that DOES accept a date, to prove splicing discipline.
    entry = dt._entry(
        "research", "synthetic_dateful",
        ["--lock-file", "/tmp/x.lock"],
        ["--", "bash", "-lc", "set -a && . /etc/trading-bot.env && set +a && "
         "python scripts/some_research.py"],
        date_param="--date")
    monkeypatch.setitem(dt.ALLOWLIST, "synthetic_dateful", entry)
    argv = dt.build_argv("synthetic_dateful", validated_date="2026-06-28")
    # The date is its own trailing argv pair, NOT embedded in the bash -lc string.
    assert argv[-2:] == ["--date", "2026-06-28"]
    bash_str = argv[argv.index("-lc") + 1]
    assert "2026-06-28" not in bash_str  # never spliced into the shell string


@pytest.mark.parametrize("bad", ["short", "has space", "bad!char", "x" * 65])
def test_bad_idempotency_key_rejected(bad):
    with pytest.raises(dt.TriggerError):
        dt.validate_idempotency_key(bad)


def test_good_idempotency_key_accepted():
    assert dt.validate_idempotency_key("abc-123_DEF") == "abc-123_DEF"


# --------------------------------------------------------------------------- guards
def test_market_hours_guard_blocks_live_band():
    # Mon 2026-06-29 10:30 — inside 09:00–14:59.
    in_band = datetime(2026, 6, 29, 10, 30)
    entry = dt.ALLOWLIST["daily_summary"]
    with pytest.raises(dt.TriggerError):
        dt.market_hours_guard(entry, now=in_band, force=False)
    # force=True (L2 confirmation) bypasses.
    dt.market_hours_guard(entry, now=in_band, force=True)
    # Outside the band passes.
    dt.market_hours_guard(entry, now=SAFE_NOW, force=False)


def test_rate_limit_blocks_after_cap():
    cap = dt.RATE_LIMIT_PER_HOUR["reporting"]
    # Fill the family cap.
    for _ in range(cap):
        dt.rate_and_idempotency_guard("reporting", None)
    with pytest.raises(dt.TriggerError):
        dt.rate_and_idempotency_guard("reporting", None)


def test_idempotency_replay_is_noop():
    dt.rate_and_idempotency_guard("learning", "key-abc-123")
    with pytest.raises(dt.TriggerError):
        dt.rate_and_idempotency_guard("learning", "key-abc-123")


def test_main_unknown_job_returns_nonzero(capsys):
    rc = dt.main(["--job", "auto_buy_manager"])
    assert rc != 0
    out = capsys.readouterr().out
    assert '"dispatched": false' in out.lower()


def test_main_list_does_not_require_job(capsys):
    rc = dt.main(["--list"])
    assert rc == 0
    payload = capsys.readouterr().out
    assert '"daily_summary"' in payload
    assert '"job_name": "daily_summary_dt"' in payload


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
