from __future__ import annotations

from services.ops_checks.conviction_checks import (
    run_buy_opportunity_report,
    run_claude_context_audit,
    run_conviction_stack_report,
)
from services.ops_checks.excursion_checks import (
    run_peak_bucket_report,
    run_winner_became_loser,
)
from services.ops_checks.setup_breakdown import run_setup_breakdown


def test_ops_checks_return_false_when_db_missing(tmp_path, capsys):
    funcs = [
        lambda: run_setup_breakdown("2026-05-30", base_dir=tmp_path),
        lambda: run_peak_bucket_report("2026-05-30", base_dir=tmp_path),
        lambda: run_winner_became_loser("2026-05-30", base_dir=tmp_path),
        lambda: run_conviction_stack_report("2026-05-30", base_dir=tmp_path),
        lambda: run_buy_opportunity_report("2026-05-30", base_dir=tmp_path),
        lambda: run_claude_context_audit("2026-05-30", base_dir=tmp_path),
    ]

    for func in funcs:
        assert func() is False

    out = capsys.readouterr().out
    assert out.count("[WARN] trades.db not found") == len(funcs)
