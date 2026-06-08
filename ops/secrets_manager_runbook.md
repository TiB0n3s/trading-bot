# Secrets Manager Runbook

Runtime effect: documentation only.

The current production source is `/etc/trading-bot.env`. This remains acceptable
for paper trading when file permissions pass `ops_check.py secrets-hygiene`.

## Readiness Check

```bash
python3 ops_check.py secrets-manager-readiness
```

The check does not read secrets and does not make network calls. It verifies
provider metadata only.

## Supported Metadata

Vault:

- `SECRET_MANAGER_PROVIDER=vault`
- `VAULT_ADDR`
- `VAULT_TOKEN`

AWS Secrets Manager:

- `SECRET_MANAGER_PROVIDER=aws`
- `AWS_REGION`
- `TRADING_BOT_SECRET_ID`

GCP Secret Manager:

- `SECRET_MANAGER_PROVIDER=gcp`
- `GOOGLE_CLOUD_PROJECT`
- `TRADING_BOT_SECRET_ID`

Azure Key Vault:

- `SECRET_MANAGER_PROVIDER=azure`
- `AZURE_KEY_VAULT_URL`

## Promotion Rule

Before cash-live use, validate retrieval in a dry-run wrapper and keep secrets
out of source files, Docker images, systemd unit files, and README examples.
