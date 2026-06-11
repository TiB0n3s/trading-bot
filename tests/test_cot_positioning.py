import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from pre_market_research_data import apply_cot_positioning_context, update_performance_context
from symbols_config import SYMBOL_CONFIG

from market_intelligence.cot_positioning import (
    cot_context_for_symbol,
    cot_index,
    cot_net_position,
    load_cot_state,
    normalize_cot_state,
    positioning_regime,
    published_at_is_effective,
    smart_retail_divergence,
    symbol_to_cot_market,
)


def test_cot_net_position_and_index_calculation():
    assert cot_net_position(120_000, 80_000) == 40_000
    assert cot_index(40_000, [-20_000, 0, 40_000]) == 100.0
    assert cot_index(-20_000, [-20_000, 0, 40_000]) == 0.0
    assert cot_index(10, [10, 10]) == 50.0


def test_cot_positioning_regime_extremes():
    assert positioning_regime(96) == "leveraged_long_extreme"
    assert positioning_regime(4) == "leveraged_short_extreme"
    assert positioning_regime(50) == "balanced"
    assert smart_retail_divergence(15_000, -5_000) == 20_000


def test_symbol_mapping_uses_symbol_clusters():
    assert symbol_to_cot_market("NVDA", SYMBOL_CONFIG) == "NASDAQ_100"
    assert symbol_to_cot_market("MRVL", SYMBOL_CONFIG) == "NASDAQ_100"
    assert symbol_to_cot_market("NOC", SYMBOL_CONFIG) == "S_AND_P_500"
    assert symbol_to_cot_market("GLD", SYMBOL_CONFIG) == "GOLD"


def test_normalized_state_maps_cot_markets_to_symbols():
    raw = {
        "markets": {
            "NASDAQ_100": {
                "as_of_date": "2026-06-09",
                "published_at": "2026-06-05T15:30:00-04:00",
                "leveraged_funds_long": 180_000,
                "leveraged_funds_short": 80_000,
                "leveraged_funds_net_history": [-50_000, 0, 100_000],
                "leveraged_funds_net_change": 25_000,
                "nonreportable_net_change": -10_000,
                "open_interest_change": 12_000,
            }
        }
    }

    state = normalize_cot_state(raw, SYMBOL_CONFIG)
    nvda_context = cot_context_for_symbol("NVDA", state)

    assert nvda_context["mapped_cot_market"] == "NASDAQ_100"
    assert nvda_context["leveraged_funds_net"] == 100_000
    assert nvda_context["leveraged_funds_cot_index_52w"] == 100.0
    assert nvda_context["positioning_regime"] == "leveraged_long_extreme"
    assert nvda_context["smart_retail_divergence"] == 35_000
    assert nvda_context["cot_size_modifier"] == 0.5


def test_load_cot_state_handles_missing_file(tmp_path):
    state = load_cot_state(tmp_path / "missing.json", SYMBOL_CONFIG)

    assert state["available"] is False
    assert state["markets"] == {}


def test_apply_cot_positioning_context_marks_extreme_macro_risk(tmp_path):
    payload = {
        "markets": {
            "NASDAQ_100": {
                "published_at": "2026-06-05T15:30:00-04:00",
                "leveraged_funds_net": 100_000,
                "leveraged_funds_cot_index_52w": 97,
                "leveraged_funds_net_change": 20_000,
                "nonreportable_net_change": -5_000,
                "open_interest_change": 10_000,
            }
        }
    }
    path = tmp_path / "cot.json"
    path.write_text(json.dumps(payload))
    state = load_cot_state(path, SYMBOL_CONFIG)

    entry = {
        "bias": "buy",
        "confidence": "medium",
        "entry_quality": "good_on_pullbacks",
        "risk_level": "medium",
        "key_risks": [],
        "key_catalysts": [],
        "performance_evidence": [],
    }
    apply_cot_positioning_context("NVDA", entry, state)
    update_performance_context(entry)

    assert entry["cot_positioning_context"]["positioning_regime"] == "leveraged_long_extreme"
    assert any("macro size-down context" in risk for risk in entry["key_risks"])
    assert any("cot_positioning_extreme" in item for item in entry["performance_evidence"])


def test_future_published_cot_record_does_not_attach_to_symbols():
    state = normalize_cot_state(
        {
            "markets": {
                "NASDAQ_100": {
                    "published_at": "2999-01-01T15:30:00-04:00",
                    "leveraged_funds_net": 100_000,
                    "leveraged_funds_cot_index_52w": 97,
                }
            }
        },
        SYMBOL_CONFIG,
    )

    assert published_at_is_effective("2999-01-01T15:30:00-04:00") is False
    assert cot_context_for_symbol("NVDA", state) is None
    assert state["available"] is False


if __name__ == "__main__":

    def _missing_file_test():
        with tempfile.TemporaryDirectory() as tmp:
            test_load_cot_state_handles_missing_file(Path(tmp))

    def _apply_context_test():
        with tempfile.TemporaryDirectory() as tmp:
            test_apply_cot_positioning_context_marks_extreme_macro_risk(Path(tmp))

    tests = [
        test_cot_net_position_and_index_calculation,
        test_cot_positioning_regime_extremes,
        test_symbol_mapping_uses_symbol_clusters,
        test_normalized_state_maps_cot_markets_to_symbols,
        test_future_published_cot_record_does_not_attach_to_symbols,
        _missing_file_test,
        _apply_context_test,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} COT positioning tests passed.")
