# Dealer Gamma Context

`runtime_state/dealer_gamma.json` stores per-symbol options dealer gamma
context. It is derived from options-chain data such as open interest, gamma,
spot price, gamma flip, and peak gamma strikes.

## Authority

- Runtime effect: `options_dealer_gamma_context_no_trade_authority`
- Allowed use: volatility-regime feature, meta-label feature, strategy-family
  weighting, dynamic stop-level evidence, size-down modifier, reporting
- Disallowed use: standalone trade approval, order-routing authority, override
  of risk lockout or execution-quality gates

## Normalization

```bash
./venv/bin/python scripts/dealer_gamma_update.py \
  --input data/dealer_gamma/latest_gamma.json \
  --output runtime_state/dealer_gamma.json
```

Input shape:

```json
{
  "source": "options_chain_gamma_estimate",
  "symbols": {
    "NVDA": {
      "as_of_date": "2026-06-10",
      "published_at": "2026-06-10T06:00:00-04:00",
      "spot_price": 100,
      "gamma_flip_zone": 99.8,
      "options": [
        {"option_type": "call", "open_interest": 100, "gamma": 0.02},
        {"option_type": "put", "open_interest": 50, "gamma": 0.02}
      ],
      "absolute_gamma_peak_levels": [
        {"strike": 95, "net_gex": 5000, "open_interest": 1000}
      ]
    }
  }
}
```

Derived fields:

- `total_net_gex`
- `gex_regime`
- `gamma_flip_zone`
- `distance_to_gamma_flip_pct`
- `nearest_positive_gamma_floor`
- `nearest_positive_gamma_ceiling`
- `gamma_size_modifier`
- `strategy_bias`

## GEX Approximation

For each option row:

```text
Call GEX = open_interest * gamma * spot_price^2 * 0.01
Put GEX  = open_interest * gamma * spot_price^2 * 0.01 * -1
```

This is an approximation that assumes public customers are net buyers and
dealers are net liquidity providers.

## Interpretation

- Positive gamma: volatility-dampening context. Mean reversion is preferred;
  aggressive breakout signals should be reviewed or size-reduced.
- Negative gamma: volatility-accelerating context. Momentum and breakout
  strategies have more supportive structural volatility context.
- Near gamma flip: expected chop/instability. The context applies a conservative
  size modifier.

## No-Lookahead Rule

Records with future `published_at` / `effective_at` timestamps are retained in
top-level diagnostics but are not attached to per-symbol context.

