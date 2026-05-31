from __future__ import annotations

import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.ops_checks.conviction_checks import (
    run_buy_opportunity_report,
    run_claude_context_audit,
    run_conviction_stack_report,
)
from services.ops_checks.advisory_authority_checks import run_advisory_authority_report
from services.ops_checks.excursion_checks import (
    run_peak_bucket_report,
    run_winner_became_loser,
)
from services.ops_checks.setup_breakdown import run_setup_breakdown


def test_ops_checks_return_false_when_db_missing(tmp_path):
    funcs = [
        lambda: run_setup_breakdown("2026-05-30", base_dir=tmp_path),
        lambda: run_peak_bucket_report("2026-05-30", base_dir=tmp_path),
        lambda: run_winner_became_loser("2026-05-30", base_dir=tmp_path),
        lambda: run_conviction_stack_report("2026-05-30", base_dir=tmp_path),
        lambda: run_buy_opportunity_report("2026-05-30", base_dir=tmp_path),
        lambda: run_claude_context_audit("2026-05-30", base_dir=tmp_path),
        lambda: run_advisory_authority_report("2026-05-30", base_dir=tmp_path),
    ]

    buf = io.StringIO()
    with redirect_stdout(buf):
        for func in funcs:
            assert func() is False

    out = buf.getvalue()
    assert out.count("[WARN] trades.db not found") == len(funcs)


def main():
    tests = [test_ops_checks_return_false_when_db_missing]
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} ops check service tests passed.")


if __name__ == "__main__":
    main()
