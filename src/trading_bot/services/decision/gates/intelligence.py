"""Intelligence adjudication gate facade."""

from typing import Any

from src.trading_bot.intelligence.adjudicator import ModelAdjudication, build_model_adjudication


def build_intelligence_adjudication(
    *,
    account_state: dict[str, Any],
    intelligence_context: dict[str, Any] | None = None,
) -> ModelAdjudication:
    return build_model_adjudication(
        account_state=account_state,
        intelligence_context=intelligence_context,
    )
