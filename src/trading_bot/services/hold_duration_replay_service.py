"""Hold-duration replay calculations for auto-buy candidates.

This module is report-only. It does not write labels, change exits, or affect
live order authority.
"""

from __future__ import annotations

import random
import zlib
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any

DEFAULT_REALISTIC_REPLAY_COST_BPS = 16.0
DEFAULT_REPLAY_COST_SOURCE = "default_cost_fallback_spread_0.08_slippage_0.04x2"


@dataclass(frozen=True)
class HoldDurationReplayConfig:
    lookback_days: int = 10
    cost_bps: float = DEFAULT_REALISTIC_REPLAY_COST_BPS
    cost_source: str = DEFAULT_REPLAY_COST_SOURCE
    min_net_ev_pct: float = 0.25
    lift_bar_pct: float = 8.0
    p_value_bar: float = 0.05
    decile_buckets: int = 10
    gate_permutations: int = 2_000
    gate_permutation_seed: int = 7
    authority_gate_horizons: tuple[str, ...] | None = None
    minute_horizons: tuple[int, ...] = (5, 15, 30, 60, 120, 240)
    session_horizons: tuple[int, ...] = (1, 2, 3, 5)
    winner_probe_minutes: int = 15
    future_calendar_days: int = 14
    max_coverage_warning_pct: float = 0.75
    pattern_buy_score_min: float = 70.0
    pattern_group_limit: int = 12


@dataclass(frozen=True)
class PricePoint:
    symbol: str
    timestamp: str
    dt: datetime
    session_date: str
    price: float
    pattern_label: str | None = None
    pattern_score: float | None = None
    opportunity_action: str | None = None
    opportunity_quality: str | None = None
    long_opportunity_score: float | None = None
    sell_opportunity_score: float | None = None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _pct(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start <= 0:
        return None
    return (end - start) / start * 100.0


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None else None


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return count / total * 100.0


def _date_from_iso(value: str) -> date:
    return date.fromisoformat(value[:10])


def _horizon_label(kind: str, value: int | None = None) -> str:
    if kind == "minute":
        return f"{value}m"
    if kind == "session":
        return f"{value}_session" if value == 1 else f"{value}_sessions"
    return "eod"


def _score_bucket(score: float | None) -> str:
    if score is None:
        return "score_missing"
    if score >= 13:
        return "score_13_plus"
    if score >= 10:
        return "score_10_12"
    if score >= 7:
        return "score_7_9"
    return "score_below_7"


def _gate_group(reason: str | None) -> str:
    text = (reason or "").lower()
    if not text:
        return "no_hard_block"
    if "strategy_memory" in text:
        return "strategy_memory"
    if "setup_avoid" in text:
        return "setup_avoid"
    if "bias_avoid" in text:
        return "bias_avoid"
    if "tape" in text:
        return "tape_regime"
    if "negative_session" in text:
        return "negative_session"
    return "other_hard_block"


def _clean_text(value: Any) -> str:
    return str(value or "").strip().lower()


class HoldDurationReplayService:
    def __init__(self, repository: Any, config: HoldDurationReplayConfig | None = None):
        self.repository = repository
        self.config = config or HoldDurationReplayConfig()

    def report(
        self,
        target_date: str,
        *,
        lookback_days: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        cfg = self.config
        days = cfg.lookback_days if lookback_days is None else lookback_days
        end = _date_from_iso(target_date)
        start = end - timedelta(days=max(days, 0))
        price_end = end + timedelta(days=cfg.future_calendar_days)
        start_s = start.isoformat()
        end_s = end.isoformat()

        candidates = self.repository.auto_buy_candidates_between(start_s, end_s, limit=limit)
        symbols = sorted({str(row.get("symbol") or "").upper() for row in candidates if row.get("symbol")})
        if hasattr(self.repository, "replay_price_points"):
            raw_points = self.repository.replay_price_points(
                symbols,
                start_s,
                price_end.isoformat(),
            )
        else:
            raw_points = self.repository.feature_price_points(
                symbols,
                start_s,
                price_end.isoformat(),
            )
        price_source = self._price_source(raw_points)
        points_by_symbol = self._build_price_index(raw_points)
        details = [
            self._candidate_detail(row, points_by_symbol)
            for row in candidates
        ]

        horizon_labels = [
            *[_horizon_label("minute", minutes) for minutes in cfg.minute_horizons],
            "eod",
            *[_horizon_label("session", sessions) for sessions in cfg.session_horizons],
        ]
        warnings = self._coverage_warnings(details, horizon_labels)

        return {
            "report_version": "hold_duration_replay_v3",
            "runtime_effect": "read_only_replay_no_trade_or_policy_authority",
            "source": f"auto_buy_candidates + {price_source}",
            "price_source": price_source,
            "target_date": target_date,
            "start_date": start_s,
            "end_date": end_s,
            "lookback_days": days,
            "cost_bps": cfg.cost_bps,
            "cost_source": cfg.cost_source,
            "min_net_ev_pct": cfg.min_net_ev_pct,
            "lift_bar_pct": cfg.lift_bar_pct,
            "p_value_bar": cfg.p_value_bar,
            "gate_permutations": cfg.gate_permutations,
            "candidate_rows": len(candidates),
            "price_rows": len(raw_points),
            "symbols": len(symbols),
            "horizons": [
                self._summarize_horizon(details, label, total=len(details))
                for label in horizon_labels
            ],
            "winner_cohorts": self._winner_cohorts(details, horizon_labels),
            "policy_replays": self._policy_replays(details),
            "pattern_gate_counterfactual": self._pattern_gate_counterfactual(
                details,
                horizon_labels,
            ),
            "score_cohorts": self._group_summaries(details, horizon_labels, "score_bucket"),
            "gate_groups": self._group_summaries(details, horizon_labels, "gate_group"),
            "coverage_warnings": warnings,
        }

    @staticmethod
    def _price_source(rows: list[dict[str, Any]]) -> str:
        sources = sorted({str(row.get("price_source") or "") for row in rows if row.get("price_source")})
        if not sources:
            return "unknown_price_path"
        if len(sources) == 1:
            return sources[0]
        return ",".join(sources)

    def _build_price_index(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        points_by_symbol: dict[str, dict[str, Any]] = {}
        for row in rows:
            dt = _parse_dt(row.get("timestamp"))
            price = _as_float(row.get("last_price"))
            symbol = str(row.get("symbol") or "").upper()
            if not symbol or dt is None or price is None:
                continue
            points_by_symbol.setdefault(symbol, {"points": []})["points"].append(
                PricePoint(
                    symbol=symbol,
                    timestamp=str(row.get("timestamp")),
                    dt=dt,
                    session_date=str(row.get("timestamp"))[:10],
                    price=price,
                    pattern_label=row.get("pattern_label"),
                    pattern_score=_as_float(row.get("pattern_score")),
                    opportunity_action=row.get("opportunity_action"),
                    opportunity_quality=row.get("opportunity_quality"),
                    long_opportunity_score=_as_float(row.get("long_opportunity_score")),
                    sell_opportunity_score=_as_float(row.get("sell_opportunity_score")),
                )
            )

        for data in points_by_symbol.values():
            points = sorted(data["points"], key=lambda point: point.dt)
            by_date: dict[str, list[PricePoint]] = {}
            for point in points:
                by_date.setdefault(point.session_date, []).append(point)
            by_date_dts = {
                session_date: [point.dt for point in day_points]
                for session_date, day_points in by_date.items()
            }
            prices = [point.price for point in points]
            data["points"] = points
            data["dts"] = [point.dt for point in points]
            data["prices"] = prices
            data["by_date"] = by_date
            data["by_date_dts"] = by_date_dts
            data["session_dates"] = sorted(by_date)
            data["session_date_index"] = {
                session_date: idx for idx, session_date in enumerate(data["session_dates"])
            }
            data["range_index"] = self._build_range_index(prices)
        return points_by_symbol

    @staticmethod
    def _build_range_index(prices: list[float]) -> dict[str, Any]:
        if not prices:
            return {"log": [0], "min": [], "max": []}
        logs = [0] * (len(prices) + 1)
        for idx in range(2, len(prices) + 1):
            logs[idx] = logs[idx // 2] + 1
        min_table = [prices]
        max_table = [prices]
        step = 1
        while step * 2 <= len(prices):
            prev_min = min_table[-1]
            prev_max = max_table[-1]
            width = len(prices) - (step * 2) + 1
            min_table.append(
                [min(prev_min[idx], prev_min[idx + step]) for idx in range(width)]
            )
            max_table.append(
                [max(prev_max[idx], prev_max[idx + step]) for idx in range(width)]
            )
            step *= 2
        return {"log": logs, "min": min_table, "max": max_table}

    def _candidate_detail(
        self,
        row: dict[str, Any],
        points_by_symbol: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        symbol = str(row.get("symbol") or "").upper()
        candidate_ts = str(row.get("timestamp") or "")
        candidate_dt = _parse_dt(candidate_ts)
        candidate_date = candidate_ts[:10]
        score = _as_float(row.get("score"))
        hard_block_reason = row.get("hard_block_reason")
        order_submitted = int(row.get("order_submitted") or 0)
        decision = row.get("decision")
        detail = {
            "id": row.get("id"),
            "timestamp": candidate_ts,
            "symbol": symbol,
            "signal_source": row.get("signal_source"),
            "decision": decision,
            "score": score,
            "score_bucket": _score_bucket(score),
            "setup_score": _as_float(row.get("setup_score")),
            "setup_label": row.get("setup_label"),
            "setup_recommendation": row.get("setup_recommendation"),
            "hard_block_reason": hard_block_reason,
            "reason": row.get("reason"),
            "gate_group": _gate_group(hard_block_reason),
            "order_submitted": order_submitted,
            "non_passing_gate": self._non_passing_gate(decision, hard_block_reason),
            "candidate_date": candidate_date,
            "reference_session_date": None,
            "pattern_signal": "unknown",
            "pattern_gate_group": "unknown_pattern",
            "pattern_buy_support": False,
            "pattern_avoid_support": False,
            "pattern_label": None,
            "pattern_score": None,
            "opportunity_action": None,
            "opportunity_quality": None,
            "long_opportunity_score": None,
            "sell_opportunity_score": None,
            "horizons": {},
        }
        if candidate_dt is None:
            return detail
        data = points_by_symbol.get(symbol)
        if not data:
            return detail
        ref = self._reference_point(data, candidate_dt, candidate_date)
        if ref is None:
            return detail
        detail["reference_session_date"] = ref.session_date
        self._apply_pattern_fields(detail, ref)

        for minutes in self.config.minute_horizons:
            label = _horizon_label("minute", minutes)
            exit_point = self._minute_exit_point(data, ref.dt, ref.session_date, minutes)
            detail["horizons"][label] = self._outcome(ref, exit_point, data)

        detail["horizons"]["eod"] = self._outcome(
            ref,
            self._eod_exit_point(data, ref.dt, ref.session_date),
            data,
        )

        for sessions in self.config.session_horizons:
            label = _horizon_label("session", sessions)
            exit_point = self._session_exit_point(data, ref.session_date, sessions)
            detail["horizons"][label] = self._outcome(ref, exit_point, data)

        return detail

    @staticmethod
    def _non_passing_gate(decision: Any, hard_block_reason: Any) -> bool:
        if str(hard_block_reason or "").strip():
            return True
        decision_text = _clean_text(decision)
        return decision_text in {
            "skip",
            "watch",
            "reject",
            "rejected",
            "blocked",
            "avoid",
            "sell_or_avoid_candidate",
        }

    def _apply_pattern_fields(self, detail: dict[str, Any], point: PricePoint) -> None:
        action = _clean_text(point.opportunity_action)
        quality = _clean_text(point.opportunity_quality)
        buy_qualities = {"best_buy_window", "good_buy_window"}
        avoid_qualities = {"best_sell_or_avoid_window", "good_sell_or_avoid_window"}
        avoid_support = action == "sell_or_avoid_candidate" or quality in avoid_qualities
        buy_support = (
            not avoid_support
            and (
                action == "buy_candidate"
                or quality in buy_qualities
                or (
                    point.long_opportunity_score is not None
                    and point.long_opportunity_score >= self.config.pattern_buy_score_min
                )
            )
        )
        if buy_support:
            pattern_signal = "buy_support"
        elif avoid_support:
            pattern_signal = "avoid_support"
        elif action or quality or point.long_opportunity_score is not None:
            pattern_signal = "neutral_or_wait"
        else:
            pattern_signal = "unknown"

        detail.update(
            {
                "pattern_signal": pattern_signal,
                "pattern_gate_group": self._pattern_gate_group(point),
                "pattern_buy_support": buy_support,
                "pattern_avoid_support": avoid_support,
                "pattern_label": point.pattern_label,
                "pattern_score": point.pattern_score,
                "opportunity_action": point.opportunity_action,
                "opportunity_quality": point.opportunity_quality,
                "long_opportunity_score": point.long_opportunity_score,
                "sell_opportunity_score": point.sell_opportunity_score,
            }
        )

    @staticmethod
    def _pattern_gate_group(point: PricePoint) -> str:
        label = str(point.pattern_label or "unknown_label")
        action = str(point.opportunity_action or "unknown_action")
        quality = str(point.opportunity_quality or "unknown_quality")
        return f"{label}|{action}|{quality}"

    @staticmethod
    def _reference_point(
        data: dict[str, Any],
        candidate_dt: datetime,
        candidate_date: str,
    ) -> PricePoint | None:
        day_points = data["by_date"].get(candidate_date) or []
        if not day_points:
            return None
        day_dts = data.get("by_date_dts", {}).get(candidate_date) or [
            point.dt for point in day_points
        ]
        idx = bisect_left(day_dts, candidate_dt)
        if idx >= len(day_points):
            return None
        return day_points[idx]

    @staticmethod
    def _minute_exit_point(
        data: dict[str, Any],
        candidate_dt: datetime,
        candidate_date: str,
        minutes: int,
    ) -> PricePoint | None:
        target_dt = candidate_dt + timedelta(minutes=minutes)
        day_points = data["by_date"].get(candidate_date) or []
        if not day_points:
            return None
        day_dts = data.get("by_date_dts", {}).get(candidate_date) or [
            point.dt for point in day_points
        ]
        idx = bisect_left(day_dts, target_dt)
        if idx >= len(day_points):
            return None
        return day_points[idx]

    @staticmethod
    def _eod_exit_point(
        data: dict[str, Any],
        candidate_dt: datetime,
        candidate_date: str,
    ) -> PricePoint | None:
        day_points = data["by_date"].get(candidate_date) or []
        if not day_points:
            return None
        day_dts = data.get("by_date_dts", {}).get(candidate_date) or [
            point.dt for point in day_points
        ]
        idx = bisect_left(day_dts, candidate_dt)
        return day_points[-1] if idx < len(day_points) else None

    @staticmethod
    def _session_exit_point(
        data: dict[str, Any],
        candidate_date: str,
        sessions: int,
    ) -> PricePoint | None:
        session_dates = data["session_dates"]
        date_index = data.get("session_date_index", {}).get(candidate_date)
        if date_index is None:
            return None
        target_idx = date_index + sessions
        if target_idx >= len(session_dates):
            return None
        target_date = session_dates[target_idx]
        day_points = data["by_date"].get(target_date) or []
        return day_points[-1] if day_points else None

    def _outcome(
        self,
        ref: PricePoint,
        exit_point: PricePoint | None,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        if exit_point is None:
            return None
        gross_return = _pct(ref.price, exit_point.price)
        if gross_return is None:
            return None
        low_price, high_price = self._range_min_max(data, ref.dt, exit_point.dt)
        hold_minutes = (exit_point.dt - ref.dt).total_seconds() / 60.0
        return {
            "exit_timestamp": exit_point.timestamp,
            "gross_return_pct": gross_return,
            "net_return_pct": gross_return - (self.config.cost_bps / 100.0),
            "mfe_pct": _pct(ref.price, high_price) if high_price is not None else gross_return,
            "mae_pct": _pct(ref.price, low_price) if low_price is not None else gross_return,
            "hold_minutes": hold_minutes,
        }

    @staticmethod
    def _range_min_max(
        data: dict[str, Any],
        start_dt: datetime,
        end_dt: datetime,
    ) -> tuple[float | None, float | None]:
        dts = data["dts"]
        start_idx = bisect_left(dts, start_dt)
        end_idx = bisect_right(dts, end_dt) - 1
        if start_idx > end_idx:
            return None, None
        length = end_idx - start_idx + 1
        index = data["range_index"]
        level = index["log"][length]
        span = 1 << level
        min_table = index["min"][level]
        max_table = index["max"][level]
        low = min(min_table[start_idx], min_table[end_idx - span + 1])
        high = max(max_table[start_idx], max_table[end_idx - span + 1])
        return low, high


    def _summarize_horizon(
        self,
        details: list[dict[str, Any]],
        horizon: str,
        *,
        total: int,
    ) -> dict[str, Any]:
        outcomes = [
            detail.get("horizons", {}).get(horizon)
            for detail in details
            if detail.get("horizons", {}).get(horizon) is not None
        ]
        return self._summarize_outcomes(horizon, outcomes, total=total)

    def _summarize_outcomes(
        self,
        label: str,
        outcomes: list[dict[str, Any]],
        *,
        total: int,
    ) -> dict[str, Any]:
        gross_values = [float(item["gross_return_pct"]) for item in outcomes]
        net_values = [float(item["net_return_pct"]) for item in outcomes]
        mfe_values = [float(item["mfe_pct"]) for item in outcomes if item.get("mfe_pct") is not None]
        mae_values = [float(item["mae_pct"]) for item in outcomes if item.get("mae_pct") is not None]
        hold_values = [
            float(item["hold_minutes"])
            for item in outcomes
            if item.get("hold_minutes") is not None
        ]
        rows = len(net_values)
        return {
            "label": label,
            "rows": rows,
            "total": total,
            "coverage_pct": _round(_rate(rows, total), 2),
            "avg_gross_return_pct": _round(_mean(gross_values)),
            "avg_net_return_pct": _round(_mean(net_values)),
            "median_net_return_pct": _round(median(net_values) if net_values else None),
            "positive_rate_pct": _round(_rate(sum(1 for value in net_values if value > 0), rows), 2),
            "ev_hit_rate_pct": _round(
                _rate(sum(1 for value in net_values if value >= self.config.min_net_ev_pct), rows),
                2,
            ),
            "negative_rate_pct": _round(_rate(sum(1 for value in net_values if value < 0), rows), 2),
            "avg_mfe_pct": _round(_mean(mfe_values)),
            "avg_mae_pct": _round(_mean(mae_values)),
            "avg_hold_minutes": _round(_mean(hold_values), 1),
        }

    def _winner_cohorts(
        self,
        details: list[dict[str, Any]],
        horizon_labels: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        probe_label = _horizon_label("minute", self.config.winner_probe_minutes)
        cohorts = {"15m_winners": [], "15m_losers": [], "15m_flats": []}
        members = {
            "15m_winners": self._filter_probe(details, probe_label, "winner"),
            "15m_losers": self._filter_probe(details, probe_label, "loser"),
            "15m_flats": self._filter_probe(details, probe_label, "flat"),
        }
        selected_labels = [
            label
            for label in horizon_labels
            if label in {probe_label, "60m", "120m", "240m", "eod", "1_session", "3_sessions", "5_sessions"}
        ]
        for name, rows in members.items():
            cohorts[name] = [
                self._summarize_horizon(rows, label, total=len(rows))
                for label in selected_labels
            ]
        return cohorts

    @staticmethod
    def _filter_probe(
        details: list[dict[str, Any]],
        probe_label: str,
        kind: str,
    ) -> list[dict[str, Any]]:
        rows = []
        for detail in details:
            outcome = detail.get("horizons", {}).get(probe_label)
            if not outcome:
                continue
            value = _as_float(outcome.get("gross_return_pct"))
            if value is None:
                continue
            if kind == "winner" and value > 0:
                rows.append(detail)
            elif kind == "loser" and value < 0:
                rows.append(detail)
            elif kind == "flat" and value == 0:
                rows.append(detail)
        return rows

    def _policy_replays(self, details: list[dict[str, Any]]) -> list[dict[str, Any]]:
        policies = [
            ("exit_all_15m", "15m"),
            ("hold_15m_winners_to_60m", "60m"),
            ("hold_15m_winners_to_120m", "120m"),
            ("hold_15m_winners_to_240m", "240m"),
            ("trail_15m_winners_to_eod", "eod"),
            ("swing_15m_winners_to_1_session", "1_session"),
            ("swing_15m_winners_to_3_sessions", "3_sessions"),
            ("swing_15m_winners_to_5_sessions", "5_sessions"),
        ]
        return [
            self._summarize_policy(details, policy_name, extension_label)
            for policy_name, extension_label in policies
        ]

    def _summarize_policy(
        self,
        details: list[dict[str, Any]],
        policy_name: str,
        extension_label: str,
    ) -> dict[str, Any]:
        selected = []
        extended = 0
        for detail in details:
            horizons = detail.get("horizons", {})
            probe = horizons.get("15m")
            if probe is None:
                continue
            probe_return = _as_float(probe.get("gross_return_pct"))
            if extension_label == "15m" or probe_return is None or probe_return <= 0:
                selected.append(probe)
                continue
            extension = horizons.get(extension_label)
            if extension is None:
                continue
            selected.append(extension)
            extended += 1
        summary = self._summarize_outcomes(policy_name, selected, total=len(details))
        summary["extended_rows"] = extended
        summary["extension_horizon"] = extension_label
        return summary

    def _group_summaries(
        self,
        details: list[dict[str, Any]],
        horizon_labels: list[str],
        group_key: str,
    ) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for detail in details:
            groups.setdefault(str(detail.get(group_key) or "unknown"), []).append(detail)
        selected_labels = [
            label
            for label in horizon_labels
            if label in {"15m", "60m", "120m", "240m", "eod", "1_session", "5_sessions"}
        ]
        return {
            group: [
                self._summarize_horizon(rows, label, total=len(rows))
                for label in selected_labels
            ]
            for group, rows in sorted(groups.items())
        }

    def _pattern_gate_counterfactual(
        self,
        details: list[dict[str, Any]],
        horizon_labels: list[str],
    ) -> dict[str, Any]:
        non_passing = [detail for detail in details if detail.get("non_passing_gate")]
        buy_supported = [
            detail
            for detail in non_passing
            if detail.get("pattern_buy_support")
        ]
        avoid_supported = [
            detail
            for detail in non_passing
            if detail.get("pattern_avoid_support")
        ]
        neutral_or_wait = [
            detail
            for detail in non_passing
            if detail.get("pattern_signal") == "neutral_or_wait"
        ]
        unknown = [
            detail
            for detail in non_passing
            if detail.get("pattern_signal") == "unknown"
        ]
        selected_labels = [
            label
            for label in horizon_labels
            if label in {"15m", "60m", "120m", "240m", "eod", "1_session", "3_sessions", "5_sessions"}
        ]
        authority_labels = self._authority_gate_labels(selected_labels)
        authority_gate_horizons = [
            self._authority_gate_for_horizon(buy_supported, label)
            for label in authority_labels
        ]
        screen_pass_horizons = [
            row["label"]
            for row in authority_gate_horizons
            if row.get("verdict") == "passes_research_bar"
        ]
        return {
            "definition": (
                "observe-only replay of candidates that had a hard block or skip/watch/rejected decision; "
                "pattern buy support is based on bar_pattern_features opportunity_action/quality"
            ),
            "pattern_buy_score_min": self.config.pattern_buy_score_min,
            "non_passing_rows": len(non_passing),
            "pattern_buy_supported_rows": len(buy_supported),
            "pattern_avoid_supported_rows": len(avoid_supported),
            "pattern_neutral_or_wait_rows": len(neutral_or_wait),
            "pattern_unknown_rows": len(unknown),
            "non_passing_horizons": [
                self._summarize_horizon(non_passing, label, total=len(non_passing))
                for label in selected_labels
            ],
            "buy_supported_horizons": [
                self._summarize_horizon(buy_supported, label, total=len(buy_supported))
                for label in selected_labels
            ],
            "avoid_supported_horizons": [
                self._summarize_horizon(avoid_supported, label, total=len(avoid_supported))
                for label in selected_labels
            ],
            "neutral_or_wait_horizons": [
                self._summarize_horizon(neutral_or_wait, label, total=len(neutral_or_wait))
                for label in selected_labels
            ],
            "authority_gate_horizons": authority_gate_horizons,
            "authority_gate_scope_horizons": authority_labels,
            "authority_screen_pass_horizons": screen_pass_horizons,
            "authority_screen_verdict": (
                "screen_pass_but_not_authority_ready"
                if screen_pass_horizons
                else "fails_research_bar"
            ),
            "authority_screen_limitations": [
                "no_precommitted_primary_horizon",
                "single_window_replay",
                "multiple_horizon_scan",
                "not_a_frozen_promotion_contract",
                "p_values_are_permutation_estimates_with_resolution_floor",
            ],
            "top_pattern_groups": self._top_pattern_groups(non_passing, selected_labels),
        }

    def _authority_gate_labels(self, selected_labels: list[str]) -> list[str]:
        configured = self.config.authority_gate_horizons
        if configured is None:
            return selected_labels
        allowed = {str(label) for label in configured}
        return [label for label in selected_labels if label in allowed]

    def _authority_gate_for_horizon(
        self,
        details: list[dict[str, Any]],
        horizon: str,
    ) -> dict[str, Any]:
        summary = self._summarize_horizon(details, horizon, total=len(details))
        decile = self._score_decile_lift(details, horizon, "long_opportunity_score")
        avg_net = summary.get("avg_net_return_pct")
        ev_pass = avg_net is not None and float(avg_net) >= self.config.min_net_ev_pct
        lift = decile.get("lift_pct")
        p_value = decile.get("null_p_value")
        lift_pass = lift is not None and float(lift) >= self.config.lift_bar_pct
        p_pass = p_value is not None and float(p_value) <= self.config.p_value_bar
        coverage = (summary.get("coverage_pct") or 0.0) / 100.0
        coverage_pass = coverage >= self.config.max_coverage_warning_pct
        verdict = (
            "passes_research_bar"
            if ev_pass and lift_pass and p_pass and coverage_pass
            else "fails_research_bar"
        )
        return {
            "label": horizon,
            "verdict": verdict,
            "authority": "observe_only_no_trade_policy_change",
            "net_ev_pass": ev_pass,
            "decile_lift_pass": lift_pass,
            "p_value_pass": p_pass,
            "coverage_pass": coverage_pass,
            "avg_net_return_pct": avg_net,
            "min_net_ev_pct": self.config.min_net_ev_pct,
            "decile_lift_pct": lift,
            "lift_bar_pct": self.config.lift_bar_pct,
            "null_p_value": p_value,
            "p_value_bar": self.config.p_value_bar,
            "coverage_pct": summary.get("coverage_pct"),
            "rows": summary.get("rows"),
            "total": summary.get("total"),
            "decile_test": decile,
        }

    def _score_decile_lift(
        self,
        details: list[dict[str, Any]],
        horizon: str,
        score_key: str,
    ) -> dict[str, Any]:
        usable = []
        for detail in details:
            score = _as_float(detail.get(score_key))
            outcome = detail.get("horizons", {}).get(horizon)
            if score is None or outcome is None:
                continue
            net_return = _as_float(outcome.get("net_return_pct"))
            if net_return is None:
                continue
            usable.append(
                {
                    "sample_id": str(detail.get("id") or f"{detail.get('symbol')}|{detail.get('timestamp')}"),
                    "symbol": str(detail.get("symbol") or "__missing__"),
                    "sample_date": str(
                        detail.get("reference_session_date")
                        or detail.get("candidate_date")
                        or "__missing__"
                    ),
                    "score": score,
                    "net_return_pct": net_return,
                    "success": net_return >= self.config.min_net_ev_pct,
                    "block": str(detail.get("reference_session_date") or detail.get("candidate_date") or "__missing__"),
                }
            )
        usable.sort(key=lambda item: float(item["score"]))
        n = len(usable)
        buckets = max(1, int(self.config.decile_buckets))
        required_n = buckets * 3
        if n < required_n:
            return {
                "score": score_key,
                "n": n,
                "required_n": required_n,
                "buckets": [],
                "lift_pct": None,
                "null_p_value": None,
                "null_lift_p95": None,
                "null_verdict": "not_run",
                "permutations": self.config.gate_permutations,
                "verdict": "too_few_rows",
            }

        ranges = self._bucket_ranges(n, buckets)
        bucket_rows = []
        success_rates = []
        for idx, (lo, hi) in enumerate(ranges):
            chunk = usable[lo:hi]
            scores = [float(item["score"]) for item in chunk]
            returns = [float(item["net_return_pct"]) for item in chunk]
            successes = [bool(item["success"]) for item in chunk]
            success_rate = _rate(sum(1 for item in successes if item), len(successes))
            success_rates.append(success_rate or 0.0)
            bucket_rows.append(
                {
                    "bucket": f"D{idx + 1}",
                    "n": len(chunk),
                    "score_min": _round(min(scores) if scores else None),
                    "score_max": _round(max(scores) if scores else None),
                    "success_rate_pct": _round(success_rate, 2),
                    "avg_net_return_pct": _round(_mean(returns)),
                }
            )

        lift = round(success_rates[-1] - success_rates[0], 1)
        p_payload = self._blocked_success_lift_null(
            successes=[bool(item["success"]) for item in usable],
            blocks=[str(item["block"]) for item in usable],
            ranges=ranges,
            observed_lift=lift,
            seed_salt=f"{horizon}:{score_key}:{n}",
        )
        aligned_steps = sum(
            1 for idx in range(1, len(success_rates)) if success_rates[idx] >= success_rates[idx - 1]
        )
        monotonicity = round(aligned_steps / (len(success_rates) - 1), 4) if len(success_rates) > 1 else None
        null_p = p_payload.get("null_p_value")
        verdict = (
            "rank_orders_outcomes"
            if lift >= self.config.lift_bar_pct
            and null_p is not None
            and float(null_p) <= self.config.p_value_bar
            else "weak_or_flat"
        )
        return {
            "score": score_key,
            "horizon": horizon,
            "n": n,
            "required_n": required_n,
            "sample_ids": [str(item["sample_id"]) for item in usable],
            "sample_fingerprint": self._sample_fingerprint(
                [str(item["sample_id"]) for item in usable]
            ),
            "sample_concentration": self._sample_concentration(usable),
            "success_rows": sum(1 for item in usable if item["success"]),
            "failure_rows": sum(1 for item in usable if not item["success"]),
            "block_count": len({str(item["block"]) for item in usable}),
            "buckets": bucket_rows,
            "lift_pct": lift,
            "monotonicity": monotonicity,
            "direction": "higher_score_is_better",
            "success_definition": f"net_return_pct >= {self.config.min_net_ev_pct}",
            **p_payload,
            "verdict": verdict,
        }

    @staticmethod
    def _bucket_ranges(n: int, n_buckets: int) -> list[tuple[int, int]]:
        size = n // n_buckets
        return [
            (idx * size, n if idx == n_buckets - 1 else (idx + 1) * size)
            for idx in range(n_buckets)
        ]

    @staticmethod
    def _success_lift(values: list[bool], ranges: list[tuple[int, int]]) -> float:
        rates = []
        for lo, hi in ranges:
            chunk = values[lo:hi]
            if not chunk:
                rates.append(0.0)
                continue
            rates.append(100.0 * sum(1 for value in chunk if value) / len(chunk))
        return rates[-1] - rates[0]

    def _blocked_success_lift_null(
        self,
        *,
        successes: list[bool],
        blocks: list[str],
        ranges: list[tuple[int, int]],
        observed_lift: float,
        seed_salt: str,
    ) -> dict[str, Any]:
        permutations = int(self.config.gate_permutations)
        if permutations <= 0:
            return {
                "null_p_value": None,
                "null_lift_p95": None,
                "null_verdict": "not_run",
                "permutations": permutations,
                "null_block": "not_run",
            }
        seed = self.config.gate_permutation_seed + zlib.crc32(seed_salt.encode("utf-8"))
        rng = random.Random(seed)
        block_indices: dict[str, list[int]] = {}
        for idx, block in enumerate(blocks):
            block_indices.setdefault(block, []).append(idx)
        low_lo, low_hi = ranges[0]
        high_lo, high_hi = ranges[-1]
        low_n = max(0, low_hi - low_lo)
        high_n = max(0, high_hi - high_lo)
        block_draws = []
        for indices in block_indices.values():
            low_draws = sum(1 for idx in indices if low_lo <= idx < low_hi)
            high_draws = sum(1 for idx in indices if high_lo <= idx < high_hi)
            if low_draws == 0 and high_draws == 0:
                continue
            success_count = sum(1 for idx in indices if successes[idx])
            block_draws.append(
                {
                    "successes": success_count,
                    "failures": len(indices) - success_count,
                    "low_draws": low_draws,
                    "high_draws": high_draws,
                }
            )
        null_lifts = []
        is_iid = set(block_indices) == {"__iid__"}
        for _ in range(permutations):
            low_successes = 0
            high_successes = 0
            for block in block_draws:
                successes_left = int(block["successes"])
                failures_left = int(block["failures"])
                low_hits = self._draw_hypergeometric_successes(
                    successes_left,
                    failures_left,
                    int(block["low_draws"]),
                    rng,
                )
                successes_left -= low_hits
                failures_left -= int(block["low_draws"]) - low_hits
                high_hits = self._draw_hypergeometric_successes(
                    successes_left,
                    failures_left,
                    int(block["high_draws"]),
                    rng,
                )
                low_successes += low_hits
                high_successes += high_hits
            low_rate = 100.0 * low_successes / low_n if low_n else 0.0
            high_rate = 100.0 * high_successes / high_n if high_n else 0.0
            null_lifts.append(high_rate - low_rate)
        exceedances = sum(1 for value in null_lifts if value >= observed_lift)
        p_value = (exceedances + 1) / (permutations + 1)
        p_value_floor = 1 / (permutations + 1)
        sorted_lifts = sorted(null_lifts)
        p95_idx = min(int(0.95 * (len(sorted_lifts) - 1)), len(sorted_lifts) - 1)
        null_mean = _mean(null_lifts)
        null_variance = (
            sum((value - null_mean) ** 2 for value in null_lifts) / len(null_lifts)
            if null_lifts and null_mean is not None
            else None
        )
        return {
            "null_p_value": round(p_value, 6),
            "null_p_value_floor": round(p_value_floor, 6),
            "null_p_value_is_floor": exceedances == 0,
            "null_p_value_method": "plus_one_empirical_permutation",
            "null_lift_p95": round(sorted_lifts[p95_idx], 1),
            "null_lift_mean": _round(null_mean, 4),
            "null_lift_std": _round(null_variance ** 0.5 if null_variance is not None else None, 4),
            "null_lift_min": _round(min(null_lifts) if null_lifts else None, 4),
            "null_lift_max": _round(max(null_lifts) if null_lifts else None, 4),
            "null_exceedances": exceedances,
            "null_verdict": "beats_chance" if p_value <= self.config.p_value_bar else "within_noise",
            "permutations": permutations,
            "permutation_seed": seed,
            "permutation_seed_salt": seed_salt,
            "null_block": "iid" if is_iid else "market_date",
            "null_simulation_method": "blocked_hypergeometric_top_bottom_buckets",
        }

    @staticmethod
    def _draw_hypergeometric_successes(
        successes: int,
        failures: int,
        draws: int,
        rng: random.Random,
    ) -> int:
        hits = 0
        population = successes + failures
        if draws <= 0 or successes <= 0 or population <= 0:
            return 0
        draws = min(draws, population)
        for _ in range(draws):
            if population <= 0 or successes <= 0:
                break
            if rng.random() < successes / population:
                hits += 1
                successes -= 1
            else:
                failures -= 1
            population -= 1
        return hits

    @staticmethod
    def _sample_fingerprint(sample_ids: list[str]) -> str:
        payload = "\n".join(sorted(sample_ids))
        return f"{zlib.crc32(payload.encode('utf-8')):08x}"

    @staticmethod
    def _sample_concentration(rows: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(rows)

        def ranked_counts(key: str, limit: int) -> list[dict[str, Any]]:
            counts = Counter(str(row.get(key) or "__missing__") for row in rows)
            return [
                {
                    "value": value,
                    "count": count,
                    "share_pct": _round(_rate(count, total), 2),
                }
                for value, count in counts.most_common(limit)
            ]

        top_symbols = ranked_counts("symbol", 5)
        top_dates = ranked_counts("sample_date", 5)
        symbol_counts = Counter(str(row.get("symbol") or "__missing__") for row in rows)
        date_counts = Counter(str(row.get("sample_date") or "__missing__") for row in rows)
        top_5_symbol_count = sum(count for _, count in symbol_counts.most_common(5))
        top_3_date_count = sum(count for _, count in date_counts.most_common(3))
        return {
            "sample_rows": total,
            "symbol_count": len(symbol_counts),
            "date_count": len(date_counts),
            "top_symbols": top_symbols,
            "top_dates": top_dates,
            "top_symbol_share_pct": top_symbols[0]["share_pct"] if top_symbols else None,
            "top_5_symbol_share_pct": _round(_rate(top_5_symbol_count, total), 2),
            "top_date_share_pct": top_dates[0]["share_pct"] if top_dates else None,
            "top_3_date_share_pct": _round(_rate(top_3_date_count, total), 2),
        }

    def _top_pattern_groups(
        self,
        details: list[dict[str, Any]],
        horizon_labels: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for detail in details:
            groups.setdefault(str(detail.get("pattern_gate_group") or "unknown_pattern"), []).append(detail)
        ranked = sorted(groups.items(), key=lambda item: len(item[1]), reverse=True)
        return {
            group: [
                self._summarize_horizon(rows, label, total=len(rows))
                for label in horizon_labels
            ]
            for group, rows in ranked[: self.config.pattern_group_limit]
        }

    def _coverage_warnings(
        self,
        details: list[dict[str, Any]],
        horizon_labels: list[str],
    ) -> list[str]:
        warnings = []
        total = len(details)
        if total == 0:
            return ["no auto-buy candidate rows found for replay window"]
        for label in horizon_labels:
            summary = self._summarize_horizon(details, label, total=total)
            coverage = (summary.get("coverage_pct") or 0.0) / 100.0
            if coverage < self.config.max_coverage_warning_pct:
                warnings.append(
                    f"{label} coverage is {summary.get('coverage_pct')}%; treat horizon result as partial"
                )
        return warnings
