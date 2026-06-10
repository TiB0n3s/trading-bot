"""Bot event audit logging service."""

from __future__ import annotations

import json
from datetime import datetime

import pytz
from repositories.bot_events_repo import BotEventsRepository

ET = pytz.timezone("America/New_York")


def now_s() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S")


class BotEventsService:
    def __init__(self, repository: BotEventsRepository):
        self.repository = repository

    def init_table(self) -> None:
        self.repository.init_table()

    def log_event(
        self,
        event_type,
        symbol=None,
        action=None,
        decision=None,
        severity=None,
        reason=None,
        source=None,
        payload=None,
    ) -> bool:
        """Insert one event into bot_events. Fail-open."""
        try:
            self.repository.init_table()

            payload_json = None
            if payload is not None:
                try:
                    payload_json = json.dumps(payload, sort_keys=True, default=str)
                except Exception:
                    payload_json = json.dumps({"unserializable_payload": str(payload)})

            self.repository.insert_event(
                {
                    "timestamp": now_s(),
                    "event_type": event_type,
                    "symbol": symbol,
                    "action": action,
                    "decision": decision,
                    "severity": severity,
                    "reason": reason,
                    "source": source,
                    "payload_json": payload_json,
                }
            )
            return True
        except Exception:
            return False

    def fetch_events(self, limit=50, event_type=None, symbol=None, since=None):
        self.repository.init_table()
        return self.repository.fetch_events(
            limit=limit,
            event_type=event_type,
            symbol=symbol,
            since=since,
        )


def build_default_bot_events_service() -> BotEventsService:
    return BotEventsService(BotEventsRepository())
