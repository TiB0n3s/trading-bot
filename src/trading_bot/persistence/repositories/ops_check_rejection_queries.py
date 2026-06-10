from __future__ import annotations

import sqlite3


class OpsCheckRejectionQueriesMixin:
    def rejection_total_count(self, target_date: str) -> int:
        row = self._fetchone(
            """
            SELECT COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
            """,
            (target_date,),
        )
        return int(row["n"] or 0) if row else 0

    def rejection_approved_count(self, target_date: str) -> int:
        row = self._fetchone(
            """
            SELECT COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND approved = 1
            """,
            (target_date,),
        )
        return int(row["n"] or 0) if row else 0

    def rejection_rejected_count(self, target_date: str) -> int:
        row = self._fetchone(
            """
            SELECT COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND COALESCE(approved, 0) = 0
            """,
            (target_date,),
        )
        return int(row["n"] or 0) if row else 0

    def rejection_action_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT COALESCE(action, 'missing') AS action,
                   COALESCE(approved, 0) AS approved,
                   COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY COALESCE(action, 'missing'), COALESCE(approved, 0)
            ORDER BY action, approved DESC
            """,
            (target_date,),
        )

    def rejection_reason_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT rejection_reason, COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND COALESCE(approved, 0) = 0
            GROUP BY rejection_reason
            ORDER BY n DESC, rejection_reason
            """,
            (target_date,),
        )

    def rejected_symbol_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT COALESCE(symbol, 'missing') AS symbol, COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND COALESCE(approved, 0) = 0
            GROUP BY COALESCE(symbol, 'missing')
            ORDER BY n DESC, symbol
            LIMIT 15
            """,
            (target_date,),
        )

    def recent_rejected_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT timestamp, symbol, action, rejection_reason, confidence,
                   prediction_score, prediction_decision, setup_label,
                   buy_opportunity_score, buy_opportunity_recommendation
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND COALESCE(approved, 0) = 0
            ORDER BY timestamp DESC, id DESC
            LIMIT 12
            """,
            (target_date,),
        )

    def rejected_outcome_rejected_counts(self, target_date: str) -> sqlite3.Row | None:
        return self._fetchone(
            """
            SELECT
                COUNT(*) AS n,
                SUM(CASE WHEN LOWER(action) = 'buy' THEN 1 ELSE 0 END) AS buy_n,
                SUM(CASE WHEN LOWER(action) = 'sell' THEN 1 ELSE 0 END) AS sell_n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND approved = 0
              AND symbol IS NOT NULL
              AND action IS NOT NULL
              AND signal_price IS NOT NULL
              AND LOWER(action) IN ('buy', 'sell')
            """,
            (target_date,),
        )

    def rejected_outcome_status_counts(self, target_date: str) -> sqlite3.Row | None:
        return self._fetchone(
            """
            SELECT
                COUNT(*) AS n,
                SUM(CASE WHEN label_status = 'labeled' THEN 1 ELSE 0 END) AS labeled,
                SUM(CASE WHEN label_status = 'partial' THEN 1 ELSE 0 END) AS partial,
                SUM(CASE WHEN label_status = 'pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN label_status = 'no_bars' THEN 1 ELSE 0 END) AS no_bars,
                SUM(CASE WHEN label_status = 'error' THEN 1 ELSE 0 END) AS error
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
            """,
            (target_date,),
        )

    def rejected_outcome_partial_reason_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT COALESCE(partial_reason, 'unspecified') AS partial_reason,
                   COUNT(*) AS n
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
              AND label_status IN ('partial', 'pending', 'no_bars')
            GROUP BY COALESCE(partial_reason, 'unspecified')
            ORDER BY n DESC, partial_reason
            """,
            (target_date,),
        )

    def rejected_outcome_horizon_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                label_status,
                COUNT(*) AS n,
                SUM(CASE WHEN return_5m IS NOT NULL THEN 1 ELSE 0 END) AS has_5m,
                SUM(CASE WHEN return_15m IS NOT NULL THEN 1 ELSE 0 END) AS has_15m,
                SUM(CASE WHEN return_30m IS NOT NULL THEN 1 ELSE 0 END) AS has_30m,
                SUM(CASE WHEN return_60m IS NOT NULL THEN 1 ELSE 0 END) AS has_60m,
                SUM(CASE WHEN return_eod IS NOT NULL THEN 1 ELSE 0 END) AS has_eod,
                SUM(CASE WHEN max_favorable_60m IS NOT NULL THEN 1 ELSE 0 END) AS has_mfe,
                SUM(CASE WHEN max_adverse_60m IS NOT NULL THEN 1 ELSE 0 END) AS has_mae
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY label_status
            ORDER BY label_status
            """,
            (target_date,),
        )

    def rejected_outcome_action_status_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT action, label_status, COUNT(*) AS n,
                   AVG(return_15m) AS avg_return_15m,
                   AVG(return_60m) AS avg_return_60m,
                   AVG(return_eod) AS avg_return_eod
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY action, label_status
            ORDER BY action, label_status
            """,
            (target_date,),
        )

    def rejected_outcome_invalid_labeled_count(self, target_date: str) -> int:
        row = self._fetchone(
            """
            SELECT COUNT(*) AS n
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
              AND label_status = 'labeled'
              AND (
                   return_5m IS NULL
                OR return_15m IS NULL
                OR return_30m IS NULL
                OR return_60m IS NULL
                OR return_eod IS NULL
                OR max_favorable_60m IS NULL
                OR max_adverse_60m IS NULL
              )
            """,
            (target_date,),
        )
        return int(row["n"] or 0) if row else 0

    def rejected_outcome_bad_excursion_count(self, target_date: str) -> int:
        row = self._fetchone(
            """
            SELECT COUNT(*) AS n
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
              AND label_status IN ('labeled', 'partial')
              AND (
                   max_favorable_60m < -0.000001
                OR max_adverse_60m > 0.000001
              )
            """,
            (target_date,),
        )
        return int(row["n"] or 0) if row else 0

    def rejected_outcome_partial_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT trade_id, timestamp, partial_reason, return_60m
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
              AND label_status = 'partial'
            """,
            (target_date,),
        )

    def rejected_outcome_category_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                CASE
                  WHEN instr(rejection_reason, ':') > 0
                    THEN substr(rejection_reason, 1, instr(rejection_reason, ':') - 1)
                  ELSE COALESCE(rejection_reason, 'unknown')
                END AS category,
                COUNT(*) AS n,
                AVG(return_15m) AS avg_return_15m,
                AVG(max_favorable_60m) AS avg_mfe_60m
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY category
            ORDER BY n DESC, category
            LIMIT 12
            """,
            (target_date,),
        )
