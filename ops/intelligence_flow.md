# Intelligence Flow

## Preferred Direction

The primary pre-market intelligence flow should use `pre_market_research_data.py`.

This is the deterministic/no-Claude path built around:

- Alpaca market data
- raw research templates
- `market_intelligence.market_brief_builder`
- `market_intelligence.market_brief_schema`
- optional context ingestion into `daily_symbol_context`
- alerts on completion/failure

## Primary Script

```bash
python3 pre_market_research_data.py \
  --date YYYY-MM-DD \
  --raw-output /tmp/raw_research_YYYY-MM-DD.json \
  --build-output /tmp/market_context_YYYY-MM-DD.sample.json \
  --ingest-context
For safe validation, always use --build-output so live market_context.json is not modified.

Live Write Behavior

pre_market_research_data.py can write live market_context.json when no --build-output is provided or when the build output explicitly targets the live file.

Before market open, live writes should only happen intentionally after sample output has been reviewed.

Legacy / QC Script

pre_market_research.py is the Claude-first batched web_search script.

It should not be the primary intelligence generator going forward.

Use it only for:

manual QC
override review
comparison against deterministic output
temporary fallback if deterministic data collection fails
Current Architecture Direction

Preferred flow:

collect deterministic raw data/events
→ build raw research
→ build normalized market context
→ validate schema
→ write sample output
→ review
→ write live market_context.json only when intentional
→ ingest context for reporting/learning
Do Not Do

Do not spend refactor effort expanding the Claude-first script unless it is needed as a temporary fallback.

Do not make Claude/web_search the only pre-market source of truth.

Do not write live market_context.json from any script without confirming:

intended market date
approved symbol count
schema validity
macro fields
avoid_type behavior
source/format fields
