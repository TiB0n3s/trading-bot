"""SQLite ownership diagnostics for container/runtime planning."""

from __future__ import annotations

from pathlib import Path

SQLITE_OWNERSHIP_VERSION = "sqlite_ownership_contract_v1"


DB_CONTRACTS = (
    {
        "db_file": "trades.db",
        "primary_writer": "live runtime/order/audit services",
        "allowed_concurrent_research": "read-only only",
        "risk": "highest",
        "required": True,
    },
    {
        "db_file": "predictions.db",
        "primary_writer": "optional future split prediction store; current prediction tables live in trades.db",
        "allowed_concurrent_research": "not applicable unless the split DB exists",
        "risk": "medium",
        "required": False,
    },
    {
        "db_file": "jobs.db",
        "primary_writer": "job_runner / scheduled job ledger",
        "allowed_concurrent_research": "read-only dashboards",
        "risk": "medium",
        "required": False,
    },
)


def run_sqlite_ownership_report(*, base_dir: Path) -> bool:
    print()
    print("=" * 72)
    print("  SQLite Ownership Contract")
    print("=" * 72)
    print(f"report_version          : {SQLITE_OWNERSHIP_VERSION}")
    print("runtime_effect          : diagnostic_only_no_live_authority")
    print("volume_rule             : same-host bind mount only; never NFS/network volume")
    print("writer_rule             : at most one writer per database file")
    print()
    print("DB files")
    required_present = True
    for row in DB_CONTRACTS:
        path = base_dir / row["db_file"]
        present = path.exists()
        if row.get("required"):
            required_present = required_present and present
        print(
            f"  {row['db_file']:<16} present={str(present):<5} "
            f"required={str(row.get('required')):<5} risk={row['risk']:<7} "
            f"writer={row['primary_writer']}"
        )
        print(f"      concurrent research: {row['allowed_concurrent_research']}")
    print()
    if required_present:
        print("[OK] SQLite ownership contract is inspectable")
        return True
    print("[WARN] required SQLite DB files are not present")
    return False
