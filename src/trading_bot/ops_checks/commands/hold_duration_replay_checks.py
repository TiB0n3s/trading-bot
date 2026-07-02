"""Operator report for read-only hold-duration replay."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from trading_bot.persistence.repositories.hold_duration_replay_repo import (
    HoldDurationReplayRepository,
)
from trading_bot.services.hold_duration_replay_service import (
    DEFAULT_REALISTIC_REPLAY_COST_BPS,
    DEFAULT_REPLAY_COST_SOURCE,
    HoldDurationReplayConfig,
    HoldDurationReplayService,
)


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):+.4f}%"


def _fmt_rate(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):.2f}%"


def _fmt_num(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):.1f}"


def _fmt_p(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):.6f}"


def _print_summary_table(title: str, rows: list[dict[str, Any]]) -> None:
    print()
    print(title)
    print(
        "  horizon/policy                       rows coverage  avg_net   med_net "
        "  pos%  ev_hit%   neg%  avg_mfe  avg_mae  hold_min"
    )
    for row in rows:
        print(
            f"  {row['label']:<34} "
            f"{row['rows']:>5} "
            f"{_fmt_rate(row.get('coverage_pct')):>8} "
            f"{_fmt_pct(row.get('avg_net_return_pct')):>8} "
            f"{_fmt_pct(row.get('median_net_return_pct')):>8} "
            f"{_fmt_rate(row.get('positive_rate_pct')):>6} "
            f"{_fmt_rate(row.get('ev_hit_rate_pct')):>8} "
            f"{_fmt_rate(row.get('negative_rate_pct')):>7} "
            f"{_fmt_pct(row.get('avg_mfe_pct')):>8} "
            f"{_fmt_pct(row.get('avg_mae_pct')):>8} "
            f"{_fmt_num(row.get('avg_hold_minutes')):>8}"
        )


def _print_compact_group(title: str, groups: dict[str, list[dict[str, Any]]]) -> None:
    print()
    print(title)
    print("  group                       horizon rows  avg_net   med_net coverage")
    for group, summaries in groups.items():
        for row in summaries:
            if row["rows"] == 0:
                continue
            print(
                f"  {group:<27} {row['label']:<8} "
                f"{row['rows']:>4} "
                f"{_fmt_pct(row.get('avg_net_return_pct')):>8} "
                f"{_fmt_pct(row.get('median_net_return_pct')):>8} "
                f"{_fmt_rate(row.get('coverage_pct')):>8}"
            )


def _primary_horizon_config(
    authority_horizons: tuple[str, ...] | None,
    primary_horizon_only: bool,
) -> dict[str, Any]:
    if not primary_horizon_only or not authority_horizons or len(authority_horizons) != 1:
        return {}
    label = authority_horizons[0]
    if label.endswith("m"):
        try:
            return {
                "minute_horizons": (int(label[:-1]),),
                "session_horizons": (),
                "future_calendar_days": 1,
            }
        except ValueError:
            return {}
    if label == "eod":
        return {
            "minute_horizons": (),
            "session_horizons": (),
            "future_calendar_days": 1,
        }
    if "_session" in label:
        try:
            sessions = int(label.split("_", 1)[0])
        except ValueError:
            return {}
        return {
            "minute_horizons": (),
            "session_horizons": (sessions,),
            "future_calendar_days": max(14, sessions * 3 + 7),
        }
    return {}


def _print_authority_gate(rows: list[dict[str, Any]]) -> None:
    print()
    print("Pattern-supported gate check")
    print("  horizon rows coverage  avg_net  EV?  lift_pp lift?  p_value   p? verdict")
    for row in rows:
        print(
            f"  {row['label']:<8} "
            f"{row.get('rows') or 0:>4} "
            f"{_fmt_rate(row.get('coverage_pct')):>8} "
            f"{_fmt_pct(row.get('avg_net_return_pct')):>8} "
            f"{str(row.get('net_ev_pass')):>4} "
            f"{_fmt_num(row.get('decile_lift_pct')):>7} "
            f"{str(row.get('decile_lift_pass')):>5} "
            f"{_fmt_p(row.get('null_p_value')):>8} "
            f"{str(row.get('p_value_pass')):>4} "
            f"{row.get('verdict')}"
        )
    print()
    print("Pattern-supported p-value diagnostics")
    print(
        "  horizon       n blocks sample   seed        exceed/perms floor? "
        "p_floor obs_lift null_mean null_std null_p95 null_max"
    )
    for row in rows:
        decile = row.get("decile_test") or {}
        if not decile or decile.get("n", 0) == 0:
            continue
        print(
            f"  {row['label']:<8} "
            f"{decile.get('n') or 0:>5} "
            f"{decile.get('block_count') or 0:>6} "
            f"{str(decile.get('sample_fingerprint') or '-')[:8]:>8} "
            f"{decile.get('permutation_seed') or '-':>10} "
            f"{decile.get('null_exceedances') if decile.get('null_exceedances') is not None else '-':>4}/"
            f"{decile.get('permutations') or 0:<5} "
            f"{str(decile.get('null_p_value_is_floor')):>6} "
            f"{_fmt_p(decile.get('null_p_value_floor')):>7} "
            f"{_fmt_num(decile.get('lift_pct')):>8} "
            f"{_fmt_num(decile.get('null_lift_mean')):>9} "
            f"{_fmt_num(decile.get('null_lift_std')):>8} "
            f"{_fmt_num(decile.get('null_lift_p95')):>8} "
            f"{_fmt_num(decile.get('null_lift_max')):>8}"
        )

    print()
    print("Pattern-supported sample concentration")
    print(
        "  horizon       n symbols top_symbol top_sym% top5_sym% "
        "dates top_date   top_date% top3_date%"
    )
    for row in rows:
        decile = row.get("decile_test") or {}
        concentration = decile.get("sample_concentration") or {}
        if not concentration:
            continue
        top_symbol = (concentration.get("top_symbols") or [{}])[0]
        top_date = (concentration.get("top_dates") or [{}])[0]
        print(
            f"  {row['label']:<8} "
            f"{concentration.get('sample_rows') or 0:>5} "
            f"{concentration.get('symbol_count') or 0:>7} "
            f"{str(top_symbol.get('value') or '-')[:10]:>10} "
            f"{_fmt_rate(top_symbol.get('share_pct')):>8} "
            f"{_fmt_rate(concentration.get('top_5_symbol_share_pct')):>9} "
            f"{concentration.get('date_count') or 0:>5} "
            f"{str(top_date.get('value') or '-')[:10]:>10} "
            f"{_fmt_rate(top_date.get('share_pct')):>9} "
            f"{_fmt_rate(concentration.get('top_3_date_share_pct')):>10}"
        )


def _print_pattern_gate_counterfactual(payload: dict[str, Any]) -> None:
    counterfactual = payload.get("pattern_gate_counterfactual") or {}
    if not counterfactual:
        return
    print()
    print("Approval-gate pattern counterfactual")
    print(f"  definition                  : {counterfactual.get('definition')}")
    print(f"  pattern_buy_score_min       : {counterfactual.get('pattern_buy_score_min')}")
    print(f"  non_passing_rows            : {counterfactual.get('non_passing_rows')}")
    print(f"  pattern_buy_supported_rows  : {counterfactual.get('pattern_buy_supported_rows')}")
    print(f"  pattern_avoid_supported_rows: {counterfactual.get('pattern_avoid_supported_rows')}")
    print(f"  pattern_neutral_or_wait_rows: {counterfactual.get('pattern_neutral_or_wait_rows')}")
    print(f"  pattern_unknown_rows        : {counterfactual.get('pattern_unknown_rows')}")
    print("  authority                   : observe-only; pattern support does not override gates")
    print(f"  authority_screen_verdict    : {counterfactual.get('authority_screen_verdict')}")
    scope_horizons = counterfactual.get("authority_gate_scope_horizons") or []
    print(f"  authority_gate_horizons     : {', '.join(scope_horizons) if scope_horizons else '-'}")
    pass_horizons = counterfactual.get("authority_screen_pass_horizons") or []
    print(f"  screen_pass_horizons        : {', '.join(pass_horizons) if pass_horizons else '-'}")
    limitations = counterfactual.get("authority_screen_limitations") or []
    if limitations:
        print(f"  screen_limitations          : {', '.join(limitations)}")

    _print_summary_table(
        "Non-passing candidates by horizon",
        counterfactual.get("non_passing_horizons") or [],
    )
    _print_summary_table(
        "Pattern-supported non-passing buys",
        counterfactual.get("buy_supported_horizons") or [],
    )
    _print_summary_table(
        "Pattern-avoid non-passing candidates",
        counterfactual.get("avoid_supported_horizons") or [],
    )
    _print_authority_gate(counterfactual.get("authority_gate_horizons") or [])
    _print_compact_group(
        "Top non-passing pattern groups",
        counterfactual.get("top_pattern_groups") or {},
    )


def run_hold_duration_replay(
    target_date: str,
    *,
    base_dir: Path,
    lookback_days: int = 10,
    cost_bps: float | None = None,
    min_net_ev_pct: float = 0.25,
    gate_permutations: int = 2_000,
    authority_horizons: tuple[str, ...] | None = ("60m",),
    primary_horizon_only: bool = False,
    limit: int | None = None,
) -> bool:
    print()
    print("=" * 88)
    print(f"  Hold-Duration Replay - {target_date}")
    print("=" * 88)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    service = HoldDurationReplayService(
        HoldDurationReplayRepository(db_path),
        HoldDurationReplayConfig(
            lookback_days=lookback_days,
            cost_bps=DEFAULT_REALISTIC_REPLAY_COST_BPS if cost_bps is None else cost_bps,
            cost_source=DEFAULT_REPLAY_COST_SOURCE if cost_bps is None else "operator_cost_bps_override",
            min_net_ev_pct=min_net_ev_pct,
            gate_permutations=gate_permutations,
            authority_gate_horizons=authority_horizons,
            **_primary_horizon_config(authority_horizons, primary_horizon_only),
        ),
    )
    payload = service.report(target_date, lookback_days=lookback_days, limit=limit)

    print(f"report_version              : {payload['report_version']}")
    print(f"runtime_effect              : {payload['runtime_effect']}")
    print(f"source                      : {payload['source']}")
    print(f"price_source                : {payload['price_source']}")
    print(f"window                      : {payload['start_date']} -> {payload['end_date']}")
    print(f"lookback_days               : {payload['lookback_days']}")
    print(f"candidate_rows              : {payload['candidate_rows']}")
    print(f"symbols                     : {payload['symbols']}")
    print(f"price_rows                  : {payload['price_rows']}")
    print(f"cost_bps_round_trip         : {payload['cost_bps']}")
    print(f"cost_source                 : {payload['cost_source']}")
    print(f"net_ev_hit_threshold_pct    : {payload['min_net_ev_pct']}")
    print(f"decile_lift_bar_pp          : {payload['lift_bar_pct']}")
    print(f"p_value_bar                 : {payload['p_value_bar']}")
    print(f"gate_permutations           : {payload['gate_permutations']}")
    print(f"primary_horizon_only        : {primary_horizon_only}")
    print("authority                   : read-only; no exit, sizing, gate, broker, or order changes")

    _print_summary_table("Fixed-horizon replay", payload["horizons"])
    _print_summary_table("Hold-policy counterfactuals", payload["policy_replays"])
    _print_pattern_gate_counterfactual(payload)

    cohorts = payload["winner_cohorts"]
    _print_summary_table("15-minute winners held longer", cohorts.get("15m_winners", []))
    _print_summary_table("15-minute losers held longer", cohorts.get("15m_losers", []))

    _print_compact_group("Score cohorts", payload["score_cohorts"])
    _print_compact_group("Hard-block groups", payload["gate_groups"])

    if payload["coverage_warnings"]:
        print()
        print("Coverage warnings")
        for warning in payload["coverage_warnings"]:
            print(f"  [WARN] {warning}")

    if payload["candidate_rows"] == 0:
        print("[WARN] no auto-buy candidate rows found")
        return False
    if payload["price_rows"] == 0:
        print("[WARN] no replay price rows found")
        return False

    print()
    print("[OK] hold-duration replay completed; no live authority changed")
    return True
