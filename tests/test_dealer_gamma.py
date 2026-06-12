import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from pre_market_research_data import apply_dealer_gamma_context, update_performance_context

from market_intelligence.dealer_gamma import (
    dealer_gamma_context_for_symbol,
    distance_pct,
    gamma_size_modifier,
    gex_regime,
    load_dealer_gamma_state,
    nearest_gamma_level,
    normalize_dealer_gamma_state,
    option_gex,
    total_gex,
)


def test_option_gex_uses_call_positive_put_negative_signs():
    assert option_gex(100, 0.02, 50, "call") == 50.0
    assert option_gex(100, 0.02, 50, "put") == -50.0
    assert (
        total_gex(
            [
                {"open_interest": 100, "gamma": 0.02, "option_type": "call"},
                {"open_interest": 50, "gamma": 0.02, "option_type": "put"},
            ],
            50,
        )
        == 25.0
    )


def test_gex_regime_and_size_modifier():
    assert gex_regime(100) == "positive_gamma_vol_dampening"
    assert gex_regime(-100) == "negative_gamma_vol_accelerating"
    assert gex_regime(0) == "gamma_neutral"
    assert gamma_size_modifier("positive_gamma_vol_dampening", 0.2) == 0.75
    assert gamma_size_modifier("positive_gamma_vol_dampening", 2.0) == 0.85
    assert gamma_size_modifier("negative_gamma_vol_accelerating", 2.0) == 1.0


def test_nearest_gamma_levels_and_distance():
    levels = [{"strike": 95, "net_gex": 10}, {"strike": 105, "net_gex": 20}]

    assert nearest_gamma_level(100, levels, "below")["strike"] == 95
    assert nearest_gamma_level(100, levels, "above")["strike"] == 105
    assert distance_pct(100, 99.5) == 0.5


def test_normalized_dealer_gamma_state_attaches_symbol_context():
    state = normalize_dealer_gamma_state(
        {
            "symbols": {
                "NVDA": {
                    "published_at": "2026-06-10T06:00:00-04:00",
                    "spot_price": 100,
                    "gamma_flip_zone": 99.8,
                    "options": [
                        {"open_interest": 100, "gamma": 0.02, "option_type": "put"},
                        {"open_interest": 20, "gamma": 0.02, "option_type": "call"},
                    ],
                    "absolute_gamma_peak_levels": [
                        {"strike": 95, "net_gex": 5000, "open_interest": 1000},
                        {"strike": 105, "net_gex": 8000, "open_interest": 1200},
                    ],
                }
            }
        }
    )

    context = dealer_gamma_context_for_symbol("NVDA", state)

    assert context["gex_regime"] == "negative_gamma_vol_accelerating"
    assert context["distance_to_gamma_flip_pct"] == 0.2
    assert context["gamma_size_modifier"] == 0.75
    assert context["nearest_positive_gamma_floor"]["strike"] == 95
    assert context["nearest_positive_gamma_ceiling"]["strike"] == 105


def test_future_published_dealer_gamma_record_does_not_attach():
    state = normalize_dealer_gamma_state(
        {
            "symbols": {
                "NVDA": {
                    "published_at": "2999-01-01T06:00:00-04:00",
                    "spot_price": 100,
                    "total_net_gex": -100,
                }
            }
        }
    )

    assert state["available"] is False
    assert dealer_gamma_context_for_symbol("NVDA", state) is None


def test_load_dealer_gamma_state_handles_missing_file(tmp_path):
    state = load_dealer_gamma_state(tmp_path / "missing.json")

    assert state["available"] is False
    assert state["symbols"] == {}


def test_apply_dealer_gamma_context_marks_positive_gamma_breakout_risk(tmp_path):
    payload = {
        "symbols": {
            "NVDA": {
                "published_at": "2026-06-10T06:00:00-04:00",
                "spot_price": 100,
                "total_net_gex": 1_000_000,
                "gamma_flip_zone": 99.7,
                "absolute_gamma_peak_levels": [{"strike": 95, "net_gex": 5000}],
            }
        }
    }
    path = tmp_path / "gamma.json"
    path.write_text(json.dumps(payload))
    state = load_dealer_gamma_state(path)
    entry = {
        "bias": "buy",
        "confidence": "medium",
        "entry_quality": "good_on_pullbacks",
        "risk_level": "medium",
        "key_risks": [],
        "key_catalysts": [],
        "performance_evidence": [],
    }

    apply_dealer_gamma_context("NVDA", entry, state)
    update_performance_context(entry)

    assert entry["dealer_gamma_context"]["gex_regime"] == "positive_gamma_vol_dampening"
    assert any("positive/vol-dampening" in risk for risk in entry["key_risks"])
    assert "dealer_gamma_positive_vol_dampening" in entry["performance_evidence"]
    assert any("near_gamma_flip" in item for item in entry["performance_evidence"])


if __name__ == "__main__":

    def _missing_file_test():
        with tempfile.TemporaryDirectory() as tmp:
            test_load_dealer_gamma_state_handles_missing_file(Path(tmp))

    def _apply_context_test():
        with tempfile.TemporaryDirectory() as tmp:
            test_apply_dealer_gamma_context_marks_positive_gamma_breakout_risk(Path(tmp))

    tests = [
        test_option_gex_uses_call_positive_put_negative_signs,
        test_gex_regime_and_size_modifier,
        test_nearest_gamma_levels_and_distance,
        test_normalized_dealer_gamma_state_attaches_symbol_context,
        test_future_published_dealer_gamma_record_does_not_attach,
        _missing_file_test,
        _apply_context_test,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} dealer gamma tests passed.")
