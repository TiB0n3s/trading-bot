"""Operator report for cross-asset lead-lag mapping."""

from __future__ import annotations

from services.cross_asset_lead_lag_service import build_cross_asset_lead_map


def run_cross_asset_lead_lag_map_report(*, limit: int = 20) -> bool:
    payload = build_cross_asset_lead_map().to_dict()
    summary = payload["summary"]

    print()
    print("=" * 72)
    print("  Cross-Asset Lead-Lag Map")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"symbol_count            : {payload['symbol_count']}")
    print(f"default_leads           : {', '.join(payload['default_leads'])}")
    print(f"unique_leads            : {len(summary['unique_leads'])}")
    print(f"transformer_authority   : {summary['transformer_authority']}")
    print(f"intended_use            : {summary['intended_use']}")

    print()
    print("Top lead usage")
    for lead, count in sorted(
        summary["lead_usage"].items(),
        key=lambda item: (-int(item[1]), item[0]),
    )[:10]:
        print(f"  {lead:<8} symbols={count}")

    print()
    print("Symbol mappings")
    for row in payload["rows"][: max(1, int(limit or 1))]:
        print(
            f"  {row['symbol']:<6} clusters={','.join(row['clusters']) or '-':<34} "
            f"leads={','.join(row['lead_tickers'])}"
        )

    if summary["missing_cluster_symbols"]:
        print()
        print("Missing cluster symbols")
        print("  " + ", ".join(summary["missing_cluster_symbols"]))

    print()
    print("[OK] cross-asset lead-lag map generated")
    return True
