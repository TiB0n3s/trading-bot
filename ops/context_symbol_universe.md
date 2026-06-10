# Context-Only Symbol Universe

The event collector can optionally scrape configured non-traded symbols to enrich approved-symbol context.

## Purpose

Context-only symbols are used for:

- supplier/customer spillover
- peer and sector confirmation
- theme detection
- peripheral risk discovery
- future approved-list review

They are not tradable symbols.

## Runtime Contract

Context-only events are stored with:

- `tradable=false`
- `context_only=true`
- `linked_symbols=[...]`
- `relationship_type=...`
- `context_symbol_universe=context_only`
- `authority=context_only_no_standalone_buy_authority`

Aggregation may include these events when building event context for linked approved symbols. The original non-traded source symbol remains preserved in event metadata.

## CLI Usage

Default collection stays approved-symbol only:

```bash
./venv/bin/python collect_and_score_events.py --date YYYY-MM-DD --apply-context
```

To include context-only symbols:

```bash
./venv/bin/python collect_and_score_events.py \
  --date YYYY-MM-DD \
  --include-context-symbols \
  --apply-context
```

Requesting a context-only symbol without `--include-context-symbols` fails intentionally.

## Guardrails

- Context-only symbols cannot generate predictions unless they are also approved symbols.
- Context-only symbols cannot become trade candidates.
- Context-only events can only enrich linked approved symbols.
- `linked_symbols` must reference approved symbols only.
- Promotion from context-only to tradable requires adding the symbol to `SYMBOL_CONFIG` through normal risk review.

## SpaceX Catalyst Cohort

The SpaceX catalyst cohort is explicitly tiered:

- Approved internal-bar/paper-learning symbols: `NOC`, `LHX`, `HON`, `TDY`
- Context-only symbols: `SPCX`, `IRDM`, `ASTS`, `GSAT`, `RDW`, `PL`, `BKSY`, `SPIR`, `BA`

`SPCX` is a catalyst placeholder, not trade authority. Smaller or more speculative
space names remain context-only until liquidity, spread, slippage, and learning
evidence justify an explicit promotion review.

The SpaceX cohort also has a deterministic value-chain graph exposed by
`services.spacex_value_chain_service`:

- anchor node: `SPCX`
- approved tradable proxies: `NOC`, `LHX`, `HON`, `TDY`
- context-only satellites: `SPCX`, `IRDM`, `ASTS`, `GSAT`, `RDW`, `PL`, `BKSY`, `SPIR`, `BA`
- feature outputs: relationship weight, lead-lag information shock score, and liquidity siphon ratio

These graph features are eligible only as paper/context intelligence. They do
not create standalone trade authority for context-only symbols, and normal
execution, spread, slippage, affordability, and risk gates still apply to the
approved symbols.
