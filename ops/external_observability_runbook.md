# External Observability Runbook

Runtime effect: documentation only.

Use this after local diagnostics are stable and before any cash-live promotion.

## Readiness Check

```bash
python3 ops_check.py external-observability-readiness
```

The check does not make network calls. It verifies metadata for:

- Metrics export endpoint, such as Prometheus Pushgateway or collector URL.
- External alert destination, such as Slack webhook or PagerDuty routing key.
- Dashboard URL, such as Grafana.

## Required Configuration

At least one value in each group should be configured outside the repo:

- `PROMETHEUS_PUSHGATEWAY_URL` or `PROMETHEUS_GATEWAY_URL`
- `ALERT_WEBHOOK_URL`, `SLACK_WEBHOOK_URL`, or `PAGERDUTY_ROUTING_KEY`
- `GRAFANA_URL` or `OBSERVABILITY_DASHBOARD_URL`

## Promotion Rule

Local `ops_check.py observability-health` remains the source of truth for what
should be exported. External publishing should mirror those fields first:

- job ledger cleanliness
- database backup freshness
- service watchdog warnings
- model staleness guard
- order latency and broker errors once collector support is added

Do not add external alerting directly to order execution paths.
