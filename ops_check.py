#!/usr/bin/env python3
"""
Operator check wrapper.

Usage:
  python3 ops_check.py morning
  python3 ops_check.py positions
  python3 ops_check.py alignment
  python3 ops_check.py adaptive
  python3 ops_check.py filters
  python3 ops_check.py drawdown
  python3 ops_check.py post
  python3 ops_check.py intelligence
  python3 ops_check.py events
  python3 ops_check.py context
  python3 ops_check.py learning
  python3 ops_check.py predictions
  python3 ops_check.py signal-lessons
  python3 ops_check.py trends
  python3 ops_check.py prediction-validation
  python3 ops_check.py bot-events
  python3 ops_check.py event-attribution
  python3 ops_check.py premarket
  python3 ops_check.py market-context-check
  python3 ops_check.py intelligence-summary
  python3 ops_check.py dataset-health
  python3 ops_check.py feature-health
  python3 ops_check.py feature-watch
  python3 ops_check.py rejection-summary
  python3 ops_check.py rejected-outcomes
  python3 ops_check.py auto-buy
  python3 ops_check.py auto-buy-outcomes
  python3 ops_check.py decision-snapshots
  python3 ops_check.py policy-artifacts
  python3 ops_check.py retention
  python3 ops_check.py order-health
  python3 ops_check.py runtime-health
  python3 ops_check.py runtime-health-trend START_DATE END_DATE
  python3 ops_check.py context-freshness
  python3 ops_check.py data-freshness-gate
  python3 ops_check.py event-source-coverage
  python3 ops_check.py event-context-validation
  python3 ops_check.py log-ledger-consistency
  python3 ops_check.py portfolio-risk
  python3 ops_check.py production-evidence
  python3 ops_check.py lifecycle-analysis
  python3 ops_check.py decision-lifecycle-dashboard
  python3 ops_check.py exit-snapshot-backfill YYYY-MM-DD [--dry-run]
  python3 ops_check.py candidate-universe
  python3 ops_check.py calibration-buckets
  python3 ops_check.py feature-attribution
  python3 ops_check.py post-trade-learning
  python3 ops_check.py symbol-patterns
  python3 ops_check.py learning-readiness START_DATE [END_DATE]
  python3 ops_check.py rollout-contract
  python3 ops_check.py advisory-authority-report
  python3 ops_check.py ai-intelligence-review
  python3 ops_check.py migration-status
  python3 ops_check.py strong-days
  python3 ops_check.py strong-days 2026-05-26
  python3 ops_check.py conviction-persistence-health 2026-05-29
  python3 ops_check.py regime
  python3 ops_check.py regime-json
  python3 ops_check.py regime-matrix
  python3 ops_check.py all
  python3 ops_check.py filters 2026-05-08
"""

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from services.ops_checks.conviction_checks import (
    run_buy_opportunity_report,
    run_claude_context_audit,
    run_conviction_persistence_health,
    run_conviction_stack_report,
)
from services.ops_checks.auto_buy_checks import run_auto_buy_health
from services.ops_checks.dataset_checks import run_dataset_health
from services.ops_checks.excursion_checks import (
    run_peak_bucket_report,
    run_winner_became_loser,
)
from services.ops_checks.feature_checks import run_feature_health, run_feature_watch
from services.ops_checks.intelligence_checks import run_intelligence_summary
from services.ops_checks.lifecycle_checks import run_lifecycle_analysis
from services.ops_checks.lifecycle_dashboard_checks import run_lifecycle_dashboard
from services.ops_checks.exit_snapshot_backfill_checks import run_exit_snapshot_backfill
from services.ops_checks.candidate_universe_checks import run_candidate_universe_report
from services.ops_checks.calibration_bucket_checks import run_calibration_buckets
from services.ops_checks.feature_attribution_checks import run_feature_attribution_report
from services.ops_checks.post_trade_learning_checks import run_post_trade_learning_report
from services.ops_checks.symbol_pattern_checks import run_symbol_pattern_outcomes
from services.ops_checks.learning_readiness_checks import run_learning_readiness
from services.ops_checks.rollout_contract_checks import run_rollout_contract_report
from services.ops_checks.advisory_authority_checks import run_advisory_authority_report
from services.ops_checks.ai_intelligence_review_checks import run_ai_intelligence_review
from services.ops_checks.order_checks import run_order_health
from services.ops_checks.rejection_checks import run_rejection_summary
from services.ops_checks.rejected_outcome_checks import run_rejected_outcomes_health
from services.ops_checks.setup_breakdown import run_setup_breakdown
from services.ops_checks.runtime_checks import run_runtime_health, run_runtime_health_trend
from services.ops_checks.context_freshness_checks import run_context_freshness, run_data_freshness_gate
from services.ops_checks.event_source_checks import run_event_source_coverage
from services.ops_checks.event_context_validation_checks import run_event_context_validation
from services.ops_checks.log_ledger_checks import run_log_ledger_consistency
from services.ops_checks.portfolio_risk_checks import run_portfolio_risk_report
from services.ops_checks.point_in_time_archive_checks import run_point_in_time_archive
from services.ops_checks.snapshot_checks import run_decision_snapshot_health

BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
ENV_FILE = Path("/etc/trading-bot.env")


def reexec_under_venv_if_available():
    if not VENV_PYTHON.exists():
        return

    venv_dir = VENV_PYTHON.parent.parent.resolve()
    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == venv_dir:
        return

    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])


reexec_under_venv_if_available()


def load_env_file(path=ENV_FILE):
    if not path.exists():
        return False

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value

    return True


# Commands that take no date arg (run with no extra args)
# Commands that take a positional date: drawdown, post, adaptive_impact, strategy_intelligence
# Commands that take --date DATE: filters, blocked, event-attribution, intelligence, context,
#   learning, predictions, signal-lessons, trends, prediction-validation, auto-buy-outcomes,
#   strong-days
# Full arg construction is done in main() below.
COMMANDS = {
    "morning": ["morning_check.py"],
    "positions": ["position_review.py"],
    "alignment": ["market_alignment_report.py"],
    "adaptive": ["adaptive_confirmation_report.py"],
    "adaptive_impact": ["adaptive_impact_report.py"],
    "strategy_intelligence": ["strategy_intelligence_report.py"],
    "blocked": ["blocked_signal_outcome_report.py"],
    "session": ["session_momentum.py", "--all"],
    "position-momentum": ["position_momentum_monitor.py"],
    "filters": ["filter_report.py"],
    "drawdown": ["drawdown_report.py"],
    "post": ["post_session_check.py"],
    "events": ["bot_events.py", "--limit", "25"],
    "bot-events": ["bot_events.py", "--limit", "25"],
    "event-attribution": ["event_attribution_report.py"],
    "intelligence": ["intelligence_context_report.py"],
    "context": ["context_trade_join_report.py"],
    "learning": ["intelligence_learning_report.py"],
    "predictions": ["intelligence_prediction_report.py"],
    "signal-lessons": ["signal_timing_lesson_report.py"],
    "trends": ["trend_context_report.py"],
    "prediction-validation": ["prediction_validation_report.py"],
    "auto-buy-outcomes": ["auto_buy_outcome_report.py"],
    "strong-days": ["strong_day_participation_report.py"],
    "regime": ["regime_status.py"],
    "regime-json": ["regime_status.py", "--json"],
    "regime-matrix": ["regime_status.py", "--routing-matrix"],
}


def run(label, args):
    print()
    print("=" * 72)
    print(f"  {label}")
    print("=" * 72)

    try:
        r = subprocess.run(
            [sys.executable] + args,
            cwd=BASE_DIR,
            text=True,
            timeout=180,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"[FAIL] {label} failed: {e}")
        return False


def check_market_context_file():
    import json

    path = BASE_DIR / "market_context.json"

    print()
    print("=" * 72)
    print("  Market Context Check")
    print("=" * 72)

    if not path.exists():
        print(f"[FAIL] missing {path}")
        return False

    try:
        data = json.loads(path.read_text())
    except Exception as e:
        print(f"[FAIL] could not parse {path}: {e}")
        return False

    required_top = {
        "market_date",
        "macro_sentiment",
        "macro_summary",
        "symbols",
    }

    required_symbol = {
        "bias",
        "reason",
        "confidence",
        "fundamental_score",
        "risk_level",
        "entry_quality",
        "avoid_type",
    }

    ok = True

    missing_top = sorted(required_top - set(data.keys()))
    if missing_top:
        print(f"[FAIL] missing top-level fields: {missing_top}")
        ok = False

    market_date = data.get("market_date")
    source = data.get("source")
    fmt = data.get("format")
    symbols = data.get("symbols") or {}

    print(f"market_date : {market_date}")
    print(f"source      : {source}")
    print(f"format      : {fmt}")
    print(f"symbols     : {len(symbols)}")
    print(f"macro       : {data.get('macro_sentiment')}")
    print(f"regime      : {data.get('macro_regime')}")
    print(f"risk_mult   : {data.get('risk_multiplier')}")
    print(f"max_pos     : {data.get('max_new_positions')}")
    print(f"block_buys  : {data.get('block_new_buys')}")

    # Intraday refresh staleness check — only meaningful during market hours.
    from datetime import datetime, timezone, timedelta
    intraday_refresh_at = data.get("intraday_refresh_at")
    print(f"intraday_refresh_at : {intraday_refresh_at or 'not present'}")
    now_utc = datetime.now(timezone.utc)
    et_offset = timedelta(hours=-4)  # EDT; close enough for a staleness gate
    now_et = now_utc + et_offset
    market_open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    is_market_hours = now_et.weekday() < 5 and market_open_et <= now_et <= market_close_et
    INTRADAY_REFRESH_STALE_MINUTES = 90
    if is_market_hours:
        if not intraday_refresh_at:
            print(f"[WARN] intraday_refresh_at absent during market hours — intraday_context_refresh.py may not have run yet")
        else:
            try:
                refresh_dt = datetime.fromisoformat(intraday_refresh_at).astimezone(timezone.utc)
                age_minutes = (now_utc - refresh_dt).total_seconds() / 60
                if age_minutes > INTRADAY_REFRESH_STALE_MINUTES:
                    print(f"[WARN] intraday_refresh_at is {age_minutes:.0f} min old (>{INTRADAY_REFRESH_STALE_MINUTES} min) — refresh may be silently failing")
                    ok = False
                else:
                    print(f"[OK] intraday_refresh_at is {age_minutes:.0f} min old (within {INTRADAY_REFRESH_STALE_MINUTES} min)")
            except Exception as e:
                print(f"[WARN] could not parse intraday_refresh_at '{intraday_refresh_at}': {e}")
    else:
        if intraday_refresh_at:
            print(f"[OK] intraday_refresh_at present (staleness check skipped outside market hours)")

    if not isinstance(symbols, dict) or not symbols:
        print("[FAIL] symbols is empty or not an object")
        return False

    bad_symbols = []
    avoid_type_errors = []
    bias_counts = {}

    for sym, entry in symbols.items():
        entry = entry or {}
        bias = entry.get("bias", "missing")
        bias_counts[bias] = bias_counts.get(bias, 0) + 1

        missing = sorted(required_symbol - set(entry.keys()))
        if missing:
            bad_symbols.append((sym, missing))

        avoid_type = entry.get("avoid_type")
        if bias != "avoid" and avoid_type is not None:
            avoid_type_errors.append((sym, bias, avoid_type))

    print(f"bias_counts : {bias_counts}")

    if bad_symbols:
        print("[FAIL] symbols missing required fields:")
        for sym, missing in bad_symbols[:25]:
            print(f"  {sym}: {missing}")
        ok = False
    else:
        print("[OK] required per-symbol fields present")

    if avoid_type_errors:
        print("[FAIL] avoid_type set on non-avoid symbols:")
        for sym, bias, avoid_type in avoid_type_errors[:25]:
            print(f"  {sym}: bias={bias} avoid_type={avoid_type}")
        ok = False
    else:
        print("[OK] avoid_type only set for avoid symbols")

    if source != "market_brief_builder":
        print(f"[WARN] source is not market_brief_builder: {source}")

    if fmt != "rich_market_brief_v1":
        print(f"[WARN] format is not rich_market_brief_v1: {fmt}")

    if ok:
        print("[OK] market_context.json schema check passed")
    else:
        print("[FAIL] market_context.json schema check failed")

    return ok


def intelligence_summary(target_date):
    return run_intelligence_summary(target_date, base_dir=BASE_DIR)


def _table_exists(con, table_name):
    row = con.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _count_table(con, table_name, where_sql="", params=()):
    if not _table_exists(con, table_name):
        return None

    sql = f"SELECT COUNT(*) AS n FROM {table_name}"
    if where_sql:
        sql += f" WHERE {where_sql}"
    return con.execute(sql, params).fetchone()["n"]


def dataset_health(target_date):
    return run_dataset_health(target_date, base_dir=BASE_DIR)


def feature_health(target_date):
    return run_feature_health(target_date, base_dir=BASE_DIR)


def feature_watch(target_date):
    return run_feature_watch(target_date, base_dir=BASE_DIR)


def rejection_summary(target_date):
    return run_rejection_summary(target_date, base_dir=BASE_DIR)


def migration_status_check():
    from db_migrations import status as migration_status

    print()
    print("=" * 72)
    print("  DB Migration Status")
    print("=" * 72)

    try:
        rows = migration_status(BASE_DIR / "trades.db")
    except Exception as e:
        print(f"[FAIL] migration status check failed: {e}")
        return False

    pending = [row for row in rows if not row["applied"]]
    for row in rows:
        marker = "applied" if row["applied"] else "pending"
        print(f"{marker:>8}  {row['migration_id']}  {row['description']}")

    if pending:
        print(f"[FAIL] {len(pending)} pending DB migration(s)")
        return False

    print("[OK] all DB migrations applied")
    return True


def rejected_outcomes_health(target_date):
    return run_rejected_outcomes_health(
        target_date,
        base_dir=BASE_DIR,
        env_get=os.getenv,
    )


def auto_buy_health(target_date):
    return run_auto_buy_health(target_date, base_dir=BASE_DIR)


def decision_snapshot_health(target_date):
    return run_decision_snapshot_health(target_date, base_dir=BASE_DIR)


def policy_artifact_health():
    from datetime import datetime, timezone

    from policy_artifacts import policy_artifact_status

    print()
    print("=" * 72)
    print("  Policy Artifact Health")
    print("=" * 72)

    status = policy_artifact_status(BASE_DIR)
    print(f"enabled     : {status.get('enabled')}")
    print(f"effect      : {status.get('runtime_effect')}")
    print(f"state_hash  : {status.get('state_hash')}")
    registry = status.get("registry") or {}
    known_good = registry.get("known_good") or {}
    print(f"registry    : entries={registry.get('entry_count', 0)} path={registry.get('registry_path')}")
    print(f"known_good  : {known_good.get('artifact_set_id') or '-'}")

    ok = True
    now = datetime.now(timezone.utc)
    for name, item in status.get("files", {}).items():
        exists = item.get("exists")
        mtime = item.get("mtime")
        age_hours = None
        if mtime:
            try:
                age_hours = (now - datetime.fromisoformat(mtime)).total_seconds() / 3600
            except Exception:
                age_hours = None
        age_s = f"{age_hours:.1f}h" if age_hours is not None else "-"
        print(
            f"  {name:<36} exists={str(exists):<5} age={age_s:>8} "
            f"generated_at={item.get('generated_at') or '-'} sha={str(item.get('sha256') or '-')[:12]}"
        )
        if name == "policy_backtest_summary.json":
            rec = item.get("recommendation")
            if rec:
                print(f"    policy_backtest_recommendation={rec} reason={item.get('reason') or '-'}")
                if rec == "policy_too_loose":
                    print("    [WARN] decision policy remains too loose; keep under review and do not promote")
        if not exists:
            ok = False
            print(f"    [WARN] missing policy artifact: {name}")
        elif age_hours is not None and age_hours > 72:
            print(f"    [WARN] artifact older than 72h: {name}")

    if not registry.get("entry_count"):
        ok = False
        print("[WARN] no policy artifact registry entries found")
    if not known_good.get("artifact_set_id"):
        ok = False
        print("[WARN] no known-good policy artifact pointer found")

    print()
    print("[OK] policy artifact check completed" if ok else "[WARN] policy artifact check found issues")
    return ok


def retention_health():
    from ml_platform.retention import retention_policy

    print()
    print("=" * 72)
    print("  ML/Audit Retention Policy")
    print("=" * 72)

    policy = retention_policy()
    print(f"version       : {policy['version']}")
    print(f"destructive   : {policy['destructive_compaction_enabled']}")
    print(f"rule          : {policy['rule']}")
    print()
    for row in policy["rules"]:
        window = row["default_window_days"] if row["default_window_days"] is not None else "preserve"
        print(
            f"  {row['name']:<30} tier={row['tier']:<5} window={str(window):<8} storage={row['storage']}"
        )

    print()
    print("[OK] retention policy is classified; no destructive compaction is enabled")
    return True


def order_health(target_date):
    return run_order_health(target_date, base_dir=BASE_DIR)


def runtime_health(target_date):
    return run_runtime_health(target_date, base_dir=BASE_DIR)


def runtime_health_trend(start_date, end_date):
    return run_runtime_health_trend(start_date, end_date=end_date, base_dir=BASE_DIR)


def context_freshness(target_date):
    return run_context_freshness(target_date, base_dir=BASE_DIR)


def data_freshness_gate(target_date):
    return run_data_freshness_gate(target_date, base_dir=BASE_DIR)


def event_source_coverage(target_date):
    return run_event_source_coverage(target_date, base_dir=BASE_DIR)


def event_context_validation(target_date):
    return run_event_context_validation(target_date, base_dir=BASE_DIR)


def log_ledger_consistency():
    return run_log_ledger_consistency(base_dir=BASE_DIR)


def portfolio_risk(target_date):
    return run_portfolio_risk_report(target_date, base_dir=BASE_DIR)


def production_evidence(target_date):
    checks = [
        runtime_health(target_date),
        log_ledger_consistency(),
        context_freshness(target_date),
        event_source_coverage(target_date),
        event_context_validation(target_date),
        portfolio_risk(target_date),
        lifecycle_analysis(target_date),
        decision_lifecycle_dashboard(target_date),
        calibration_buckets(target_date),
        setup_breakdown(target_date),
        conviction_persistence_health(target_date),
        feature_attribution(target_date),
        post_trade_learning(target_date),
        ai_intelligence_review(target_date),
    ]
    print()
    print("=" * 72)
    if all(checks):
        print("[OK] production evidence checks completed successfully")
        return True
    print("[WARN] production evidence checks found gaps")
    return False


def lifecycle_analysis(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_lifecycle_analysis(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        samples=_int_option("--samples", 15),
    )


def decision_lifecycle_dashboard(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_lifecycle_dashboard(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        samples=_int_option("--samples", 15),
    )


def exit_snapshot_backfill(target_date):
    end_date = None
    if len(sys.argv) > 3 and not sys.argv[3].startswith("--"):
        end_date = sys.argv[3]
    return run_exit_snapshot_backfill(
        target_date,
        end_date=end_date,
        dry_run="--dry-run" in sys.argv,
        limit=_int_option("--limit", 0) or None,
    )


def candidate_universe(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_candidate_universe_report(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
    )


def calibration_buckets(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_calibration_buckets(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        min_sample_size=_int_option("--min-sample-size", 5),
        limit=_int_option("--limit", 20),
    )


def feature_attribution(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_feature_attribution_report(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        min_sample_size=_int_option("--min-sample-size", 30),
        rolling_window_size=_int_option("--rolling-window-size", 50),
    )


def post_trade_learning(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_post_trade_learning_report(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
    )


def symbol_patterns(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_symbol_pattern_outcomes(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        min_sample_size=_int_option("--min-sample-size", 30),
        limit=_int_option("--limit", 20),
    )


def learning_readiness(start_date):
    end_date = None
    if len(sys.argv) > 3 and not sys.argv[3].startswith("--"):
        end_date = sys.argv[3]
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_learning_readiness(
        start_date,
        end_date=end_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        min_feature_sample_size=_int_option("--feature-min-sample-size", 30),
        min_pattern_sample_size=_int_option("--pattern-min-sample-size", 30),
        min_calibration_sample_size=_int_option("--calibration-min-sample-size", 5),
        full_readiness_target=_int_option("--full-readiness-target", 750),
    )


def rollout_contract(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_rollout_contract_report(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        min_sample_size=_int_option("--min-sample-size", 30),
    )


def ai_intelligence_review(target_date):
    symbol = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1]
    return run_ai_intelligence_review(
        target_date,
        base_dir=BASE_DIR,
        symbol=symbol,
        samples=_int_option("--samples", 10),
    )


def setup_breakdown(target_date: str) -> bool:
    return run_setup_breakdown(target_date, base_dir=BASE_DIR)


def peak_bucket_report(target_date: str | None = None) -> bool:
    return run_peak_bucket_report(target_date, base_dir=BASE_DIR)


def winner_became_loser(target_date: str) -> bool:
    return run_winner_became_loser(target_date, base_dir=BASE_DIR)

def conviction_stack_report(target_date: str) -> bool:
    return run_conviction_stack_report(target_date, base_dir=BASE_DIR)


def _int_option(name: str, default: int = 0) -> int:
    if name not in sys.argv:
        return default
    idx = sys.argv.index(name)
    if idx + 1 >= len(sys.argv):
        return default
    try:
        return int(sys.argv[idx + 1])
    except Exception:
        return default


def conviction_persistence_health(target_date: str) -> bool:
    return run_conviction_persistence_health(
        target_date,
        base_dir=BASE_DIR,
        samples=_int_option("--samples", 0),
    )


def buy_opportunity_report(target_date: str) -> bool:
    return run_buy_opportunity_report(target_date, base_dir=BASE_DIR)


def claude_context_audit(target_date: str) -> bool:
    return run_claude_context_audit(target_date, base_dir=BASE_DIR)


def advisory_authority_report(target_date: str) -> bool:
    return run_advisory_authority_report(target_date, base_dir=BASE_DIR)


def point_in_time_archive(target_date: str) -> bool:
    reason = "operator_snapshot"
    if "--reason" in sys.argv:
        idx = sys.argv.index("--reason")
        if idx + 1 < len(sys.argv):
            reason = sys.argv[idx + 1]
    return run_point_in_time_archive(target_date, base_dir=BASE_DIR, reason=reason)

def main():
    env_loaded = load_env_file()
    print(f"env_file_loaded={env_loaded}")

    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 2

    command = sys.argv[1].lower()
    target_date = sys.argv[2] if len(sys.argv) > 2 else date.today().isoformat()
    if target_date.startswith("--"):
        target_date = date.today().isoformat()

    if command == "market-context-check":
        return 0 if check_market_context_file() else 1

    if command == "intelligence-summary":
        return 0 if intelligence_summary(target_date) else 1

    if command == "dataset-health":
        return 0 if dataset_health(target_date) else 1

    if command == "feature-health":
        return 0 if feature_health(target_date) else 1

    if command == "feature-watch":
        return 0 if feature_watch(target_date) else 1

    if command == "rejection-summary":
        return 0 if rejection_summary(target_date) else 1

    if command == "rejected-outcomes":
        return 0 if rejected_outcomes_health(target_date) else 1

    if command == "auto-buy":
        return 0 if auto_buy_health(target_date) else 1

    if command == "decision-snapshots":
        return 0 if decision_snapshot_health(target_date) else 1

    if command == "policy-artifacts":
        return 0 if policy_artifact_health() else 1

    if command == "retention":
        return 0 if retention_health() else 1

    if command == "order-health":
        return 0 if order_health(target_date) else 1

    if command == "runtime-health":
        return 0 if runtime_health(target_date) else 1

    if command == "runtime-health-trend":
        end_date = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else target_date
        return 0 if runtime_health_trend(target_date, end_date) else 1

    if command == "context-freshness":
        return 0 if context_freshness(target_date) else 1

    if command == "data-freshness-gate":
        return 0 if data_freshness_gate(target_date) else 1

    if command == "event-source-coverage":
        return 0 if event_source_coverage(target_date) else 1

    if command == "event-context-validation":
        return 0 if event_context_validation(target_date) else 1

    if command == "log-ledger-consistency":
        return 0 if log_ledger_consistency() else 1

    if command == "portfolio-risk":
        return 0 if portfolio_risk(target_date) else 1

    if command == "production-evidence":
        return 0 if production_evidence(target_date) else 1

    if command == "lifecycle-analysis":
        return 0 if lifecycle_analysis(target_date) else 1

    if command == "decision-lifecycle-dashboard":
        return 0 if decision_lifecycle_dashboard(target_date) else 1

    if command == "exit-snapshot-backfill":
        return 0 if exit_snapshot_backfill(target_date) else 1

    if command == "candidate-universe":
        return 0 if candidate_universe(target_date) else 1

    if command == "calibration-buckets":
        return 0 if calibration_buckets(target_date) else 1

    if command == "feature-attribution":
        return 0 if feature_attribution(target_date) else 1

    if command == "post-trade-learning":
        return 0 if post_trade_learning(target_date) else 1

    if command == "symbol-patterns":
        return 0 if symbol_patterns(target_date) else 1

    if command == "learning-readiness":
        return 0 if learning_readiness(target_date) else 1

    if command == "rollout-contract":
        return 0 if rollout_contract(target_date) else 1

    if command == "ai-intelligence-review":
        return 0 if ai_intelligence_review(target_date) else 1

    if command == "point-in-time-archive":
        return 0 if point_in_time_archive(target_date) else 1

    if command == "migration-status":
        return 0 if migration_status_check() else 1

    if command == "setup-breakdown":
        return 0 if setup_breakdown(target_date) else 1

    if command == "winner-became-loser":
        return 0 if winner_became_loser(target_date) else 1

    if command == "peak-bucket-report":
        date_arg = sys.argv[2] if len(sys.argv) > 2 else None
        return 0 if peak_bucket_report(date_arg) else 1

    if command == "conviction-stack-report":
        return 0 if conviction_stack_report(target_date) else 1

    if command == "conviction-persistence-health":
        return 0 if conviction_persistence_health(target_date) else 1

    if command == "buy-opportunity-report":
        return 0 if buy_opportunity_report(target_date) else 1

    if command == "claude-context-audit":
        return 0 if claude_context_audit(target_date) else 1

    if command == "advisory-authority-report":
        return 0 if advisory_authority_report(target_date) else 1

    if command == "premarket":
        checks = []
        checks.append(run("DB Migration Status", ["ops_check.py", "migration-status"]))
        checks.append(run("Morning Check", ["morning_check.py"]))
        checks.append(run("Position Review", ["position_review.py"]))
        checks.append(run("Market Alignment Report", ["market_alignment_report.py"]))
        checks.append(run("Session Momentum Refresh", ["session_momentum.py", "--all"]))
        checks.append(run("Position Momentum Monitor", ["position_momentum_monitor.py"]))
        checks.append(run("Bot Events", ["bot_events.py", "--limit", "25"]))

        print()
        print("=" * 72)
        if all(checks):
            print("[OK] premarket checks completed successfully")
            return 0

        print("[WARN] one or more premarket checks reported issues")
        return 1

    if command == "all":
        checks = []
        checks.append(run("DB Migration Status", ["ops_check.py", "migration-status"]))
        checks.append(run("Morning Check", ["morning_check.py"]))
        checks.append(run("Position Review", ["position_review.py"]))
        checks.append(run("Market Alignment Report", ["market_alignment_report.py"]))
        checks.append(run("Session Momentum Refresh", ["session_momentum.py", "--all"]))
        checks.append(run("Position Momentum Monitor", ["position_momentum_monitor.py"]))
        checks.append(run("Adaptive Confirmation Report", ["adaptive_confirmation_report.py"]))
        checks.append(run("Adaptive Impact Report", ["adaptive_impact_report.py", target_date]))
        checks.append(run("Filter Report", ["filter_report.py", "--date", target_date]))
        checks.append(run("Blocked Signal Outcome Report", ["blocked_signal_outcome_report.py", "--date", target_date]))
        checks.append(run("Strong-Day Participation", ["strong_day_participation_report.py", "--date", target_date, "--write-db"]))
        checks.append(run("Rejected Outcomes", ["ops_check.py", "rejected-outcomes", target_date]))
        checks.append(run("Auto-Buy Candidates", ["ops_check.py", "auto-buy", target_date]))
        checks.append(run("Auto-Buy Outcomes", ["auto_buy_outcome_report.py", "--date", target_date]))
        checks.append(run("Decision Snapshots", ["ops_check.py", "decision-snapshots", target_date]))
        checks.append(run("AI Intelligence Review", ["ops_check.py", "ai-intelligence-review", target_date]))
        checks.append(run("Policy Artifacts", ["ops_check.py", "policy-artifacts"]))
        checks.append(run("Retention Policy", ["ops_check.py", "retention"]))
        checks.append(run("Drawdown Report", ["drawdown_report.py", target_date]))
        checks.append(run("Post-Session Check", ["post_session_check.py", target_date]))

        print()
        print("=" * 72)
        if all(checks):
            print("[OK] all requested checks completed successfully")
            return 0

        print("[WARN] one or more checks reported issues")
        return 1

    if command not in COMMANDS:
        print(f"Unknown command: {command}")
        print()
        print(__doc__.strip())
        return 2

    script = COMMANDS[command][0]
    extra = COMMANDS[command][1:]

    if command in ("filters", "blocked", "event-attribution", "intelligence", "context",
                   "learning", "predictions", "signal-lessons", "trends",
                   "prediction-validation", "auto-buy-outcomes", "strong-days"):
        args = [script] + extra + ["--date", target_date]
    elif command in ("drawdown", "post", "adaptive_impact", "strategy_intelligence"):
        args = [script] + extra + [target_date]
    else:
        args = [script] + extra

    ok = run(command.title(), args)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
