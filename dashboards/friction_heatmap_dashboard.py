#!/usr/bin/env python3
"""Streamlit friction heatmap dashboard.

Run:
  streamlit run dashboards/friction_heatmap_dashboard.py -- --date YYYY-MM-DD
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.ops_check_repo import OpsCheckRepository  # noqa: E402
from services.friction_heatmap_service import build_friction_heatmap_payload  # noqa: E402


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--date", default="")
    parser.add_argument("--db-path", default=str(ROOT / "trades.db"))
    args, _unknown = parser.parse_known_args()
    return args


def main() -> None:
    import streamlit as st

    args = _args()
    st.set_page_config(page_title="Friction Heatmap", layout="wide")
    st.title("Friction Heatmap")
    target_date = st.text_input("Market date", value=args.date)
    db_path = Path(args.db_path)

    if not target_date:
        st.info("Provide a market date with --date or enter one above.")
        return
    if not db_path.exists():
        st.error(f"trades.db not found: {db_path}")
        return

    repo = OpsCheckRepository(db_path)
    rows = [dict(row) for row in repo.pattern_learning_bar_pattern_rows(target_date)]
    payload = build_friction_heatmap_payload(rows).to_dict()
    summary = payload["summary"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", payload["rows"])
    c2.metric("Rows With Outcome", payload["rows_with_outcome"])
    c3.metric("Symmetric Toxic Stop-Outs", summary["symmetric_toxic_stopouts"])
    c4.metric("Asym Avoided", summary["asymmetric_toxic_stopouts_avoided"])

    st.caption(payload["runtime_effect"])
    heatmap = payload["heatmap"]
    st.dataframe(
        heatmap,
        use_container_width=True,
        hide_index=True,
        column_config={
            "profile": "Profile",
            "liquidity_stress_bucket": "LSI Bucket",
            "rows": "Rows",
            "trades_taken": "Taken",
            "stopouts": "Stop-Outs",
            "toxic_stopouts": "Toxic Stop-Outs",
            "avg_lsi_score": st.column_config.NumberColumn("Avg LSI", format="%.2f"),
            "avg_forward_return_pct": st.column_config.NumberColumn("Avg Return", format="%.4f"),
            "stopout_rate": st.column_config.ProgressColumn(
                "Stop-Out Rate",
                min_value=0,
                max_value=1,
                format="%.2f",
            ),
        },
    )


if __name__ == "__main__":
    main()
