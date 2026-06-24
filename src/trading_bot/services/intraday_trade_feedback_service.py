"""Trade-quality feedback for active auto-buy learning.

This service combines same-day filled trades with prior-session matched-trade
outcomes. The same-day path reacts intraday; the historical path keeps repeated
mistakes from being forgotten after the session rolls over.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from repositories import auto_buy_repo

INTRADAY_TRADE_FEEDBACK_VERSION = "intraday_trade_feedback_v2"
INTRADAY_LEARNING_SNAPSHOT_VERSION = "intraday_learning_snapshot_v1"


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
    block_min_trades: int = 5
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

    def _group_matches(self, matches: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
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

    def _load_materialized_historical_evidence(self, target_date: str) -> dict[str, dict[str, Any]]:
        rows = auto_buy_repo.historical_outcome_feedback_rows(
            target_date,
            lookback_days=self.thresholds.historical_lookback_days,
            db_path=self.db_path or auto_buy_repo.DB_PATH,
        )
        evidence: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            raw = item.get("evidence_json")
            loaded = None
            if raw:
                try:
                    loaded = json.loads(str(raw))
                except Exception:
                    loaded = None
            if not isinstance(loaded, dict):
                loaded = {
                    "key": item.get("feedback_key"),
                    "trades": item.get("trades"),
                    "wins": item.get("wins"),
                    "losses": item.get("losses"),
                    "loss_rate": item.get("loss_rate"),
                    "avg_pnl_pct": item.get("avg_pnl_pct"),
                    "min_pnl_pct": item.get("min_pnl_pct"),
                    "max_pnl_pct": item.get("max_pnl_pct"),
                    "symbols": [],
                    "sources": ["materialized_historical_outcomes"],
                    "same_day_trades": 0,
                    "historical_trades": item.get("trades"),
                    "historical_lookback_days": item.get("lookback_days"),
                }
            loaded["feedback_source"] = "materialized_historical_outcomes"
            loaded["historical_materialized"] = True
            loaded["same_day_trades"] = 0
            loaded["historical_trades"] = int(loaded.get("historical_trades") or 0)
            evidence[str(loaded.get("key") or item.get("feedback_key"))] = loaded
        return evidence

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
        evidence = self._group_matches(self.same_day_matches(target_date))
        if include_historical:
            historical = self._load_materialized_historical_evidence(target_date)
            if not historical:
                historical = self._group_matches(self.historical_matches(target_date))
            for key, item in historical.items():
                if key not in evidence:
                    evidence[key] = item
                    continue
                combined = evidence[key]
                trades = int(combined.get("trades") or 0) + int(item.get("trades") or 0)
                losses = int(combined.get("losses") or 0) + int(item.get("losses") or 0)
                wins = int(combined.get("wins") or 0) + int(item.get("wins") or 0)
                combined["trades"] = trades
                combined["wins"] = wins
                combined["losses"] = losses
                combined["loss_rate"] = round(losses / trades, 4) if trades else 0.0
                if trades:
                    same_total = float(combined.get("avg_pnl_pct") or 0) * int(
                        combined.get("same_day_trades") or 0
                    )
                    hist_total = float(item.get("avg_pnl_pct") or 0) * int(
                        item.get("historical_trades") or item.get("trades") or 0
                    )
                    combined["avg_pnl_pct"] = round((same_total + hist_total) / trades, 4)
                mins = [
                    value
                    for value in (combined.get("min_pnl_pct"), item.get("min_pnl_pct"))
                    if value is not None
                ]
                maxes = [
                    value
                    for value in (combined.get("max_pnl_pct"), item.get("max_pnl_pct"))
                    if value is not None
                ]
                combined["min_pnl_pct"] = round(min(float(v) for v in mins), 4) if mins else None
                combined["max_pnl_pct"] = round(max(float(v) for v in maxes), 4) if maxes else None
                combined["symbols"] = sorted(
                    set(combined.get("symbols") or []) | set(item.get("symbols") or [])
                )
                combined["sources"] = sorted(
                    set(combined.get("sources") or []) | set(item.get("sources") or [])
                )
                combined["historical_trades"] = int(combined.get("historical_trades") or 0) + int(
                    item.get("historical_trades") or item.get("trades") or 0
                )
                combined["historical_materialized"] = bool(
                    combined.get("historical_materialized") or item.get("historical_materialized")
                )

        return evidence

    def refresh_historical_outcome_feedback(
        self,
        target_date: str,
        *,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        created_at = created_at or datetime.now(timezone.utc).isoformat()
        raw_evidence = self._group_matches(self.historical_matches(target_date))
        rows = []
        for item in raw_evidence.values():
            rows.append(
                {
                    **item,
                    "status": self._classify_evidence_item(item),
                    "runtime_effect": "paper_historical_outcome_feedback_materialized",
                }
            )
        rows.sort(
            key=lambda item: (
                {"block": 3, "penalty": 2, "neutral": 1}.get(item["status"], 0),
                item.get("trades") or 0,
                item.get("loss_rate") or 0,
            ),
            reverse=True,
        )
        persisted = auto_buy_repo.replace_historical_outcome_feedback(
            created_at=created_at,
            target_date=target_date,
            lookback_days=self.thresholds.historical_lookback_days,
            evidence_rows=rows,
            db_path=self.db_path or auto_buy_repo.DB_PATH,
        )
        return {
            "version": "historical_outcome_feedback_refresh_v1",
            "created_at": created_at,
            "target_date": target_date,
            "lookback_days": self.thresholds.historical_lookback_days,
            "matched_trade_rows": len(self.historical_matches(target_date)),
            "evidence_rows": len(rows),
            "persisted_rows": persisted,
            "status_counts": {
                "block": sum(1 for row in rows if row["status"] == "block"),
                "penalty": sum(1 for row in rows if row["status"] == "penalty"),
                "neutral": sum(1 for row in rows if row["status"] == "neutral"),
            },
            "runtime_effect": "paper_historical_outcome_feedback_materialized",
            "top_feedback": rows[:10],
        }

    def _classify_evidence_item(self, item: dict[str, Any]) -> str:
        thresholds = self.thresholds
        key = str(item.get("key") or "")

        def _specificity(candidate_key: str) -> int:
            if candidate_key.startswith("ml=") and "|setup_action=" in candidate_key:
                return 4
            if candidate_key.startswith("session=") and "|setup_action=" in candidate_key:
                return 3
            if candidate_key.startswith("setup_label="):
                return 3
            return 1

        block_qualified = (
            _specificity(key) >= 3
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

    @staticmethod
    def _execution_friction_memory(matches: list[dict[str, Any]]) -> dict[str, Any]:
        short_holds = []
        for row in matches:
            try:
                hold = float(row.get("holding_minutes"))
                pnl = float(row.get("realized_pnl_pct") or 0)
            except (TypeError, ValueError):
                continue
            if hold <= 5.0:
                short_holds.append((hold, pnl))
        short_losses = [item for item in short_holds if item[1] <= 0]
        loss_rate = len(short_losses) / len(short_holds) if short_holds else None
        avg_pnl = sum(item[1] for item in short_holds) / len(short_holds) if short_holds else None
        status = "insufficient_data"
        decision = "pass"
        size_multiplier = 1.0
        if short_holds:
            status = "stable"
            if len(short_holds) >= 3 and loss_rate is not None and loss_rate >= 0.67:
                status = "short_hold_friction_pressure"
                decision = "size_down"
                size_multiplier = 0.75
        return {
            "version": "execution_friction_memory_v1",
            "runtime_effect": "paper_execution_friction_feedback_no_order_authority",
            "status": status,
            "decision": decision,
            "size_multiplier": size_multiplier,
            "short_hold_minutes_threshold": 5.0,
            "short_hold_closed_trades": len(short_holds),
            "short_hold_losses": len(short_losses),
            "short_hold_loss_rate": round(loss_rate, 4) if loss_rate is not None else None,
            "short_hold_avg_pnl_pct": round(avg_pnl, 4) if avg_pnl is not None else None,
            "reason": (
                "short-hold losses indicate execution/exit friction pressure"
                if decision == "size_down"
                else "short-hold execution friction below action threshold"
            ),
        }

    def performance_snapshot(
        self,
        target_date: str,
        *,
        phase: str,
        trigger_symbol: str | None = None,
        include_historical: bool = True,
    ) -> dict[str, Any]:
        same_day_matches = self.same_day_matches(target_date)
        evidence = self.build_evidence(target_date, include_historical=include_historical)
        classified = []
        for item in evidence.values():
            classified.append({**item, "status": self._classify_evidence_item(item)})
        classified.sort(
            key=lambda item: (
                {"block": 3, "penalty": 2, "neutral": 1}.get(item["status"], 0),
                item.get("trades") or 0,
                item.get("loss_rate") or 0,
                -float(item.get("avg_pnl_pct") or 0),
            ),
            reverse=True,
        )

        pnls = [float(row.get("realized_pnl_pct") or 0) for row in same_day_matches]
        losses = [pnl for pnl in pnls if pnl <= 0]
        execution_friction = self._execution_friction_memory(same_day_matches)
        status_counts: dict[str, int] = {"block": 0, "penalty": 0, "neutral": 0}
        for item in classified:
            status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1

        worst_status = "neutral"
        if status_counts.get("block"):
            worst_status = "block"
        elif status_counts.get("penalty"):
            worst_status = "penalty"

        return {
            "version": INTRADAY_LEARNING_SNAPSHOT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "target_date": target_date,
            "phase": phase,
            "trigger_symbol": trigger_symbol.upper() if trigger_symbol else None,
            "runtime_effect": "paper_intraday_learning_feedback",
            "status": worst_status,
            "same_day_closed_trades": len(same_day_matches),
            "same_day_wins": len(pnls) - len(losses),
            "same_day_losses": len(losses),
            "same_day_win_rate": round((len(pnls) - len(losses)) / len(pnls), 4) if pnls else None,
            "same_day_avg_pnl_pct": round(sum(pnls) / len(pnls), 4) if pnls else None,
            "same_day_min_pnl_pct": round(min(pnls), 4) if pnls else None,
            "same_day_max_pnl_pct": round(max(pnls), 4) if pnls else None,
            "execution_friction_memory": execution_friction,
            "evidence_keys": len(evidence),
            "status_counts": status_counts,
            "top_feedback": classified[:10],
        }

    def capture_performance_snapshot(
        self,
        target_date: str,
        *,
        phase: str,
        trigger_symbol: str | None = None,
        include_historical: bool = True,
    ) -> dict[str, Any]:
        auto_buy_repo.init_tables(db_path=self.db_path or auto_buy_repo.DB_PATH)
        snapshot = self.performance_snapshot(
            target_date,
            phase=phase,
            trigger_symbol=trigger_symbol,
            include_historical=include_historical,
        )
        status = str(snapshot.get("status") or "neutral")
        top_feedback = snapshot.get("top_feedback") or []
        feedback_key = f"intraday_performance_snapshot:{phase}"
        if top_feedback:
            feedback_key = f"{feedback_key}:{top_feedback[0].get('key') or 'unknown'}"
        hard_block_reason = None
        if status == "block" and top_feedback:
            item = top_feedback[0]
            hard_block_reason = (
                "intraday_learning_snapshot:"
                f"{item.get('key')}:loss_rate={item.get('loss_rate')}:"
                f"avg_pnl={item.get('avg_pnl_pct')}%:trades={item.get('trades')}"
            )

        auto_buy_repo.insert_intraday_feedback_event(
            created_at=str(snapshot["created_at"]),
            target_date=target_date,
            symbol=trigger_symbol.upper() if trigger_symbol else None,
            feedback_key=feedback_key,
            status=status,
            score_penalty=self.thresholds.penalty_score if status in {"block", "penalty"} else 0.0,
            hard_block_reason=hard_block_reason,
            evidence_json=json.dumps(snapshot, sort_keys=True),
            candidate_json=json.dumps(
                {
                    "phase": phase,
                    "trigger_symbol": trigger_symbol.upper() if trigger_symbol else None,
                    "source": "intraday_learning_snapshot",
                },
                sort_keys=True,
            ),
            runtime_effect="paper_intraday_learning_feedback",
            db_path=self.db_path or auto_buy_repo.DB_PATH,
        )
        return snapshot

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

        status_rank = {"block": 3, "penalty": 2, "neutral": 1}
        best = None
        best_status = "neutral"
        for item in matches:
            item_status = self._classify_evidence_item(item)
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
            base["score_penalty"] = self.thresholds.penalty_score
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
            base["score_penalty"] = self.thresholds.penalty_score
            base["runtime_effect"] = (
                "paper_intraday_pattern_penalty"
                if allow_authority
                else "observe_only_cash_mode_no_authority"
            )

        return base


def build_default_intraday_trade_feedback_service(db_path=None) -> IntradayTradeFeedbackService:
    return IntradayTradeFeedbackService(db_path=db_path)
