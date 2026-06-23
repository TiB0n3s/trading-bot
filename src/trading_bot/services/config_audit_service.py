"""Configuration inventory and safety audit.

The audit is diagnostic-only. It validates the existing typed config factories
and inventories remaining raw env-var access so configuration sprawl can be
reduced deliberately without changing runtime behavior.
"""

from __future__ import annotations

import ast
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import runtime_config
from services.runtime_safety_profile_service import (
    build_runtime_safety_profile,
    runtime_safety_warnings,
)

from config import (
    load_auto_buy_config,
    load_ml_config,
    load_position_manager_config,
    load_risk_config,
    load_signal_config,
)

CONFIG_AUDIT_VERSION = "config_audit_v1"
CONFIG_AUDIT_RUNTIME_EFFECT = "diagnostic_only_no_runtime_config_change"
SENSITIVE_TOKENS = ("KEY", "SECRET", "TOKEN", "PASSWORD")
SOURCE_ROOTS = (
    "*.py",
    "api/**/*.py",
    "config/**/*.py",
    "pipeline/**/*.py",
    "repositories/**/*.py",
    "risk/**/*.py",
    "scripts/**/*.py",
    "services/**/*.py",
)


@dataclass(frozen=True)
class ConfigFactoryAudit:
    name: str
    status: str
    fields: int
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_sensitive(name: str) -> bool:
    upper = name.upper()
    return any(token in upper for token in SENSITIVE_TOKENS)


def _literal_env_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_call_name(node.value)}.{node.attr}".strip(".")
    if isinstance(node, ast.Name):
        return node.id
    return ""


def discover_env_var_references(base_dir: Path) -> dict[str, Any]:
    references: dict[str, set[str]] = {}
    non_literal_calls: list[str] = []
    for pattern in SOURCE_ROOTS:
        for path in base_dir.glob(pattern):
            if not path.is_file() or path.name.endswith(".pyc"):
                continue
            try:
                tree = ast.parse(path.read_text())
            except Exception:
                continue
            rel = str(path.relative_to(base_dir))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                call_name = _call_name(node.func)
                is_getenv = call_name in {"os.getenv", "getenv", "env_get"}
                value_node = getattr(node.func, "value", None)
                is_environ_get = (
                    call_name.endswith(".get")
                    and value_node is not None
                    and _call_name(value_node) in {"os.environ", "environ"}
                )
                if not (is_getenv or is_environ_get):
                    continue
                if not node.args:
                    continue
                env_name = _literal_env_name(node.args[0])
                if env_name:
                    references.setdefault(env_name, set()).add(rel)
                else:
                    non_literal_calls.append(rel)
    by_file: dict[str, int] = {}
    for files in references.values():
        for file_name in files:
            by_file[file_name] = by_file.get(file_name, 0) + 1
    return {
        "total_env_keys": len(references),
        "sensitive_env_keys": sorted(name for name in references if _is_sensitive(name)),
        "by_file": dict(sorted(by_file.items(), key=lambda item: (-item[1], item[0]))),
        "env_keys": {
            name: sorted(files)
            for name, files in sorted(references.items(), key=lambda item: item[0])
        },
        "non_literal_call_files": sorted(set(non_literal_calls)),
    }


def _factory_audit(name: str, loader) -> ConfigFactoryAudit:
    try:
        config = loader()
    except Exception as exc:
        return ConfigFactoryAudit(
            name=name,
            status="fail",
            fields=0,
            reason=str(exc),
        )
    fields = len(getattr(config, "__dataclass_fields__", {}) or {})
    return ConfigFactoryAudit(name=name, status="ok", fields=fields)


@contextmanager
def _temporary_environ(env: dict[str, str]):
    original = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(env)
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _runtime_warnings(env: dict[str, str]) -> list[str]:
    warnings: list[str] = []
    execution_mode = env.get("EXECUTION_MODE", runtime_config.EXECUTION_MODE).strip().lower()
    live_trading_enabled = env.get(
        "LIVE_TRADING_ENABLED",
        str(runtime_config.LIVE_TRADING_ENABLED),
    ).strip().lower() in {"1", "true", "yes", "on"}
    ml_authority_mode = (
        env.get(
            "ML_AUTHORITY_MODE",
            runtime_config.ML_AUTHORITY_MODE,
        )
        .strip()
        .lower()
    )
    if env.get("ALLOW_QUERY_STRING_SECRET", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        warnings.append("ALLOW_QUERY_STRING_SECRET is enabled")
    if execution_mode in {"cash_safe", "cash_full"} and not live_trading_enabled:
        warnings.append("cash execution mode selected while LIVE_TRADING_ENABLED is false")
    if execution_mode == "cash_full":
        warnings.append("EXECUTION_MODE=cash_full requires explicit operator review")
    if ml_authority_mode == "live_block":
        warnings.append("ML_AUTHORITY_MODE=live_block requires current promotion evidence")
    if env.get("TRANSFORMER_AUTHORITY_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    } and not env.get("TRANSFORMER_MODEL_ID"):
        warnings.append("Transformer authority enabled without TRANSFORMER_MODEL_ID")
    return warnings


def build_config_audit_payload(
    *,
    base_dir: Path,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if env is None else env)
    execution_mode = env.get("EXECUTION_MODE", runtime_config.EXECUTION_MODE).strip().lower()
    live_trading_enabled = env.get(
        "LIVE_TRADING_ENABLED",
        str(runtime_config.LIVE_TRADING_ENABLED),
    ).strip().lower() in {"1", "true", "yes", "on"}
    with _temporary_environ(env):
        factories = [
            _factory_audit("signal", load_signal_config),
            _factory_audit("risk", load_risk_config),
            _factory_audit("auto_buy", load_auto_buy_config),
            _factory_audit("position_manager", load_position_manager_config),
            _factory_audit("ml", load_ml_config),
        ]
    inventory = discover_env_var_references(base_dir)
    warnings = _runtime_warnings(env)
    safety_profile = build_runtime_safety_profile(env)
    safety_profile_payload = safety_profile.to_dict()
    safety_profile_warnings = runtime_safety_warnings(safety_profile)
    return {
        "version": CONFIG_AUDIT_VERSION,
        "runtime_effect": CONFIG_AUDIT_RUNTIME_EFFECT,
        "execution_mode": execution_mode,
        "live_trading_enabled": live_trading_enabled,
        "factory_count": len(factories),
        "factory_failures": sum(1 for item in factories if item.status != "ok"),
        "factories": [item.to_dict() for item in factories],
        "env_inventory": {
            "total_env_keys": inventory["total_env_keys"],
            "sensitive_env_key_count": len(inventory["sensitive_env_keys"]),
            "top_files": list(inventory["by_file"].items())[:12],
            "non_literal_call_files": inventory["non_literal_call_files"][:12],
        },
        "warnings": warnings,
        "runtime_safety_profile": {
            **safety_profile_payload,
            "warnings": safety_profile_warnings,
            "ready": not safety_profile_warnings,
        },
        "ready": not warnings and all(item.status == "ok" for item in factories),
    }
