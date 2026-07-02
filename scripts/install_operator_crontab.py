#!/usr/bin/env python3
"""Install the repo-owned operator crontab reference.

The checked-in crontab is the scheduler source of truth. This script exists so
operator installs follow one path: inspect drift, back up the current installed
crontab, apply the repo reference, and verify the installed commands match.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trading_bot.ops_checks.commands.scheduler_drift_checks import compare_crontabs  # noqa: E402


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference",
        default=str(ROOT / "ops" / "crontab.tradingbot.current.txt"),
        help="Checked-in crontab file to install.",
    )
    parser.add_argument(
        "--backup-dir",
        default=str(ROOT / "migration"),
        help="Directory for the pre-install installed-crontab backup.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually install the reference. Without this flag the script only reports drift.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Return non-zero when the installed crontab differs from the reference.",
    )
    return parser.parse_args(argv)


def backup_path(backup_dir: Path, *, now: datetime | None = None) -> Path:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return backup_dir / f"crontab.backup.{timestamp}.before-install-reference.bak"


def read_installed_crontab() -> tuple[bool, str]:
    result = subprocess.run(
        ["crontab", "-l"],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if result.returncode == 0:
        return True, result.stdout
    detail = (result.stderr or result.stdout or "").strip()
    if "no crontab for" in detail.lower():
        return True, ""
    return False, detail


def install_reference(reference_path: Path) -> tuple[bool, str]:
    result = subprocess.run(
        ["crontab", str(reference_path)],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or result.stdout or "").strip()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    reference_path = Path(args.reference)
    backup_dir = Path(args.backup_dir)

    print("operator_crontab_install_v1")
    print(f"reference={reference_path}")
    print(f"apply={args.apply}")
    print(f"check={args.check}")

    if not reference_path.exists():
        print(f"[FAIL] reference crontab is missing: {reference_path}")
        return 1

    ok, installed = read_installed_crontab()
    if not ok:
        print("[FAIL] could not read installed user crontab")
        print(f"detail={installed or '-'}")
        return 1

    reference_text = reference_path.read_text()
    drift = compare_crontabs(reference_text, installed)
    print(f"missing_lines={len(drift.missing)}")
    print(f"extra_lines={len(drift.extra)}")

    if not args.apply:
        print("[DRY-RUN] no crontab changes made")
        if args.check and not drift.ok:
            return 1
        return 0

    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_path(backup_dir)
    backup.write_text(installed)
    print(f"backup={backup}")

    installed_ok, detail = install_reference(reference_path)
    if not installed_ok:
        print("[FAIL] crontab install failed")
        print(f"detail={detail or '-'}")
        return 1

    ok, installed_after = read_installed_crontab()
    if not ok:
        print("[FAIL] could not read installed user crontab after install")
        print(f"detail={installed_after or '-'}")
        return 1

    post_drift = compare_crontabs(reference_text, installed_after)
    print(f"post_install_missing_lines={len(post_drift.missing)}")
    print(f"post_install_extra_lines={len(post_drift.extra)}")
    if not post_drift.ok:
        print("[FAIL] installed crontab differs from reference after install")
        return 1

    print("[OK] installed crontab now matches checked-in reference")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
