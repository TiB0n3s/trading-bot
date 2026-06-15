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
- Adjacent/value-chain events are stored as discounted ML evidence only:
  `adjacent_event_count`, `adjacent_impact_score`,
  `adjacent_source_symbols`, `adjacent_relationships`, and
  `adjacent_themes` are written under `daily_symbol_context.raw_json.event_context`.
- Adjacent evidence has `context_only_no_standalone_trade_authority`; it can be
  learned against forward outcomes, but it must not directly approve or size a
  trade without a later authority-promotion change.
- Approved-symbol adjacency uses explicit value-chain mappings, not generic
  cluster overlap, to avoid broad sector bleed-through.
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

## AI Infrastructure Dependency Cohort

The AI infrastructure cohort captures the companies that the large AI
semiconductor/platform names rely on: networking, switching, data-center power,
utility capacity, AI cloud/HPC capacity, and advanced nuclear/power optionality.

Approved internal-bar/paper-learning symbols:

- Core AI semiconductors/platforms already in the universe: `NVDA`, `AMD`, `AVGO`
- Added AI semiconductor/networking dependencies: `INTC`, `CSCO`, `JNPR`, `MRVL`, `ANET`
- Data-center power/grid dependencies: `VRT`, `ETN`, `GEV`, `CEG`

Context-only symbols:

- AI compute / bitcoin-miner-to-HPC peers: `IREN`, `CIFR`, `WULF`, `CORZ`
- AI cloud providers: `NBIS`, `CRWV`
- Advanced nuclear / speculative power peers: `OKLO`, `SMR`

Ticker normalizations from operator shorthand:

- `Cif` -> `CIFR` / Cipher Digital
- `Nabis` -> `NBIS` / Nebius Group
- `CRW` -> `CRWV` / CoreWeave
- `GE Verona` -> `GEV` / GE Vernova

The speculative compute and nuclear names are context-only by default. They
can influence linked approved symbols through event context and value-chain
features, but they cannot become standalone trade candidates without explicit
promotion into `SYMBOL_CONFIG` and normal liquidity/slippage review.

## Critical Materials, Space Autonomy, And Robotics Expansion

The broader AI dependency map also includes upstream materials, autonomous
systems, robotics, and space-infrastructure names that may act as leading
context for the AI infrastructure theme.

Approved internal-bar/paper-learning symbols:

- Critical materials: `MP`, `FCX`, `ALB`
- Space/defense autonomy: `RKLB`, `KTOS`, `AVAV`
- Automation/robotics software and systems: `PATH`, `SYM`

Context-only symbols:

- Domestic rare earth / uranium context: `USAR`, `UUUU`, `UEC`
- Space-infrastructure context already in the SpaceX cohort: `ASTS`
- Lunar and autonomous systems context: `LUNR`, `ONDS`
- Aerospace controls microcap context: `SVT`

Ticker normalizations from operator shorthand:

- `USA Rare Earth` -> `USAR`
- `Ueu` is ambiguous; both `UUUU` / Energy Fuels and `UEC` / Uranium Energy are
  retained as context-only until the intended ticker is confirmed.
- `Symbiotic` -> `SYM` / Symbotic
- `Servotronics` -> `SVT`

The critical-materials and robotics additions are still subject to ordinary
bar coverage, liquidity, execution-quality, affordability, and model-learning
gates. Context-only names cannot create standalone trade authority.

## Value-Chain Eco-Cluster Graphs

All approved and context-only symbols are represented in a deterministic
value-chain eco-cluster graph exposed by
`services.value_chain_eco_cluster_service`.

The current graph source is deliberately static and point-in-time safe:

- approved symbol cluster membership from `SYMBOL_CONFIG`
- context-only `linked_symbols` relationships from `CONTEXT_ONLY_SYMBOL_CONFIG`
- relationship categories and weights from checked-in metadata

The graph produces ML/reference features for every symbol:

- eco-cluster scope
- authority tier
- graph degree
- maximum relationship weight
- average relationship weight
- linked context count

Discovery remains a separate asynchronous layer. External NLP, filings, supply
chain, or transcript scanners must write reviewed static metadata before
pre-market filtering. They must not run inside the live execution loop.
