"""Feature flag inventory derived from static env-var references."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.config_audit_service import discover_env_var_references

FLAG_TOKENS = (
    "ENABLED",
    "MODE",
    "AUTHORITY",
    "LIVE",
    "BLOCK",
    "SIZE_DOWN",
    "GATE",
    "POLICY",
    "KILL",
)

HIGH_AUTHORITY_TOKENS = ("LIVE", "AUTHORITY", "BLOCK", "GATE", "POLICY")


def _is_feature_flag(name: str) -> bool:
    upper = name.upper()
    return any(token in upper for token in FLAG_TOKENS)


def _authority_level(name: str) -> str:
    upper = name.upper()
    if "LIVE" in upper or "AUTHORITY" in upper:
        return "high"
    if any(token in upper for token in ("BLOCK", "GATE", "POLICY")):
        return "medium"
    return "low"


def _owner_from_files(files: list[str]) -> str:
    joined = " ".join(files)
    if "ml" in joined or "prediction" in joined or "transformer" in joined:
        return "ml_platform"
    if "risk" in joined or "sizing" in joined or "policy" in joined:
        return "risk_policy"
    if "market_data" in joined or "bar" in joined or "polygon" in joined:
        return "market_data"
    if "pipeline" in joined or "ops_checks" in joined:
        return "operations"
    return "runtime"


def _rollback_action(name: str) -> str:
    upper = name.upper()
    if upper.endswith("_MODE"):
        return "set to observe_only, compare, warn, or off"
    if "LIVE" in upper or "AUTHORITY" in upper or "ENABLED" in upper:
        return "set false/off unless explicitly required"
    return "restore documented default"


def build_feature_flag_inventory(*, base_dir: Path) -> dict[str, Any]:
    inventory = discover_env_var_references(base_dir)
    rows = []
    for name, files in inventory["env_keys"].items():
        if not _is_feature_flag(name):
            continue
        file_list = list(files)
        rows.append(
            {
                "name": name,
                "owner": _owner_from_files(file_list),
                "authority_level": _authority_level(name),
                "rollback_action": _rollback_action(name),
                "files": file_list,
                "file_count": len(file_list),
            }
        )
    rows.sort(key=lambda row: (row["authority_level"], row["owner"], row["name"]))
    high_authority = [row for row in rows if row["authority_level"] == "high"]
    missing_rollback = [row["name"] for row in rows if not row["rollback_action"]]
    return {
        "report_version": "feature_flag_inventory_v1",
        "runtime_effect": "diagnostic_only_no_runtime_config_change",
        "flag_count": len(rows),
        "high_authority_count": len(high_authority),
        "missing_rollback_count": len(missing_rollback),
        "owners": {
            owner: sum(1 for row in rows if row["owner"] == owner)
            for owner in sorted({row["owner"] for row in rows})
        },
        "flags": rows,
        "ready": bool(rows) and not missing_rollback,
    }
