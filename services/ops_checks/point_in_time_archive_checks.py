"""Point-in-time context archive operator action."""

from __future__ import annotations

from pathlib import Path

from services.point_in_time_archive_service import PointInTimeArchiveService


def run_point_in_time_archive(
    target_date: str,
    *,
    base_dir: Path,
    reason: str = "operator_snapshot",
) -> bool:
    print()
    print("=" * 72)
    print(f"  Point-in-Time Context Archive - {target_date}")
    print("=" * 72)

    result = PointInTimeArchiveService(base_dir=base_dir).archive_current_context(
        archive_date=target_date,
        reason=reason,
    )
    print(f"archive_version       : {result.payload['version']}")
    print(f"archive_path          : {result.archive_path.relative_to(base_dir)}")
    print(f"archive_hash          : {result.archive_hash}")
    print(f"market_context_hash   : {result.payload.get('market_context_hash') or '-'}")
    print(f"symbol_overrides_hash : {result.payload.get('symbol_overrides_hash') or '-'}")
    print(f"policy_artifact_count : {len(result.payload.get('policy_artifact_refs') or {})}")
    print()
    print("[OK] point-in-time context archive written")
    return True
