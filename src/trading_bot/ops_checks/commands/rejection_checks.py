from __future__ import annotations

from pathlib import Path

from rejection_categories import reason_category
from repositories.ops_check_repo import OpsCheckRepository


def _reason_category(reason):
    category = reason_category(reason)
    return "missing" if category == "unknown_error" and not (reason or "").strip() else category


def run_rejection_summary(target_date: str, *, base_dir: Path) -> bool:
    repo = OpsCheckRepository(base_dir / "trades.db")

    print()
    print("=" * 72)
    print(f"  Rejection Summary - {target_date}")
    print("=" * 72)

    if not repo.exists():
        print(f"[FAIL] missing {repo.db_path}")
        return False

    if not repo.table_exists("trades"):
        print("[FAIL] trades table is missing")
        return False

    total = repo.rejection_total_count(target_date)
    approved = repo.rejection_approved_count(target_date)
    rejected = repo.rejection_rejected_count(target_date)

    print("Totals")
    print(f"  trades                 {total:>8}")
    print(f"  approved               {approved:>8}")
    print(f"  rejected               {rejected:>8}")

    print()
    print("By action / approval")
    rows = repo.rejection_action_rows(target_date)
    if rows:
        for r in rows:
            decision = "approved" if int(r["approved"] or 0) == 1 else "rejected"
            print(f"  {r['action']:<8} {decision:<10} {r['n']}")
    else:
        print("  none")

    print()
    print("Rejection categories")
    rows = repo.rejection_reason_rows(target_date)
    if rows:
        buckets = {}
        examples = {}
        for r in rows:
            category = _reason_category(r["rejection_reason"])
            buckets[category] = buckets.get(category, 0) + int(r["n"] or 0)
            examples.setdefault(category, r["rejection_reason"] or "")
        for category, n in sorted(buckets.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {category:<28} {n:>5}  example={examples[category]}")
        unknown_count = buckets.get("unknown_error", 0)
        if unknown_count:
            print(
                f"[WARN] unknown_error rejection category count={unknown_count}; check for log_rejection bypasses"
            )
    else:
        print("  none")

    print()
    print("Top rejected symbols")
    rows = repo.rejected_symbol_rows(target_date)
    if rows:
        for r in rows:
            print(f"  {r['symbol']:<8} {r['n']}")
    else:
        print("  none")

    print()
    print("Recent rejected rows")
    rows = repo.recent_rejected_rows(target_date)
    if rows:
        for r in rows:
            print(
                f"  {r['timestamp']} {r['symbol'] or '-':<6} {r['action'] or '-':<4} "
                f"reason={r['rejection_reason'] or '-'} "
                f"conf={r['confidence'] or '-'} pred={r['prediction_score']}/{r['prediction_decision']} "
                f"setup={r['setup_label'] or '-'} opp={r['buy_opportunity_score']}/{r['buy_opportunity_recommendation']}"
            )
    else:
        print("  none")

    print()
    print("[OK] rejection summary completed")
    return True
