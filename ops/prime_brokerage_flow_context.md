# Prime Brokerage Flow Context

`runtime_state/prime_brokerage_flows.json` stores external prime-brokerage /
hedge-fund flow context. This is the single-stock and sector-positioning analog
to CFTC COT, but it is vendor/source dependent and must be treated as external
context rather than native execution truth.

## Authority

- Runtime effect: `external_prime_brokerage_positioning_context_no_trade_authority`
- Allowed use: ML feature, meta-label feature, sector rotation filter,
  crowded-short context, size-down modifier, reporting
- Disallowed use: standalone trade approval, broker order routing authority,
  override of risk lockout or execution-quality gates

## Input Contract

Normalize a locally supplied JSON payload:

```bash
./venv/bin/python scripts/prime_brokerage_flows_update.py \
  --input data/prime_brokerage/latest_flows.json \
  --output runtime_state/prime_brokerage_flows.json
```

Example:

```json
{
  "source": "approved_external_prime_brokerage_summary",
  "sectors": {
    "technology": {
      "as_of_date": "2026-06-10",
      "published_at": "2026-06-10T06:00:00-04:00",
      "net_flow_percentile_1y": 8,
      "long_inflows_5d": 10,
      "short_outflows_5d": 60,
      "gross_leverage_change_5d": -1
    }
  },
  "symbols": {
    "NVDA": {
      "as_of_date": "2026-06-10",
      "published_at": "2026-06-10T06:00:00-04:00",
      "net_flow_percentile_1y": 93,
      "short_exposure": 20000000,
      "free_float": 100000000
    }
  }
}
```

Derived fields:

- `net_flow_momentum_5d`
- `crowding_score`
- `is_crowded_short`
- `degrossing_indicator`
- `pb_flow_regime`
- `pb_size_modifier`

## No-Lookahead Rule

Records with future `published_at` / `effective_at` timestamps are retained in
top-level diagnostics but are not attached to per-symbol context. Missing or
stale files degrade to unavailable context rather than blocking market-context
generation.

## Symbol Mapping

Explicit symbol records override sector records. When no symbol record exists,
the bot maps the symbol to a broad sector from `symbols_config.py` clusters:

- technology/software/semiconductors/AI infrastructure:
  `information_technology`
- defense/aerospace/industrials/power: `industrials`
- critical materials/rare earths/copper/lithium: `materials`
- payments/financials: `financials`
- healthcare: `healthcare`
- energy: `energy`

Per-symbol PB context is written to
`market_context.json -> symbols.<SYMBOL>.prime_brokerage_context`. Top-level
state is written as `prime_brokerage_context`.

