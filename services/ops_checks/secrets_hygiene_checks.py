"""Local secrets hygiene checks.

This report never prints secret values. It checks storage and repository hygiene
around the current `/etc/trading-bot.env` workflow.
"""

from __future__ import annotations

import stat
from pathlib import Path

SENSITIVE_MARKERS = (
    "SECRET",
    "API_KEY",
    "TOKEN",
    "PASSWORD",
    "PRIVATE_KEY",
)


def _mode(path: Path) -> int | None:
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return None


def _gitignore_contains_env(base_dir: Path) -> bool:
    gitignore = base_dir / ".gitignore"
    if not gitignore.exists():
        return False
    lines = {line.strip() for line in gitignore.read_text(errors="replace").splitlines()}
    return any(item in lines for item in {".env", "*.env", "trading-bot.env"})


def _dockerfile_mentions_env_file(base_dir: Path) -> bool:
    dockerfile = base_dir / "Dockerfile"
    if not dockerfile.exists():
        return False
    text = dockerfile.read_text(errors="replace")
    return "trading-bot.env" in text or "/etc/trading-bot.env" in text


def _repo_secret_file_candidates(base_dir: Path) -> list[str]:
    candidates = []
    for path in base_dir.rglob("*"):
        if ".git" in path.parts or "venv" in path.parts or not path.is_file():
            continue
        name = path.name.lower()
        if name in {".env", "trading-bot.env"} or name.endswith(".env"):
            candidates.append(path.relative_to(base_dir).as_posix())
    return sorted(candidates)


def _sensitive_key_count(env_file: Path) -> int:
    if not env_file.exists():
        return 0
    count = 0
    for raw in env_file.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip().upper()
        if any(marker in key for marker in SENSITIVE_MARKERS):
            count += 1
    return count


def build_secrets_hygiene_payload(*, base_dir: Path, env_file: Path) -> dict:
    mode = _mode(env_file)
    env_exists = env_file.exists()
    group_or_world_readable = bool(mode is not None and mode & 0o077)
    repo_candidates = _repo_secret_file_candidates(base_dir)
    dockerfile_mentions_env = _dockerfile_mentions_env_file(base_dir)
    gitignore_has_env = _gitignore_contains_env(base_dir)

    findings = []
    if not env_exists:
        findings.append("env_file_missing")
    if group_or_world_readable:
        findings.append("env_file_group_or_world_accessible")
    if repo_candidates:
        findings.append("repo_env_file_candidates_present")
    if dockerfile_mentions_env:
        findings.append("dockerfile_mentions_runtime_env_file")
    if not gitignore_has_env:
        findings.append("gitignore_missing_env_pattern")

    return {
        "report_version": "secrets_hygiene_v1",
        "runtime_effect": "diagnostic_only_no_secret_values_printed",
        "env_file": str(env_file),
        "env_file_exists": env_exists,
        "env_file_mode": oct(mode) if mode is not None else None,
        "env_file_group_or_world_accessible": group_or_world_readable,
        "sensitive_key_count": _sensitive_key_count(env_file),
        "repo_env_file_candidates": repo_candidates,
        "dockerfile_mentions_env_file": dockerfile_mentions_env,
        "gitignore_has_env_pattern": gitignore_has_env,
        "findings": findings,
        "ok": not findings,
    }


def run_secrets_hygiene_report(*, base_dir: Path, env_file: Path) -> bool:
    payload = build_secrets_hygiene_payload(base_dir=base_dir, env_file=env_file)

    print()
    print("=" * 72)
    print("  Secrets Hygiene")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"env_file                : {payload['env_file']}")
    print(f"env_file_exists         : {payload['env_file_exists']}")
    print(f"env_file_mode           : {payload['env_file_mode'] or '-'}")
    print(f"sensitive_key_count     : {payload['sensitive_key_count']}")
    print(f"gitignore_has_env       : {payload['gitignore_has_env_pattern']}")
    print(f"dockerfile_mentions_env : {payload['dockerfile_mentions_env_file']}")

    print()
    print("Repo env-file candidates")
    candidates = payload["repo_env_file_candidates"]
    if not candidates:
        print("  -")
    else:
        for item in candidates:
            print(f"  {item}")

    print()
    if payload["ok"]:
        print("[OK] local secrets hygiene checks passed")
        return True
    print(f"[WARN] secrets hygiene findings: {', '.join(payload['findings'])}")
    return False
