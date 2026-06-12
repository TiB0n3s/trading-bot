from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from pre_market_research_data import apply_webull_market_context  # noqa: E402

from market_intelligence.webull_market_evidence import (  # noqa: E402
    load_webull_market_evidence_state,
    normalize_webull_market_evidence_state,
)


def test_webull_market_evidence_normalizes_screener_news_and_attention():
    state = normalize_webull_market_evidence_state(
        {
            "published_at": "2026-06-12T09:45:00-04:00",
            "screeners": {
                "top_active": [
                    {
                        "symbol": "SOFI",
                        "rank": 3,
                        "relative_volume_10d": "2.4",
                        "volume": "12000000",
                    }
                ],
                "gainers": [{"ticker": "SOFI", "change_pct": "4.2"}],
            },
            "news": {
                "summaries": [
                    {
                        "symbol": "SOFI",
                        "sentiment": "positive",
                        "summary": "Watchlist news summary.",
                    }
                ]
            },
            "attention": {"symbols": {"SOFI": {"attention_rank": 5, "attention_count": "961"}}},
        }
    )

    context = state["symbols"]["SOFI"]
    assert state["available"] is True
    assert context["screener"]["top_active_rank"] == 3
    assert context["screener"]["gainer_rank"] == 1
    assert context["screener"]["relative_volume_10d"] == 2.4
    assert context["news"]["positive_count"] == 1
    assert context["attention"]["attention_count"] == 961
    assert context["authority"] == "webull_context_only_no_standalone_trade_authority"


def test_load_webull_market_evidence_handles_missing_file(tmp_path):
    state = load_webull_market_evidence_state(tmp_path / "missing.json")

    assert state["available"] is False
    assert state["symbols"] == {}


def test_apply_webull_market_context_adds_learning_tags_without_authority(tmp_path):
    path = tmp_path / "webull_market.json"
    path.write_text(
        json.dumps(
            {
                "published_at": "2026-06-12T09:45:00-04:00",
                "screeners": {
                    "losers": [{"symbol": "RDW", "rank": 2, "change_pct": -8.6}],
                    "top_active": [{"symbol": "RDW", "rank": 8, "relative_volume_10d": 3.1}],
                },
                "news": {"symbols": {"RDW": {"tone": "negative", "summary": "Risk update."}}},
                "attention": {"symbols": {"RDW": {"rank": 2, "attention_count": 2000}}},
            }
        )
    )
    state = load_webull_market_evidence_state(path)
    entry = {
        "bias": "neutral",
        "key_risks": [],
        "key_catalysts": [],
        "performance_evidence": [],
    }

    apply_webull_market_context("RDW", entry, state)

    context = entry["webull_market_context"]
    assert context["screener"]["loser_rank"] == 2
    assert context["runtime_effect"] == "webull_screener_news_attention_context_no_trade_authority"
    assert any("Webull context caution" in item for item in entry["key_risks"])
    assert "webull_market:webull_news:negative" in entry["performance_evidence"]
    assert "no_standalone_trade_authority" in context["authority"]


def main():
    import tempfile

    test_webull_market_evidence_normalizes_screener_news_and_attention()
    print("[OK] test_webull_market_evidence_normalizes_screener_news_and_attention")
    with tempfile.TemporaryDirectory() as tmp:
        test_load_webull_market_evidence_handles_missing_file(Path(tmp))
        print("[OK] test_load_webull_market_evidence_handles_missing_file")
    with tempfile.TemporaryDirectory() as tmp:
        test_apply_webull_market_context_adds_learning_tags_without_authority(Path(tmp))
        print("[OK] test_apply_webull_market_context_adds_learning_tags_without_authority")
    print("\nAll 3 Webull market evidence tests passed.")


if __name__ == "__main__":
    main()
