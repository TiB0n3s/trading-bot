#!/usr/bin/env python3
"""Tests for local secrets hygiene diagnostics."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trading_bot.ops_checks.commands.secrets_hygiene_checks import (  # noqa: E402
    build_secrets_hygiene_payload,
)


def test_secrets_hygiene_passes_for_private_external_env_file():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp) / "repo"
        external_dir = Path(tmp) / "etc"
        base_dir.mkdir()
        external_dir.mkdir()
        (base_dir / ".gitignore").write_text(".env\n*.env\n")
        (base_dir / "Dockerfile").write_text("FROM python:3.12-slim\n")
        env_file = external_dir / "trading-bot.env"
        env_file.write_text("WEBHOOK_SECRET=redacted\nPOLYGON_API_KEY=redacted\n")
        os.chmod(env_file, 0o600)

        payload = build_secrets_hygiene_payload(base_dir=base_dir, env_file=env_file)

        assert payload["ok"] is True
        assert payload["sensitive_key_count"] == 2
        assert payload["repo_env_file_candidates"] == []


def test_secrets_hygiene_warns_for_world_readable_or_repo_env_files():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp) / "repo"
        base_dir.mkdir()
        (base_dir / ".gitignore").write_text(".env\n")
        env_file = base_dir / ".env"
        env_file.write_text("WEBHOOK_SECRET=redacted\n")
        os.chmod(env_file, 0o644)

        payload = build_secrets_hygiene_payload(base_dir=base_dir, env_file=env_file)

        assert payload["ok"] is False
        assert "env_file_group_or_world_accessible" in payload["findings"]
        assert "repo_env_file_candidates_present" in payload["findings"]
        assert ".env" in payload["repo_env_file_candidates"]


if __name__ == "__main__":
    test_secrets_hygiene_passes_for_private_external_env_file()
    test_secrets_hygiene_warns_for_world_readable_or_repo_env_files()
    print("secrets hygiene checks tests passed")
