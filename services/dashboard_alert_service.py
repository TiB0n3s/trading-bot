"""External dashboard alert payload builders."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


DASHBOARD_ALERT_VERSION = "dashboard_alert_v1"


@dataclass(frozen=True)
class DashboardAlert:
    version: str
    channel: str
    title: str
    markdown: str
    payload: dict[str, Any]
    runtime_effect: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_earnings_dashboard_alert(
    *,
    symbol: str,
    sentiment: dict[str, Any],
    earnings_contract: dict[str, Any],
) -> DashboardAlert:
    title = f"{symbol.upper()} earnings AI alert"
    markdown = (
        f"**{title}**\n"
        f"- sentiment: {sentiment.get('label')} ({sentiment.get('score')})\n"
        f"- model: {sentiment.get('model_provider')}\n"
        f"- peer watchlist: {', '.join(earnings_contract.get('peer_watchlist') or [])}\n"
        f"- runtime: research alert only"
    )
    return DashboardAlert(
        version=DASHBOARD_ALERT_VERSION,
        channel="earnings-ai-alerts",
        title=title,
        markdown=markdown,
        payload={
            "symbol": symbol.upper(),
            "sentiment": sentiment,
            "earnings_contract": earnings_contract,
        },
        runtime_effect="payload_only_no_external_post",
    )
