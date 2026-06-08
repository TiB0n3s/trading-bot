"""Composite ops-check command runners."""

from __future__ import annotations

from collections.abc import Callable

RunFn = Callable[[str, list[str]], bool]
RunReportFn = Callable[..., bool]
ScriptFn = Callable[[str], str]
PrintSectionFn = Callable[[str], None]


def run_premarket_bundle(
    *,
    target_date: str,
    run: RunFn,
    run_report: RunReportFn,
    script: ScriptFn,
    print_section: PrintSectionFn,
) -> int:
    checks = []
    checks.append(run("DB Migration Status", ["ops_check.py", "migration-status"]))
    checks.append(run("Morning Check", [script("morning_check.py")]))
    checks.append(run("Position Review", [script("position_review.py")]))
    print_section("Market Alignment Report")
    checks.append(run_report("alignment", target_date))
    checks.append(run("Session Momentum Refresh", [script("session_momentum.py"), "--all"]))
    checks.append(run("Position Momentum Monitor", [script("position_momentum_monitor.py")]))
    checks.append(run("Bot Events", [script("bot_events.py"), "--limit", "25"]))

    print()
    print("=" * 72)
    if all(checks):
        print("[OK] premarket checks completed successfully")
        return 0

    print("[WARN] one or more premarket checks reported issues")
    return 1


def run_all_bundle(
    *,
    target_date: str,
    run: RunFn,
    run_report: RunReportFn,
    script: ScriptFn,
    print_section: PrintSectionFn,
) -> int:
    checks = []
    checks.append(run("DB Migration Status", ["ops_check.py", "migration-status"]))
    checks.append(run("Morning Check", [script("morning_check.py")]))
    checks.append(run("Position Review", [script("position_review.py")]))
    print_section("Market Alignment Report")
    checks.append(run_report("alignment", target_date))
    checks.append(run("Session Momentum Refresh", [script("session_momentum.py"), "--all"]))
    checks.append(run("Position Momentum Monitor", [script("position_momentum_monitor.py")]))
    print_section("Adaptive Confirmation Report")
    checks.append(run_report("adaptive", target_date))
    print_section("Adaptive Impact Report")
    checks.append(run_report("adaptive_impact", target_date))
    print_section("Filter Report")
    checks.append(run_report("filters", target_date))
    print_section("Blocked Signal Outcome Report")
    checks.append(run_report("blocked", target_date))
    print_section("Strong-Day Participation")
    checks.append(run_report("strong-days", target_date, write_db=True))
    checks.append(run("Rejected Outcomes", ["ops_check.py", "rejected-outcomes", target_date]))
    checks.append(run("Auto-Buy Candidates", ["ops_check.py", "auto-buy", target_date]))
    print_section("Auto-Buy Outcomes")
    checks.append(run_report("auto-buy-outcomes", target_date))
    checks.append(run("Decision Snapshots", ["ops_check.py", "decision-snapshots", target_date]))
    checks.append(
        run("AI Intelligence Review", ["ops_check.py", "ai-intelligence-review", target_date])
    )
    checks.append(run("Policy Artifacts", ["ops_check.py", "policy-artifacts"]))
    checks.append(run("Retention Policy", ["ops_check.py", "retention"]))
    print_section("Drawdown Report")
    checks.append(run_report("drawdown", target_date))
    checks.append(run("Post-Session Check", [script("post_session_check.py"), target_date]))

    print()
    print("=" * 72)
    if all(checks):
        print("[OK] all requested checks completed successfully")
        return 0

    print("[WARN] one or more checks reported issues")
    return 1
