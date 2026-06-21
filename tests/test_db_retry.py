#!/usr/bin/env python3
"""Unit tests for db.retry_on_locked / db.is_database_locked_error."""
# ruff: noqa: E402

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import db


def test_is_database_locked_error_true_only_for_locked_operational_error():
    assert db.is_database_locked_error(sqlite3.OperationalError("database is locked")) is True
    assert db.is_database_locked_error(sqlite3.OperationalError("DATABASE IS LOCKED")) is True
    assert db.is_database_locked_error(sqlite3.OperationalError("no such table: x")) is False
    assert db.is_database_locked_error(ValueError("database is locked")) is False


def test_returns_value_on_first_success(monkeypatch):
    calls = {"n": 0}
    slept: list[float] = []
    monkeypatch.setattr(db.time, "sleep", lambda s: slept.append(s))

    def fn():
        calls["n"] += 1
        return "ok"

    assert db.retry_on_locked(fn) == "ok"
    assert calls["n"] == 1
    assert slept == []  # no retry, no backoff


def test_retries_then_succeeds_with_linear_backoff(monkeypatch):
    calls = {"n": 0}
    slept: list[float] = []
    monkeypatch.setattr(db.time, "sleep", lambda s: slept.append(s))

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return 42

    assert db.retry_on_locked(fn, max_attempts=3, delay_seconds=0.25) == 42
    assert calls["n"] == 3
    # backoff is delay * (attempt + 1) for attempts 0 and 1
    assert slept == [0.25, 0.5]


def test_exhausts_attempts_then_reraises_last_lock_error(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(db.time, "sleep", lambda s: None)

    def fn():
        calls["n"] += 1
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        db.retry_on_locked(fn, max_attempts=3)
    assert calls["n"] == 3  # tried exactly max_attempts times


def test_non_lock_operational_error_propagates_immediately(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(db.time, "sleep", lambda s: None)

    def fn():
        calls["n"] += 1
        raise sqlite3.OperationalError("no such table: trades")

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        db.retry_on_locked(fn)
    assert calls["n"] == 1  # no retry on non-lock errors


def test_non_operational_exception_propagates_immediately(monkeypatch):
    monkeypatch.setattr(db.time, "sleep", lambda s: None)

    def fn():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        db.retry_on_locked(fn)
