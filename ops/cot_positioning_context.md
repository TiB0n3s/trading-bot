# CFTC COT Positioning Context

`runtime_state/cot_positioning.json` stores weekly CFTC Commitments of Traders
context for macro positioning. This is used as ML/context and sizing evidence,
not standalone trade authority.

## Authority

- Runtime effect: `weekly_macro_positioning_context_no_intraday_trade_authority`
- Allowed use: macro context, meta-label feature, size-down modifier, reporting
- Disallowed use: standalone buy/sell approval, intraday momentum trigger

Existing execution-quality, affordability, risk-lockout, duplicate-order, and
authority gates remain superior.

## Timing Contract

COT is published weekly and reflects delayed positions. Do not treat it as live
flow.

- Financial futures COT is the relevant report for equity-index positioning.
- The bot should forward-fill only the latest published record.
- Never apply a record before its `published_at` timestamp.
- If the file is missing or stale, the market context remains valid and records
  COT as unavailable.

## Normalization

Generate normalized state with:

```bash
./venv/bin/python scripts/cot_positioning_update.py \
  --input data/cot/latest_financial_futures.json \
  --output runtime_state/cot_positioning.json
```

Input shape:

```json
{
  "source": "cftc_cot_financial_futures",
  "markets": {
    "NASDAQ_100": {
      "as_of_date": "2026-06-09",
      "published_at": "2026-06-12T15:30:00-04:00",
      "leveraged_funds_long": 180000,
      "leveraged_funds_short": 80000,
      "leveraged_funds_net_history": [-50000, 0, 100000],
      "leveraged_funds_net_change": 25000,
      "nonreportable_net_change": -10000,
      "open_interest_change": 12000
    }
  }
}
```

The normalizer derives:

- `leveraged_funds_net`
- `leveraged_funds_cot_index_52w`
- `smart_retail_divergence`
- `positioning_regime`
- `cot_size_modifier`

## Symbol Mapping

The current mapping is broad-market and cluster based:

- `QQQ`, mega-cap technology, semiconductors, networking, AI infrastructure:
  `NASDAQ_100`
- `SPY`, industrials, defense, healthcare, financials, consumer, power:
  `S_AND_P_500`
- `IWM`: `RUSSELL_2000`
- `GLD` and hedge cluster: `GOLD`

Per-symbol COT context is written into `market_context.json` as
`symbols.<SYMBOL>.cot_positioning_context`. Top-level COT state is written as
`cot_positioning_context`.

## Operational Placement

Run the update after the weekly CFTC publication has been mirrored or downloaded.
The normal pre-market and intraday context refreshes then consume the latest
normalized state automatically.

