#!/usr/bin/env python3
"""Audit deployed scheduler/service references for missing repo files.

This catches the failure mode where cleanup moves root scripts into ``scripts/``
but cron or systemd still invokes the old path.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SYSTEMD_DIR = Path("/etc/systemd/system")

REFERENCE_RE = re.compile(
    r"/home/tradingbot/trading-bot/([^\s\"']+\.(?:py|sh))\b"
    r"|(?<![\w./-])([A-Za-z0-9_./-]+\.(?:py|sh))\b"
)


@dataclass(frozen=True)
class MissingReference:
    source: str
    line_no: int
    reference: str
    suggested_path: str | None = None


def _candidate_path(repo_root: Path, reference: str) -> Path:
    if reference.startswith("/"):
        return Path(reference)
    return repo_root / reference


def _suggestion(repo_root: Path, reference: str) -> str | None:
    name = Path(reference).name
    for prefix in ("scripts", "pipeline", "ops"):
        candidate = repo_root / prefix / name
        if candidate.exists():
            return str(candidate.relative_to(repo_root))
    return None


def missing_references_in_text(
    text: str,
    *,
    source: str,
    repo_root: Path = REPO_ROOT,
) -> list[MissingReference]:
    missing: list[MissingReference] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for match in REFERENCE_RE.finditer(line):
            reference = match.group(1) or match.group(2)
            if not reference or reference.startswith("venv/"):
                continue
            if _candidate_path(repo_root, reference).exists():
                continue
            missing.append(
                MissingReference(
                    source=source,
                    line_no=line_no,
                    reference=reference,
                    suggested_path=_suggestion(repo_root, reference),
                )
            )
    return missing


def current_crontab_text() -> str:
    try:
        return subprocess.check_output(["crontab", "-l"], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return ""


def systemd_unit_texts(systemd_dir: Path = SYSTEMD_DIR) -> list[tuple[str, str]]:
    units: list[tuple[str, str]] = []
    if not systemd_dir.exists():
        return units
    for unit in sorted(systemd_dir.glob("*.service")):
        try:
            text = unit.read_text()
        except (OSError, PermissionError):
            continue
        if str(REPO_ROOT) in text:
            units.append((str(unit), text))
    return units


def audit_deployment_references(repo_root: Path = REPO_ROOT) -> list[MissingReference]:
    missing: list[MissingReference] = []
    missing.extend(
        missing_references_in_text(
            current_crontab_text(),
            source="crontab",
            repo_root=repo_root,
        )
    )
    snapshot = repo_root / "ops" / "crontab.tradingbot.current.txt"
    if snapshot.exists():
        missing.extend(
            missing_references_in_text(
                snapshot.read_text(),
                source=str(snapshot.relative_to(repo_root)),
                repo_root=repo_root,
            )
        )
    for source, text in systemd_unit_texts():
        missing.extend(missing_references_in_text(text, source=source, repo_root=repo_root))
    return missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    args = parser.parse_args()

    missing = audit_deployment_references(Path(args.repo_root))
    print("deployment_reference_audit_v1")
    print(f"repo_root={args.repo_root}")
    print(f"missing_references={len(missing)}")
    for item in missing:
        suffix = f" suggested={item.suggested_path}" if item.suggested_path else ""
        print(f"{item.source}:{item.line_no}: missing {item.reference}{suffix}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
