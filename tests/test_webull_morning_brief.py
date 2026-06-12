from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from pre_market_research_data import apply_webull_morning_brief_context  # noqa: E402

from market_intelligence.webull_morning_brief import (  # noqa: E402
    load_webull_morning_brief_state,
    normalize_webull_morning_brief_state,
)


def test_webull_morning_brief_normalizes_macro_and_symbol_context():
    state = normalize_webull_morning_brief_state(
        {
            "brief_date": "2026-06-12",
            "published_at": "2026-06-12T08:00:00-04:00",
            "index_futures": {
                "NQ": {"value": 29451.75, "pct_change": -0.04},
                "ES": {"value": 7416.75, "pct_change": 0.28},
                "YM": {"value": 51181, "pct_change": 0.60},
            },
            "technical_signal_balance": {"long_term": {"bullish": 15, "bearish": 6}},
            "symbols": {
                "RDW": {
                    "brief_signal": "top_followed_sharp_decline",
                    "event_bias": "caution",
                    "pct_change": -8.60,
                }
            },
        }
    )

    assert state["available"] is True
    assert state["macro_read"] == "mixed_constructive"
    assert state["technical_signal_balance"]["long_term"]["net_bullish"] == 9
    assert state["symbols"]["RDW"]["event_bias"] == "caution"


def test_load_webull_morning_brief_handles_missing_file(tmp_path):
    state = load_webull_morning_brief_state(tmp_path / "missing.json")

    assert state["available"] is False
    assert state["symbols"] == {}


def test_apply_webull_morning_brief_marks_symbol_context(tmp_path):
    path = tmp_path / "webull.json"
    path.write_text(
        json.dumps(
            {
                "brief_date": "2026-06-12",
                "published_at": "2026-06-12T08:00:00-04:00",
                "symbols": {
                    "RDW": {
                        "brief_signal": "top_followed_sharp_decline",
                        "event_bias": "caution",
                        "pct_change": -8.60,
                    }
                },
            }
        )
    )
    state = load_webull_morning_brief_state(path)
    entry = {
        "bias": "neutral",
        "key_risks": [],
        "key_catalysts": [],
        "performance_evidence": [],
    }

    apply_webull_morning_brief_context("RDW", entry, state)

    assert entry["webull_morning_brief_context"]["event_bias"] == "caution"
    assert any("Webull morning brief caution" in item for item in entry["key_risks"])
    assert (
        "webull_morning_brief:caution:top_followed_sharp_decline" in entry["performance_evidence"]
    )


def main():
    import tempfile

    test_webull_morning_brief_normalizes_macro_and_symbol_context()
    print("[OK] test_webull_morning_brief_normalizes_macro_and_symbol_context")
    with tempfile.TemporaryDirectory() as tmp:
        test_load_webull_morning_brief_handles_missing_file(Path(tmp))
        print("[OK] test_load_webull_morning_brief_handles_missing_file")
    with tempfile.TemporaryDirectory() as tmp:
        test_apply_webull_morning_brief_marks_symbol_context(Path(tmp))
        print("[OK] test_apply_webull_morning_brief_marks_symbol_context")
    print("\nAll 3 Webull morning brief tests passed.")


if __name__ == "__main__":
    main()
