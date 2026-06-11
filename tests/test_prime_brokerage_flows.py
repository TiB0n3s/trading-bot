import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from pre_market_research_data import apply_prime_brokerage_context, update_performance_context
from symbols_config import SYMBOL_CONFIG

from market_intelligence.prime_brokerage_flows import (
    crowding_score,
    is_degrossing,
    load_prime_brokerage_state,
    net_flow_momentum,
    normalize_prime_brokerage_state,
    pb_flow_regime,
    prime_brokerage_context_for_symbol,
    symbol_to_pb_sector,
)


def test_prime_brokerage_derived_metrics():
    assert net_flow_momentum(125.0, 25.0) == 100.0
    assert crowding_score(20_000_000, 100_000_000) == 20.0
    assert is_degrossing(-4.0, -3.0, None) is True
    assert is_degrossing(2.0, -3.0, -6.0) is True
    assert pb_flow_regime(8.0, False, False) == "institutional_distribution_extreme"
    assert pb_flow_regime(50.0, False, True) == "crowded_short_squeeze_watch"


def test_symbol_to_prime_brokerage_sector_uses_existing_clusters():
    assert symbol_to_pb_sector("NVDA", SYMBOL_CONFIG) == "information_technology"
    assert symbol_to_pb_sector("NOC", SYMBOL_CONFIG) == "industrials"
    assert symbol_to_pb_sector("FCX", SYMBOL_CONFIG) == "materials"
    assert symbol_to_pb_sector("JPM", SYMBOL_CONFIG) == "financials"


def test_sector_flow_context_falls_back_to_symbol_sector():
    state = normalize_prime_brokerage_state(
        {
            "sectors": {
                "technology": {
                    "published_at": "2026-06-10T06:00:00-04:00",
                    "net_flow_percentile_1y": 7,
                    "long_inflows_5d": 10,
                    "short_outflows_5d": 60,
                }
            }
        },
        SYMBOL_CONFIG,
    )

    context = prime_brokerage_context_for_symbol("NVDA", state)

    assert context["mapped_pb_sector"] == "information_technology"
    assert context["pb_flow_regime"] == "institutional_distribution_extreme"
    assert context["pb_size_modifier"] == 0.5


def test_symbol_flow_record_overrides_sector_fallback():
    state = normalize_prime_brokerage_state(
        {
            "sectors": {
                "technology": {
                    "published_at": "2026-06-10T06:00:00-04:00",
                    "net_flow_percentile_1y": 7,
                }
            },
            "symbols": {
                "NVDA": {
                    "published_at": "2026-06-10T06:00:00-04:00",
                    "net_flow_percentile_1y": 93,
                }
            },
        },
        SYMBOL_CONFIG,
    )

    context = prime_brokerage_context_for_symbol("NVDA", state)

    assert context["scope"] == "symbol"
    assert context["pb_flow_regime"] == "institutional_accumulation_extreme"
    assert context["pb_size_modifier"] == 1.0


def test_future_published_prime_brokerage_record_does_not_attach():
    state = normalize_prime_brokerage_state(
        {
            "sectors": {
                "technology": {
                    "published_at": "2999-01-01T06:00:00-04:00",
                    "net_flow_percentile_1y": 7,
                }
            }
        },
        SYMBOL_CONFIG,
    )

    assert state["available"] is False
    assert prime_brokerage_context_for_symbol("NVDA", state) is None


def test_load_prime_brokerage_state_handles_missing_file(tmp_path):
    state = load_prime_brokerage_state(tmp_path / "missing.json", SYMBOL_CONFIG)

    assert state["available"] is False
    assert state["sectors"] == {}


def test_apply_prime_brokerage_context_marks_distribution_risk(tmp_path):
    payload = {
        "sectors": {
            "technology": {
                "published_at": "2026-06-10T06:00:00-04:00",
                "net_flow_percentile_1y": 8,
                "gross_leverage_change_5d": -1,
            }
        }
    }
    path = tmp_path / "pb.json"
    path.write_text(json.dumps(payload))
    state = load_prime_brokerage_state(path, SYMBOL_CONFIG)
    entry = {
        "bias": "buy",
        "confidence": "medium",
        "entry_quality": "good_on_pullbacks",
        "risk_level": "medium",
        "key_risks": [],
        "key_catalysts": [],
        "performance_evidence": [],
    }

    apply_prime_brokerage_context("NVDA", entry, state)
    update_performance_context(entry)

    assert (
        entry["prime_brokerage_context"]["pb_flow_regime"] == "institutional_distribution_extreme"
    )
    assert any("external positioning size_modifier=0.5" in risk for risk in entry["key_risks"])
    assert "pb_distribution_extreme" in entry["performance_evidence"]


if __name__ == "__main__":

    def _missing_file_test():
        with tempfile.TemporaryDirectory() as tmp:
            test_load_prime_brokerage_state_handles_missing_file(Path(tmp))

    def _apply_context_test():
        with tempfile.TemporaryDirectory() as tmp:
            test_apply_prime_brokerage_context_marks_distribution_risk(Path(tmp))

    tests = [
        test_prime_brokerage_derived_metrics,
        test_symbol_to_prime_brokerage_sector_uses_existing_clusters,
        test_sector_flow_context_falls_back_to_symbol_sector,
        test_symbol_flow_record_overrides_sector_fallback,
        test_future_published_prime_brokerage_record_does_not_attach,
        _missing_file_test,
        _apply_context_test,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} prime brokerage flow tests passed.")
