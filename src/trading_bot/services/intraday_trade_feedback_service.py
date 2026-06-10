"""Trade-quality feedback for active auto-buy learning.

This service combines same-day filled trades with prior-session matched-trade
outcomes. The same-day path reacts intraday; the historical path keeps repeated
mistakes from being forgotten after the session rolls over.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from repositories import auto_buy_repo

INTRADAY_TRADE_FEEDBACK_VERSION = "intraday_trade_feedback_v2"


def _norm(value: Any, default: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    return text or default


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _pct(entry_price: float, exit_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    return (exit_price - entry_price) / entry_price * 100.0


@dataclass(frozen=True)
class IntradayFeedbackThresholds:
    penalty_min_trades: int = 2
    penalty_loss_rate: float = 0.60
    penalty_avg_pnl_pct: float = -0.15
    penalty_score: float = -4.0
    block_min_trades: int = 3
    block_loss_rate: float = 0.75
    block_avg_pnl_pct: float = -0.25
    max_matched_age_minutes: float | None = 240.0
    historical_lookback_days: int = 20


class IntradayTradeFeedbackService:
    def __init__(
        self,
        *,
        db_path=None,
        thresholds: IntradayFeedbackThresholds | None = None,
    ):
        self.db_path = db_path
        self.thresholds = thresholds or IntradayFeedbackThresholds()

    def _load_rows(self, target_date: str) -> list[dict[str, Any]]:
        rows = auto_buy_repo.filled_trade_rows_for_intraday_feedback(
            target_date,
            db_path=self.db_path or auto_buy_repo.DB_PATH,
        )
        return [dict(row) for row in rows]

    def same_day_matches(self, target_date: str) -> list[dict[str, Any]]:
        rows = self._load_rows(target_date)
        open_lots: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        matches: list[dict[str, Any]] = []

        for row in rows:
            symbol = str(row.get("symbol") or "").upper()
            action = _norm(row.get("action"), "")
            try:
                qty = float(row.get("qty") or 0)
                price = float(row.get("fill_price") or 0)
            except (TypeError, ValueError):
                continue
            if not symbol or qty <= 0 or price <= 0:
                continue

            if action == "buy":
                open_lots[symbol].append({"qty": qty, "price": price, "row": row})
                continue

            if action != "sell":
                continue

            remaining = qty
            while remaining > 0 and open_lots[symbol]:
                lot = open_lots[symbol][0]
                matched_qty = min(remaining, float(lot["qty"]))
                entry_row = lot["row"]
                entry_price = float(lot["price"])
                pnl_pct = _pct(entry_price, price)
                entry_ts = _parse_ts(entry_row.get("timestamp"))
                exit_ts = _parse_ts(row.get("timestamp"))
                hold_minutes = None
                if entry_ts and exit_ts:
                    hold_minutes = round((exit_ts - entry_ts).total_seconds() / 60, 2)

                matches.append(
                    {
                        "symbol": symbol,
                        "entry_timestamp": entry_row.get("timestamp"),
                        "exit_timestamp": row.get("timestamp"),
                        "holding_minutes": hold_minutes,
                        "qty": matched_qty,
                        "entry_price": entry_price,
                        "exit_price": price,
                        "realized_pnl_pct": round(pnl_pct, 3),
                        "won": pnl_pct > 0,
                        "setup_policy_action": _norm(entry_row.get("setup_policy_action")),
                        "setup_label": _norm(entry_row.get("setup_label")),
                        "ml_prediction_bucket": _norm(entry_row.get("ml_prediction_bucket")),
                        "session_trend_label": _norm(entry_row.get("session_trend_label")),
                        "buy_opportunity_recommendation": _norm(
                            entry_row.get("buy_opportunity_recommendation")
                        ),
                        "feedback_source": "same_day_filled_trades",
                    }
                )

                lot["qty"] = float(lot["qty"]) - matched_qty
                remaining -= matched_qty
                if float(lot["qty"]) <= 0:
                    open_lots[symbol].popleft()

        return matches

    def historical_matches(self, target_date: str) -> list[dict[str, Any]]:
        rows = auto_buy_repo.historical_matched_trade_rows_for_feedback(
            target_date,
            lookback_days=self.thresholds.historical_lookback_days,
            db_path=self.db_path or auto_buy_repo.DB_PATH,
        )
        matches: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                realized_pnl_pct = float(item.get("realized_pnl_pct") or 0)
            except (TypeError, ValueError):
                continue
            matches.append(
                {
                    "symbol": str(item.get("symbol") or "").upper(),
                    "entry_timestamp": item.get("entry_timestamp"),
                    "exit_timestamp": item.get("exit_timestamp"),
                    "holding_minutes": item.get("holding_minutes"),
                    "qty": item.get("qty"),
                    "entry_price": item.get("entry_price"),
                    "exit_price": item.get("exit_price"),
                    "realized_pnl_pct": round(realized_pnl_pct, 3),
                    "won": bool(item.get("won"))
                    if item.get("won") is not None
                    else realized_pnl_pct > 0,
                    "setup_policy_action": _norm(item.get("setup_policy_action")),
                    "setup_label": _norm(item.get("setup_label")),
                    "ml_prediction_bucket": _norm(item.get("ml_prediction_bucket")),
                    "session_trend_label": _norm(item.get("session_trend_label")),
                    "buy_opportunity_recommendation": _norm(
                        item.get("buy_opportunity_recommendation")
                    ),
                    "feedback_source": "historical_matched_trades",
                }
            )
        return matches

    @staticmethod
    def _keys_for_match(match: dict[str, Any]) -> list[str]:
        setup_action = _norm(match.get("setup_policy_action"))
        ml_bucket = _norm(match.get("ml_prediction_bucket"))
        session_label = _norm(match.get("session_trend_label"))
        setup_label = _norm(match.get("setup_label"))
        return [
            f"ml={ml_bucket}|setup_action={setup_action}",
            f"setup_action={setup_action}",
            f"ml={ml_bucket}",
            f"session={session_label}|setup_action={setup_action}",
            f"setup_label={setup_label}",
        ]

    @staticmethod
    def _keys_for_candidate(candidate: dict[str, Any]) -> list[str]:
        setup_action = _norm(
            candidate.get("setup_recommendation") or candidate.get("setup_policy_action")
        )
        ml_bucket = _norm(candidate.get("ml_prediction_bucket"))
        session_label = _norm(candidate.get("session_trend_label"))
        setup_label = _norm(candidate.get("setup_label"))
        return [
            f"ml={ml_bucket}|setup_action={setup_action}",
            f"setup_action={setup_action}",
            f"ml={ml_bucket}",
            f"session={session_label}|setup_action={setup_action}",
            f"setup_label={setup_label}",
        ]

    def build_evidence(
        self,
        target_date: str,
        *,
        include_historical: bool = True,
    ) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        matches = self.same_day_matches(target_date)
        if include_historical:
            matches.extend(self.historical_matches(target_date))

        for match in matches:
            for key in self._keys_for_match(match):
                grouped[key].append(match)

        evidence: dict[str, dict[str, Any]] = {}
        for key, rows in grouped.items():
            pnls = [float(row.get("realized_pnl_pct") or 0) for row in rows]
            losses = [p for p in pnls if p <= 0]
            evidence[key] = {
                "key": key,
                "trades": len(rows),
                "wins": len(rows) - len(losses),
                "losses": len(losses),
                "loss_rate": round(len(losses) / len(rows), 4) if rows else 0.0,
                "avg_pnl_pct": round(sum(pnls) / len(pnls), 4) if pnls else 0.0,
                "min_pnl_pct": round(min(pnls), 4) if pnls else None,
                "max_pnl_pct": round(max(pnls), 4) if pnls else None,
                "symbols": sorted(
                    {str(row.get("symbol") or "") for row in rows if row.get("symbol")}
                ),
                "sources": sorted(
                    {
                        str(row.get("feedback_source") or "unknown")
                        for row in rows
                        if row.get("feedback_source")
                    }
                ),
                "same_day_trades": sum(
                    1 for row in rows if row.get("feedback_source") == "same_day_filled_trades"
                ),
                "historical_trades": sum(
                    1 for row in rows if row.get("feedback_source") == "historical_matched_trades"
                ),
                "historical_lookback_days": self.thresholds.historical_lookback_days,
            }
        return evidence

    def assess_candidate(
        self,
        *,
        target_date: str,
        candidate: dict[str, Any],
        evidence: dict[str, dict[str, Any]] | None = None,
        allow_authority: bool = True,
    ) -> dict[str, Any]:
        evidence = evidence if evidence is not None else self.build_evidence(target_date)
        matches = [evidence[key] for key in self._keys_for_candidate(candidate) if key in evidence]
        thresholds = self.thresholds

        def _specificity(key: str) -> int:
            if key.startswith("ml=") and "|setup_action=" in key:
                return 4
            if key.startswith("session=") and "|setup_action=" in key:
                return 3
            if key.startswith("setup_label="):
                return 3
            return 1

        def _can_block(key: str) -> bool:
            return _specificity(key) >= 3

        def _classify(item: dict[str, Any]) -> str:
            key = str(item.get("key") or "")
            block_qualified = (
                _can_block(key)
                and item["trades"] >= thresholds.block_min_trades
                and item["loss_rate"] >= thresholds.block_loss_rate
                and item["avg_pnl_pct"] <= thresholds.block_avg_pnl_pct
            )
            if block_qualified:
                return "block"
            penalty_qualified = (
                item["trades"] >= thresholds.penalty_min_trades
                and item["loss_rate"] >= thresholds.penalty_loss_rate
                and item["avg_pnl_pct"] <= thresholds.penalty_avg_pnl_pct
            )
            return "penalty" if penalty_qualified else "neutral"

        status_rank = {"block": 3, "penalty": 2, "neutral": 1}
        best = None
        best_status = "neutral"
        for item in matches:
            item_status = _classify(item)
            item_rank = (
                status_rank[item_status],
                _specificity(str(item.get("key") or "")),
                item["trades"],
                item["loss_rate"],
                -item["avg_pnl_pct"],
            )
            best_rank = (
                status_rank[best_status],
                _specificity(str((best or {}).get("key") or "")),
                (best or {}).get("trades") or 0,
                (best or {}).get("loss_rate") or 0,
                -((best or {}).get("avg_pnl_pct") or 0),
            )
            if best is None or item_rank > best_rank:
                best = item
                best_status = item_status

        base = {
            "version": INTRADAY_TRADE_FEEDBACK_VERSION,
            "target_date": target_date,
            "status": "neutral",
            "runtime_effect": "observe_only_no_intraday_pattern_authority",
            "score_penalty": 0.0,
            "hard_block_reason": None,
            "feedback_key": best.get("key") if best else None,
            "evidence": best or {},
            "candidate_keys": self._keys_for_candidate(candidate),
        }
        if not best:
            return base

        if best_status == "block":
            base["status"] = "block" if allow_authority else "would_block"
            base["score_penalty"] = thresholds.penalty_score
            base["hard_block_reason"] = (
                "intraday_pattern_feedback:"
                f"{best['key']}:loss_rate={best['loss_rate']:.2f}:"
                f"avg_pnl={best['avg_pnl_pct']:.3f}%:"
                f"trades={best['trades']}:"
                f"sources={','.join(best.get('sources') or [])}"
            )
            base["runtime_effect"] = (
                "paper_intraday_pattern_block"
                if allow_authority
                else "observe_only_cash_mode_no_authority"
            )
        elif best_status == "penalty":
            base["status"] = "penalty" if allow_authority else "would_penalize"
            base["score_penalty"] = thresholds.penalty_score
            base["runtime_effect"] = (
                "paper_intraday_pattern_penalty"
                if allow_authority
                else "observe_only_cash_mode_no_authority"
            )

        return base


def build_default_intraday_trade_feedback_service(db_path=None) -> IntradayTradeFeedbackService:
    return IntradayTradeFeedbackService(db_path=db_path)
