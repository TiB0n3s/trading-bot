"""External observability readiness inventory.

This does not publish metrics or alerts. It checks whether the repo/runtime has
enough external observability configuration to move beyond local diagnostics.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any


def _configured(env: dict[str, str], *names: str) -> bool:
    return any(bool(str(env.get(name) or "").strip()) for name in names)


def build_external_observability_readiness_payload(
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if env is None else env)
    prometheus_client_present = importlib.util.find_spec("prometheus_client") is not None
    categories = [
        {
            "name": "metrics_export",
            "configured": prometheus_client_present
            and _configured(env, "PROMETHEUS_PUSHGATEWAY_URL", "PROMETHEUS_GATEWAY_URL"),
            "missing": [
                item
                for item, present in {
                    "prometheus_client": prometheus_client_present,
                    "PROMETHEUS_PUSHGATEWAY_URL": _configured(
                        env, "PROMETHEUS_PUSHGATEWAY_URL", "PROMETHEUS_GATEWAY_URL"
                    ),
                }.items()
                if not present
            ],
            "next_action": "install/configure prometheus_client and Pushgateway or collector endpoint",
        },
        {
            "name": "alert_delivery",
            "configured": _configured(
                env, "ALERT_WEBHOOK_URL", "SLACK_WEBHOOK_URL", "PAGERDUTY_ROUTING_KEY"
            ),
            "missing": ["ALERT_WEBHOOK_URL or SLACK_WEBHOOK_URL or PAGERDUTY_ROUTING_KEY"]
            if not _configured(
                env, "ALERT_WEBHOOK_URL", "SLACK_WEBHOOK_URL", "PAGERDUTY_ROUTING_KEY"
            )
            else [],
            "next_action": "configure one external alert destination for critical runtime findings",
        },
        {
            "name": "dashboard_target",
            "configured": _configured(env, "GRAFANA_URL", "OBSERVABILITY_DASHBOARD_URL"),
            "missing": ["GRAFANA_URL or OBSERVABILITY_DASHBOARD_URL"]
            if not _configured(env, "GRAFANA_URL", "OBSERVABILITY_DASHBOARD_URL")
            else [],
            "next_action": "configure dashboard URL for operator runbooks",
        },
    ]
    configured_count = sum(1 for row in categories if row["configured"])
    return {
        "report_version": "external_observability_readiness_v1",
        "runtime_effect": "readiness_only_no_network_calls",
        "configured_count": configured_count,
        "total_count": len(categories),
        "ready": configured_count == len(categories),
        "categories": categories,
    }
