"""Tests for label-tier authority enforcement (#10) and authority-config
ML-promotion capping (#18)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.learning.labels import (
    DEFAULT_HISTORICAL_BAR_TRAINING_LABELS,
    labels_support_meta_label_authority,
    tier_for_label,
)
from trading_bot.runtime.authority import load_authority_layers_from_config


# --- #10: label-tier authority -----------------------------------------------

def test_tier4_labels_grant_no_meta_label_authority():
    # The historical-bar ensemble's actual training labels are all Tier 4.
    assert labels_support_meta_label_authority(DEFAULT_HISTORICAL_BAR_TRAINING_LABELS) is False
    assert labels_support_meta_label_authority(["triple_barrier_label"]) is False
    assert labels_support_meta_label_authority(["trend_scan_label"]) is False


def test_tier3_labels_grant_meta_label_authority():
    assert labels_support_meta_label_authority(["return_15m"]) is True
    assert labels_support_meta_label_authority(["return_15m", "return_60m"]) is True


def test_weakest_label_governs():
    # A single Tier-4 label among Tier-3 labels restricts to observe-only.
    assert labels_support_meta_label_authority(["return_15m", "triple_barrier_label"]) is False


def test_empty_or_unknown_labels_grant_no_authority():
    assert labels_support_meta_label_authority([]) is False
    assert labels_support_meta_label_authority(["nonexistent_label"]) is False
    assert tier_for_label("nonexistent_label") == 99


# --- #18: authority-matrix config ML-promotion cap ---------------------------

def _write_config(tmp_path, payload) -> str:
    path = tmp_path / "authority.json"
    path.write_text(json.dumps(payload))
    return str(path)


def test_config_cannot_raise_ml_layer_to_live_block(tmp_path):
    path = _write_config(
        tmp_path,
        {"layers": {"historical_bar_meta_label": {"can_approve": "live_block"}}},
    )
    layers = load_authority_layers_from_config(path)
    # Capped back to paper_block; the config cannot grant cash-live ML authority.
    assert layers["historical_bar_meta_label"].can_approve == "paper_block"


def test_config_with_explicit_promotion_flag_allows_live(tmp_path):
    path = _write_config(
        tmp_path,
        {
            "allow_ml_live_promotion": True,
            "layers": {"layered_model_authority": {"can_approve": "live_block"}},
        },
    )
    layers = load_authority_layers_from_config(path)
    assert layers["layered_model_authority"].can_approve == "live_block"


def test_protective_permissions_are_not_capped(tmp_path):
    # block / size_down only ever stop or shrink a trade, so they are safe at
    # any level even for ML layers (no flag needed).
    path = _write_config(
        tmp_path,
        {"layers": {"transformer": {"can_size_down": "live_block"}}},
    )
    layers = load_authority_layers_from_config(path)
    assert layers["transformer"].can_size_down == "live_block"


def test_config_cap_does_not_touch_control_layers(tmp_path):
    # Non-ML control layers keep their legitimate live_block.
    path = _write_config(
        tmp_path,
        {"layers": {"claude": {"can_block": "live_block"}}},
    )
    layers = load_authority_layers_from_config(path)
    assert layers["claude"].can_block == "live_block"
