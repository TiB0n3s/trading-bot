# Runtime JSON Inventory

Root-level runtime JSON files are the canonical live state location. Scripts must
not write duplicate runtime JSON files under `scripts/`.

## Active Root Runtime Files

| File | Runtime role | Primary writer |
| --- | --- | --- |
| `market_context.json` | Live macro/symbol context consumed by Flask runtime, signal context, snapshots, ops checks | `scripts/pre_market_research_data.py`, `scripts/intraday_context_refresh.py`, manual parsers |
| `rolling_momentum.json` | Recent rolling trend context consumed by auto-buy and trend persistence | `scripts/rolling_momentum.py` |
| `position_manager_state.json` | Position manager local state | `scripts/position_manager.py` |
| `portfolio_replacement_memory.json` | Portfolio rotation/replacement memory | `scripts/portfolio_replacement_report.py`, `scripts/portfolio_replacement_memory.py` |
| `strategy_memory.json` | After-close strategy learning memory | `scripts/strategy_learner.py` |
| `missed_opportunity_memory.json` | Missed-opportunity learning memory | `scripts/missed_opportunity_report.py` |
| `excursion_memory.json` | MFE/MAE excursion learning memory | `scripts/excursion_report.py` |
| `policy_backtest_summary.json` | Policy backtest summary used by policy artifacts and reports | `scripts/policy_backtest.py` |
| `symbol_momentum_timing_memory.json` | Generated per-symbol momentum timing memory; local runtime artifact ignored by git | `scripts/symbol_momentum_timing_report.py` |
| `symbol_overrides.json` | Operator symbol disable/override configuration | operator-edited root file |
| `manual_strategy_overrides.json` | Operator strategy override configuration | operator-edited root file |

## Archived Duplicates

Duplicate runtime JSON files previously written under `scripts/` were archived
under `data_archive/runtime_json_duplicates/` on 2026-06-09. The archive is a
local runtime archive and is intentionally ignored by git.

## Regression Coverage

`tests/test_market_context_output_paths.py` verifies:

- live market-context writers target root `market_context.json`;
- other runtime JSON writers target root files;
- `scripts/` contains no duplicate runtime JSON files.
