"""Compare ML-supported auto-buy candidates that were taken vs skipped."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from repositories.reporting_repo import ReportingRepository


@dataclass(frozen=True)
class MlSupportedBuyOutcomeConfig:
    min_score: float = 14.0
    decisions: frozenset[str] = frozenset({"strong_buy_candidate", "buy_candidate", "watch"})
    forward_minutes: tuple[int, ...] = (15, 60)


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _pct(current: float | None, base: float | None) -> float | None:
    if current is None or base in (None, 0):
        return None
    return round((float(current) - float(base)) / float(base) * 100.0, 4)


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except Exception:
        return default


class MlSupportedBuyOutcomeService:
    def __init__(
        self,
        repository: ReportingRepository | None = None,
        config: MlSupportedBuyOutcomeConfig | None = None,
    ):
        self.repository = repository or ReportingRepository()
        self.config = config or MlSupportedBuyOutcomeConfig()

    def _candidate_supported(self, row: Any) -> bool:
        decision = str(row["decision"] or "").strip()
        score = _float(row["score"])
        return (
            decision in self.config.decisions
            and score is not None
            and score >= self.config.min_score
        )

    def report(self, target_date: str) -> dict[str, Any]:
        rows = [
            row
            for row in self.repository.auto_buy_candidate_rows(target_date)
            if self._candidate_supported(row)
        ]
        details: list[dict[str, Any]] = []

        for row in rows:
            symbol = row["symbol"]
            timestamp = row["timestamp"]
            reference_price, reference_ts = self.repository.feature_price_at_or_before(
                symbol, timestamp
            )

            forward: dict[str, Any] = {}
            for minutes in self.config.forward_minutes:
                price, price_ts = self.repository.feature_price_at_or_after(
                    symbol,
                    timestamp,
                    minutes,
                )
                forward[f"price_{minutes}m"] = price
                forward[f"price_{minutes}m_ts"] = price_ts
                forward[f"return_{minutes}m_pct"] = _pct(price, reference_price)

            status = "taken" if int(row["order_submitted"] or 0) == 1 else "skipped"
            details.append(
                {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "status": status,
                    "decision": row["decision"],
                    "score": _float(row["score"]),
                    "reason": _row_get(row, "reason"),
                    "hard_block_reason": _row_get(row, "hard_block_reason"),
                    "reference_price": reference_price,
                    "reference_ts": reference_ts,
                    **forward,
                }
            )

        by_status: dict[str, dict[str, Any]] = {}
        for item in details:
            status = item["status"]
            bucket = by_status.setdefault(
                status,
                {"rows": 0, "avg_return_15m_pct": None, "avg_return_60m_pct": None},
            )
            bucket["rows"] += 1

        for status, bucket in by_status.items():
            status_rows = [item for item in details if item["status"] == status]
            for minutes in self.config.forward_minutes:
                values = [
                    item.get(f"return_{minutes}m_pct")
                    for item in status_rows
                    if item.get(f"return_{minutes}m_pct") is not None
                ]
                bucket[f"avg_return_{minutes}m_pct"] = (
                    round(sum(values) / len(values), 4) if values else None
                )

        return {
            "report_version": "ml_supported_buy_outcomes_v1",
            "runtime_effect": "learning_report_no_live_authority",
            "date": target_date,
            "min_score": self.config.min_score,
            "rows": len(details),
            "taken_rows": by_status.get("taken", {}).get("rows", 0),
            "skipped_rows": by_status.get("skipped", {}).get("rows", 0),
            "by_status": by_status,
            "candidates": sorted(
                details,
                key=lambda item: (item["score"] or 0.0, item["timestamp"]),
                reverse=True,
            ),
        }
