"""Portfolio-risk operator report over canonical decision snapshots."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from repositories.ops_check_repo import OpsCheckRepository

PORTFOLIO_RISK_REPORT_VERSION = "portfolio_risk_v1"


def _load_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _path(data: dict[str, Any], *path: str) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def run_portfolio_risk_report(target_date: str, *, base_dir: Path) -> bool:
    print()
    print("=" * 72)
    print(f"  Portfolio Risk Report - {target_date}")
    print("=" * 72)
    print(f"report_version          : {PORTFOLIO_RISK_REPORT_VERSION}")

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    repo = OpsCheckRepository(db_path)
    rows = [dict(row) for row in repo.decision_authority_rows(target_date)]
    buy_rows = [row for row in rows if str(row.get("action") or "").lower() == "buy"]
    if not buy_rows:
        print("[WARN] no BUY decision snapshots found")
        return False

    decision_counts: Counter[str] = Counter()
    theme_counts: Counter[str] = Counter()
    cluster_counts: Counter[str] = Counter()
    overlap_counts: Counter[str] = Counter()
    duplicate_scores: list[float] = []
    var_values: list[float] = []
    beta_values: list[float] = []
    factor_overlap_values: list[float] = []
    concentration_values: list[float] = []
    comovement_values: list[float] = []
    highest: list[dict[str, Any]] = []

    for row in buy_rows:
        canonical = _load_json(row.get("canonical_intelligence_json"))
        regime = canonical.get("regime_state") or {}
        portfolio = _path(canonical, "advisory_authority_state", "portfolio_decision") or {}
        if not isinstance(portfolio, dict):
            portfolio = {}
        decision = portfolio.get("decision") or regime.get("portfolio_decision") or "unknown"
        decision_counts[str(decision)] += 1
        theme = portfolio.get("crowded_theme") or regime.get("crowded_theme")
        if theme:
            theme_counts[str(theme)] += 1
        cluster = regime.get("crowded_theme") or portfolio.get("max_cluster_name")
        if cluster:
            cluster_counts[str(cluster)] += 1
        for symbol in portfolio.get("overlap_symbols") or regime.get("overlap_symbols") or []:
            overlap_counts[str(symbol)] += 1

        metrics = {
            "duplicate_risk_score": (
                portfolio.get("duplicate_risk_score")
                if portfolio.get("duplicate_risk_score") is not None
                else regime.get("portfolio_duplicate_risk_score")
            ),
            "incremental_var_pct": portfolio.get("incremental_var_pct")
            or regime.get("incremental_var_pct"),
            "beta_contribution_delta": portfolio.get("beta_contribution_delta")
            or regime.get("beta_contribution_delta"),
            "factor_overlap_score": portfolio.get("factor_overlap_score"),
            "sector_concentration_delta_pct": portfolio.get("sector_concentration_delta_pct"),
            "downside_comovement_score": portfolio.get("downside_comovement_score"),
        }
        for key, target in (
            ("duplicate_risk_score", duplicate_scores),
            ("incremental_var_pct", var_values),
            ("beta_contribution_delta", beta_values),
            ("factor_overlap_score", factor_overlap_values),
            ("sector_concentration_delta_pct", concentration_values),
            ("downside_comovement_score", comovement_values),
        ):
            value = _float(metrics.get(key))
            if value is not None:
                target.append(value)
        score = _float(metrics.get("duplicate_risk_score")) or 0.0
        highest.append(
            {
                "time": row.get("decision_time"),
                "symbol": row.get("symbol"),
                "approved": bool(row.get("approved")),
                "decision": decision,
                "duplicate_risk_score": score,
                "incremental_var_pct": _float(metrics.get("incremental_var_pct")),
                "beta_contribution_delta": _float(metrics.get("beta_contribution_delta")),
                "theme": theme,
                "overlaps": ",".join((portfolio.get("overlap_symbols") or [])[:6]),
            }
        )

    highest.sort(key=lambda item: item["duplicate_risk_score"], reverse=True)

    print(f"buy_rows                         : {len(buy_rows)}")
    print(f"avg_duplicate_risk_score         : {_fmt(_avg(duplicate_scores))}")
    print(f"avg_incremental_var_pct          : {_fmt(_avg(var_values))}")
    print(f"avg_beta_contribution_delta      : {_fmt(_avg(beta_values))}")
    print(f"avg_factor_overlap_score         : {_fmt(_avg(factor_overlap_values))}")
    print(f"avg_sector_concentration_delta   : {_fmt(_avg(concentration_values))}")
    print(f"avg_downside_comovement_score    : {_fmt(_avg(comovement_values))}")

    print()
    print("Portfolio decisions")
    for decision, count in sorted(decision_counts.items()):
        print(f"  {decision:<20} {count:>5}")

    print()
    print("Crowded themes / clusters")
    for theme, count in (theme_counts or cluster_counts).most_common(12):
        print(f"  {theme:<28} {count:>5}")

    print()
    print("Repeated overlap symbols")
    for symbol, count in overlap_counts.most_common(12):
        print(f"  {symbol:<8} {count:>5}")

    print()
    print("Highest marginal risk decisions")
    print(
        f"  {'time':<19} {'sym':<6} {'approved':<8} {'decision':<10} {'dup':>7} {'var':>7} {'beta':>7} theme/overlap"
    )
    for item in highest[:15]:
        print(
            f"  {str(item['time'])[:19]:<19} {str(item['symbol'] or '-'):<6} "
            f"{str(item['approved']):<8} {str(item['decision'] or '-'):<10} "
            f"{_fmt(item['duplicate_risk_score']):>7} "
            f"{_fmt(item['incremental_var_pct']):>7} "
            f"{_fmt(item['beta_contribution_delta']):>7} "
            f"{item.get('theme') or item.get('overlaps') or '-'}"
        )

    print()
    print("[OK] portfolio risk report completed")
    return True
