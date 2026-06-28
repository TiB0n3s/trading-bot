"""Tests for idempotent client_order_id and atomic cooldown admission.

Covers the idempotency/TOCTOU remediations:
  * make_client_order_id is deterministic (never derives from wall-clock now()),
    so retries of the same logical signal produce the same Alpaca id.
  * claim_cooldown atomically reserves the (symbol, action) slot and blocks a
    concurrent second claim within the window; release_cooldown frees it.
"""

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.persistence.repositories import cooldown_repo
from trading_bot.services.signals.timing import make_client_order_id

WINDOW = 15 * 60


def _make_db(tmp_path) -> str:
    db_path = str(tmp_path / "cooldowns_test.db")
    con = sqlite3.connect(db_path)
    con.execute(
        """
        CREATE TABLE cooldowns (
            symbol          TEXT NOT NULL,
            action          TEXT NOT NULL,
            last_order_time TEXT NOT NULL,
            PRIMARY KEY (symbol, action)
        )
        """
    )
    con.commit()
    con.close()
    return db_path


# --- #3: client_order_id determinism ----------------------------------------

def test_client_order_id_is_deterministic_with_dedupe_key():
    data = {"_dedupe_key": "explicit:abc123", "price": 101.25, "source": "tv"}
    first = make_client_order_id("AAPL", "buy", data)
    second = make_client_order_id("AAPL", "buy", dict(data))
    assert first == second
    assert first.startswith("tb-aapl-buy-")


def test_client_order_id_stable_for_timestampless_retry():
    # Two deliveries of the same logical signal with NO timestamp and NO
    # dedupe key must still produce the SAME id (previously now() made them
    # differ, letting duplicate orders through).
    data = {"symbol": "AAPL", "action": "buy", "price": 101.25, "source": "tv"}
    first = make_client_order_id("AAPL", "buy", dict(data))
    second = make_client_order_id("AAPL", "buy", dict(data))
    assert first == second


def test_client_order_id_distinct_logical_signals_differ():
    base = {"symbol": "AAPL", "action": "buy", "price": 101.25, "source": "tv"}
    a = make_client_order_id("AAPL", "buy", {**base, "_dedupe_key": "hash:one"})
    b = make_client_order_id("AAPL", "buy", {**base, "_dedupe_key": "hash:two"})
    assert a != b


# --- #4: atomic cooldown admission -------------------------------------------

def test_claim_cooldown_blocks_concurrent_second_claim(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now(timezone.utc)

    claimed, prior = cooldown_repo.claim_cooldown("AAPL", "buy", now.isoformat(), WINDOW, db_path=db)
    assert claimed is True
    assert prior is None

    # A second claim within the window must fail (the slot is held).
    claimed2, existing = cooldown_repo.claim_cooldown(
        "AAPL", "buy", (now + timedelta(seconds=5)).isoformat(), WINDOW, db_path=db
    )
    assert claimed2 is False
    assert existing == now.isoformat()


def test_release_cooldown_frees_the_slot(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now(timezone.utc)

    claimed, _ = cooldown_repo.claim_cooldown("AAPL", "buy", now.isoformat(), WINDOW, db_path=db)
    assert claimed is True

    cooldown_repo.release_cooldown("AAPL", "buy", db_path=db)

    # After release, a fresh claim succeeds again.
    claimed2, prior2 = cooldown_repo.claim_cooldown(
        "AAPL", "buy", (now + timedelta(seconds=5)).isoformat(), WINDOW, db_path=db
    )
    assert claimed2 is True
    assert prior2 is None


def test_claim_cooldown_allows_after_window_expiry(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now(timezone.utc)

    claimed, _ = cooldown_repo.claim_cooldown("AAPL", "buy", now.isoformat(), WINDOW, db_path=db)
    assert claimed is True

    # A claim well after the window passes (expired cooldown is overwritten).
    later = now + timedelta(seconds=WINDOW + 60)
    claimed2, prior2 = cooldown_repo.claim_cooldown("AAPL", "buy", later.isoformat(), WINDOW, db_path=db)
    assert claimed2 is True
    assert prior2 == now.isoformat()


def test_conditional_release_does_not_clobber_a_newer_cooldown(tmp_path):
    # Claim at T_A, then a newer cooldown (T_B) is written by another path. A
    # release keyed on the stale T_A must be a no-op (not wipe T_B), so the symbol
    # stays on cooldown and a duplicate order is prevented.
    db = _make_db(tmp_path)
    now = datetime.now(timezone.utc)
    t_a = now.isoformat()
    t_b = (now + timedelta(seconds=30)).isoformat()

    claimed, _ = cooldown_repo.claim_cooldown("AAPL", "buy", t_a, WINDOW, db_path=db)
    assert claimed is True

    # Another writer replaces the row with a newer cooldown.
    cooldown_repo.write_cooldown("AAPL", "buy", t_b, db_path=db)

    # Stale release (claimed_iso=T_A) must NOT clobber T_B.
    cooldown_repo.release_cooldown("AAPL", "buy", db_path=db, claimed_iso=t_a)

    # Slot is still held by T_B: a fresh claim within the window fails.
    claimed2, existing = cooldown_repo.claim_cooldown(
        "AAPL", "buy", (now + timedelta(seconds=40)).isoformat(), WINDOW, db_path=db
    )
    assert claimed2 is False
    assert existing == t_b


def test_conditional_release_deletes_when_timestamp_matches(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now(timezone.utc)
    t_a = now.isoformat()

    claimed, _ = cooldown_repo.claim_cooldown("AAPL", "buy", t_a, WINDOW, db_path=db)
    assert claimed is True

    # Release keyed on the matching timestamp frees the slot.
    cooldown_repo.release_cooldown("AAPL", "buy", db_path=db, claimed_iso=t_a)

    claimed2, prior2 = cooldown_repo.claim_cooldown(
        "AAPL", "buy", (now + timedelta(seconds=5)).isoformat(), WINDOW, db_path=db
    )
    assert claimed2 is True
    assert prior2 is None


def test_claim_cooldown_is_per_symbol_action(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now(timezone.utc)

    assert cooldown_repo.claim_cooldown("AAPL", "buy", now.isoformat(), WINDOW, db_path=db)[0] is True
    # Different action and different symbol are independent slots.
    assert cooldown_repo.claim_cooldown("AAPL", "sell", now.isoformat(), WINDOW, db_path=db)[0] is True
    assert cooldown_repo.claim_cooldown("MSFT", "buy", now.isoformat(), WINDOW, db_path=db)[0] is True
