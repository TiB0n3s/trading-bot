from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import strategy_memory


def _reset_memory(path):
    strategy_memory.MEMORY_FILE = path
    strategy_memory._strategy_memory = {}
    strategy_memory._strategy_memory_mtime = 0.0


def test_memory_for_signal_uses_context_matches(tmp_path):
    path = tmp_path / "strategy_memory.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-31T00:00:00Z",
                "lookback_days": 30,
                "symbols": {
                    "AAPL": {
                        "recommendation": "observe",
                        "min_setup_score": 40,
                        "reason": "symbol observe",
                    }
                },
                "setup_label_context": {
                    "above_vwap_neutral_continuation": {
                        "recommendation": "caution",
                        "min_setup_score": 70,
                        "reason": "weak setup context",
                    }
                },
                "buy_opportunity_context": {
                    "small_buy_candidate": {
                        "recommendation": "avoid",
                        "min_setup_score": 80,
                        "reason": "weak opportunity context",
                    }
                },
            }
        )
    )
    _reset_memory(path)

    result = strategy_memory.memory_for_signal(
        "aapl",
        {
            "setup_quality": {"label": "above_vwap_neutral_continuation"},
            "buy_opportunity": {
                "buy_opportunity_recommendation": "small_buy_candidate"
            },
        },
    )

    assert result["available"] is True
    assert result["recommendation"] == "avoid"
    assert result["min_setup_score"] == 80
    assert [m["label"] for m in result["context_matches"]] == [
        "symbol",
        "setup_label",
        "buy_opportunity",
    ]


def test_memory_for_signal_preserves_symbol_memory_without_context(tmp_path):
    path = tmp_path / "strategy_memory.json"
    path.write_text(
        json.dumps(
            {
                "symbols": {
                    "MSFT": {
                        "recommendation": "caution",
                        "min_setup_score": 65,
                        "reason": "symbol caution",
                    }
                }
            }
        )
    )
    _reset_memory(path)

    result = strategy_memory.memory_for_signal("msft")

    assert result["recommendation"] == "caution"
    assert result["min_setup_score"] == 65
    assert [m["label"] for m in result["context_matches"]] == ["symbol"]


def test_strategy_memory_context_normalizes_malformed_context():
    result = strategy_memory.normalize_strategy_memory_context("not-a-dict")
    assert result.setup_label == "unknown"
    assert result.prediction_decision == "unknown"
    assert result.buy_opportunity_recommendation == "unknown"
    assert result.session_trend_label == "unknown"

    result = strategy_memory.normalize_strategy_memory_context(
        {
            "setup_quality": {"label": ""},
            "prediction_gate": {"prediction_decision": None},
            "buy_opportunity": {"recommendation": "  watch  "},
            "session_momentum": {"trend_label": "strong_uptrend"},
        }
    )
    assert result.setup_label == "unknown"
    assert result.prediction_decision == "unknown"
    assert result.buy_opportunity_recommendation == "watch"
    assert result.session_trend_label == "strong_uptrend"


def main():
    import tempfile
    from pathlib import Path

    tests = [
        test_memory_for_signal_uses_context_matches,
        test_memory_for_signal_preserves_symbol_memory_without_context,
        test_strategy_memory_context_normalizes_malformed_context,
    ]
    for test in tests:
        if test.__name__.endswith("malformed_context"):
            test()
        else:
            with tempfile.TemporaryDirectory() as tmp:
                test(Path(tmp))
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} strategy memory tests passed.")


if __name__ == "__main__":
    main()
