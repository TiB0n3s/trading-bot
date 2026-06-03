from __future__ import annotations

import json
import logging
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import strategy_memory


def _reset_memory(path):
    strategy_memory.MEMORY_FILE = path
    strategy_memory._strategy_memory = {}
    strategy_memory._strategy_memory_mtime = 0.0


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@contextmanager
def _capture_strategy_memory_warnings():
    handler = _ListHandler()
    old_level = strategy_memory.logger.level
    old_propagate = strategy_memory.logger.propagate
    strategy_memory.logger.addHandler(handler)
    strategy_memory.logger.setLevel(logging.WARNING)
    strategy_memory.logger.propagate = False
    try:
        yield handler
    finally:
        strategy_memory.logger.removeHandler(handler)
        strategy_memory.logger.setLevel(old_level)
        strategy_memory.logger.propagate = old_propagate


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


def test_bar_pattern_evidence_does_not_change_live_recommendation(tmp_path):
    path = tmp_path / "strategy_memory.json"
    path.write_text(
        json.dumps(
            {
                "symbols": {
                    "AAPL": {
                        "recommendation": "neutral",
                        "min_setup_score": 55,
                        "reason": "normal symbol memory",
                    }
                },
                "bar_pattern_runtime_effect": "observe_only_pattern_learning_no_live_authority",
                "symbol_bar_pattern_label_context": {
                    "AAPL|efi_pvt_breakout_confirmation": {
                        "rows": 120,
                        "recommendation": "observe",
                        "authority_ready": False,
                        "runtime_effect": "observe_only_pattern_learning_no_live_authority",
                        "evidence_label": "constructive_buy_pattern",
                    }
                },
                "symbol_bar_pattern_opportunity_context": {
                    "AAPL|long_candidate|best_buy_window": {
                        "rows": 30,
                        "recommendation": "observe",
                        "authority_ready": False,
                        "runtime_effect": "observe_only_pattern_learning_no_live_authority",
                        "evidence_label": "constructive_buy_pattern",
                    }
                },
            }
        )
    )
    _reset_memory(path)

    result = strategy_memory.memory_for_signal("aapl")

    assert result["recommendation"] == "neutral"
    assert result["min_setup_score"] == 55
    assert [m["label"] for m in result["context_matches"]] == ["symbol"]
    assert result["bar_pattern_evidence"]["available"] is True
    assert result["bar_pattern_evidence"]["authority_ready"] is False
    assert (
        result["bar_pattern_evidence"]["runtime_effect"]
        == "observe_only_pattern_learning_no_live_authority"
    )
    assert (
        "efi_pvt_breakout_confirmation"
        in result["bar_pattern_evidence"]["symbol_bar_pattern_label_context"]
    )
    assert (
        "long_candidate|best_buy_window"
        in result["bar_pattern_evidence"]["symbol_bar_pattern_opportunity_context"]
    )


def test_strategy_memory_context_normalizes_malformed_context():
    with _capture_strategy_memory_warnings() as warnings:
        result = strategy_memory.normalize_strategy_memory_context("not-a-dict")
    assert result.setup_label == "unknown"
    assert result.prediction_decision == "unknown"
    assert result.buy_opportunity_recommendation == "unknown"
    assert result.session_trend_label == "unknown"
    assert any("malformed root context" in m for m in warnings.messages)

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


def test_strategy_memory_context_accepts_current_aliases():
    result = strategy_memory.normalize_strategy_memory_context(
        {
            "setup_quality_outcome": {"label": "confirmed_near_vwap_recovery"},
            "prediction_state": {"deterministic_decision": "pass"},
            "opportunity_observation": {"recommendation": "small_buy_candidate"},
            "session_observation": {"label": "developing_uptrend"},
        }
    )

    assert result.setup_label == "confirmed_near_vwap_recovery"
    assert result.prediction_decision == "pass"
    assert result.buy_opportunity_recommendation == "small_buy_candidate"
    assert result.session_trend_label == "developing_uptrend"


def test_strategy_memory_context_logs_malformed_nested_and_unknown_enums():
    with _capture_strategy_memory_warnings() as warnings:
        result = strategy_memory.normalize_strategy_memory_context(
            {
                "setup_quality": "renamed-field",
                "prediction_gate": {"prediction_decision": "renamed_pass"},
                "buy_opportunity": ["not", "a", "dict"],
                "session_momentum": {"trend_label": "rocket_mode"},
            }
        )

    assert result.setup_label == "unknown"
    assert result.prediction_decision == "unknown"
    assert result.buy_opportunity_recommendation == "unknown"
    assert result.session_trend_label == "unknown"
    assert any("malformed setup_quality container" in m for m in warnings.messages)
    assert any("unsupported prediction_decision='renamed_pass'" in m for m in warnings.messages)
    assert any("malformed buy_opportunity container" in m for m in warnings.messages)
    assert any("unsupported session_trend_label='rocket_mode'" in m for m in warnings.messages)


def test_contextual_memory_for_signal_normalizes_malformed_direct_context():
    mem = {
        "setup_label_context": {
            "unknown": {
                "recommendation": "observe",
                "min_setup_score": 50,
                "reason": "unknown fallback",
            }
        }
    }

    with _capture_strategy_memory_warnings() as warnings:
        result = strategy_memory.contextual_memory_for_signal(
            "AAPL",
            "not-a-dict",
            memory_override=mem,
        )

    assert result["available"] is True
    assert [m["key"] for m in result["matches"]] == ["unknown"]
    assert any("malformed intelligence context" in m for m in warnings.messages)


def main():
    import tempfile
    from pathlib import Path

    tests = [
        test_memory_for_signal_uses_context_matches,
        test_memory_for_signal_preserves_symbol_memory_without_context,
        test_bar_pattern_evidence_does_not_change_live_recommendation,
        test_strategy_memory_context_normalizes_malformed_context,
        test_strategy_memory_context_accepts_current_aliases,
        test_strategy_memory_context_logs_malformed_nested_and_unknown_enums,
        test_contextual_memory_for_signal_normalizes_malformed_direct_context,
    ]
    for test in tests:
        if (
            test.__name__.endswith("malformed_context")
            or test.__name__.endswith("current_aliases")
            or test.__name__.endswith("unknown_enums")
            or test.__name__.endswith("direct_context")
        ):
            test()
        else:
            with tempfile.TemporaryDirectory() as tmp:
                test(Path(tmp))
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} strategy memory tests passed.")


if __name__ == "__main__":
    main()
