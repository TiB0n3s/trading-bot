#!/usr/bin/env python3
"""Tests for financial sentiment fallback scoring."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.financial_sentiment_service import score_financial_text


def test_score_financial_text_detects_positive_and_negative_language():
    positive = score_financial_text("record demand and strong growth with margin expansion")
    negative = score_financial_text("lowered guidance, margin pressure, delayed supply constraint")

    assert positive["label"] == "positive"
    assert negative["label"] == "negative"
    assert positive["runtime_effect"] == "research_signal_only_no_trade_authority"


def main():
    test_score_financial_text_detects_positive_and_negative_language()
    print("[OK] test_score_financial_text_detects_positive_and_negative_language")
    print("\nAll 1 financial sentiment service tests passed.")


if __name__ == "__main__":
    main()
