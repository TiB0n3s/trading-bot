# AI Leverage Audit

Last reviewed: 2026-06-02

This audit covers the current reports, monitors, and runtime logs and identifies where AI can add useful operator intelligence. These recommendations are diagnostic and observe-only unless a future authority path explicitly promotes them.

## Current Evidence

- `ops_check.py ai-intelligence-review 2026-06-02` is available and currently reports `runtime_effect=observe_only_no_live_authority`.
- `market_context.json` now has AI event-context aggregate fields populated for all 59 symbols.
- `ops_check.py event-source-coverage 2026-06-02` shows 242 events, but only 9.1% trusted-source coverage and 60.7% unclassified-source coverage.
- `ops_check.py runtime-health 2026-06-02` shows 741 job runs, 716 successes, 4 failures, 21 lock-busy skips, 5128 warnings, and p95 duration near 97 seconds.
- Logs show repeated market-data retry/fallback noise in `live_features.log`, `session_momentum.log`, `rolling_momentum.log`, and `label_features.log`.
- `ops_check.py decision-lifecycle-dashboard 2026-06-02` is analysis-ready for the available rows, but the current sample is rejected-only.

## Where AI Is High Value

### Event And Context Reports

Reports:

- `event_attribution_report.py`
- `intelligence_context_report.py`
- `intelligence_learning_report.py`
- `market_alignment_report.py`
- `event-source-coverage`
- `event-context-validation`

Best AI use:

- Interpret event intent from trusted headlines and source metadata.
- Distinguish company-specific impact from broad market noise.
- Summarize direct versus peripheral catalysts.
- Flag weak source chains, unconfirmed rumors, stale context, and unsupported directional inference.
- Produce a source-grounded narrative for why event context is bullish, bearish, neutral, or insufficient.

Guardrail:

- AI event interpretation should remain context-only until source reliability, confirmation status, and realized attribution pass governance thresholds.

### Runtime And Log Health

Reports/logs:

- `runtime-health`
- `runtime-health-trend`
- `log-ledger-consistency`
- `service_health.log`
- `live_features.log`
- `session_momentum.log`
- `rolling_momentum.log`
- `label_features.log`
- `event_collection.log`
- `fill_poller.log`
- `portfolio_rotation.log`

Best AI use:

- Collapse thousands of repeated warnings into a small set of root-cause clusters.
- Detect recurring degradation patterns such as SIP fallback storms, stale context, high p95 duration, lock contention, zero-row successes, and repeated retry loops.
- Generate an operator briefing with severity, affected jobs, affected symbols, and recommended next checks.
- Compare log-derived warnings against the durable `job_runs` ledger to find logging/ledger drift.

Guardrail:

- AI should not decide whether a job succeeded. The ledger remains canonical; AI summarizes and prioritizes.

### Lifecycle, Candidate, And Learning Reports

Reports:

- `decision-lifecycle-dashboard`
- `lifecycle-analysis`
- `candidate-universe`
- `calibration-buckets`
- `feature-attribution`
- `post-trade-learning`
- `blocked_signal_outcome_report.py`
- `missed_opportunity_report.py`
- `excursion_report.py`

Best AI use:

- Explain recurring false positives and false negatives in plain language.
- Summarize which setup/regime/session-phase buckets are improving or deteriorating.
- Identify candidate-universe blind spots, near-threshold misses, and rejected rows that later worked.
- Produce post-trade review narratives using entry snapshot, decision, execution, exit snapshot, and post-exit path.

Guardrail:

- AI-generated explanations should not replace numeric attribution. Reports should show sample size, EV delta, stability, MFE/MAE, and missing-rate context first.

### Decision Quality Reports

Reports:

- `setup-breakdown`
- `conviction-stack-report`
- `conviction-persistence-health`
- `buy_opportunity_report.py`
- `entry_quality_report.py`
- `session_gate_report.py`
- `trend_context_report.py`
- `market_alignment_report.py`
- `prediction_validation_report.py`
- `prediction_report.py`

Best AI use:

- Explain why advisory layers disagree with final execution.
- Detect stale or contradictory context in setup, trend, session momentum, prediction, and buy-opportunity signals.
- Convert dense report tables into ranked operational questions for review.
- Summarize confidence calibration gaps by setup, regime, time of day, volatility bucket, and source quality.

Guardrail:

- AI should not create new approval or sizing behavior from report summaries. Promotions must go through the rollout contract.

### Portfolio And Execution Reports

Reports/logs:

- `portfolio-risk`
- `portfolio_replacement_report.py`
- `portfolio_rotation.log`
- `position_manager.log`
- `position_momentum_monitor.log`
- `fill_stream.log`
- `fill_poller.log`
- `trade_matcher.log`

Best AI use:

- Summarize duplicate exposure, sector/theme concentration, and replacement rationale.
- Explain execution-quality degradation using spread, slippage, fill drift, and quote instability.
- Identify exit-quality patterns such as early exits, missed upside, avoided drawdown, and re-entry windows.
- Translate fill/order reconciliation anomalies into operator tasks.

Guardrail:

- Broker, fill, and reconciliation state must remain deterministic. AI can triage anomalies but should not mutate execution or matching records.

## Medium-Value AI Uses

- `daily_summary.py`: operator narrative over realized day, but deterministic P&L remains primary.
- `analytics_report.py`: summarization of broad patterns, not causal claims.
- `drawdown_report.py`: explain concentration of losses and candidate root causes.
- `filter_report.py`: summarize which filters are adding or destroying expectancy.
- `tradingview_alert_coverage_report.py`: explain alert coverage misses and candidate symbols requiring alert review.
- `strong_day_participation_report.py`: summarize no-signal strength and candidate-universe misses.
- `strategy_brain_report.py`: summarize stale memory artifacts and conflicting manual overrides.

## Low-Value Or Risky AI Uses

- Direct broker/order submission decisions.
- Fill matching, order reconciliation, or synthetic exit insertion.
- Hard blocker taxonomy such as stale signal, spread failure, account constraints, and max risk.
- DB migration, retention, and schema checks.
- Cron lock acquisition and exit-code determination.

These areas should remain deterministic. AI can explain failures after the fact.

## Recommended Implementation Order

1. Add an AI operator briefing command that consumes runtime health, data freshness, event-source coverage, lifecycle dashboard, feature attribution, and log-ledger consistency.
2. Add log-cluster extraction for the most warning-heavy logs, especially `live_features`, `session_momentum`, `rolling_momentum`, and `label_features`.
3. Extend event-context validation with source-grounded AI explanations for unclassified or low-confidence events.
4. Add lifecycle narrative samples to the decision lifecycle dashboard.
5. Add portfolio/execution review summaries that explain duplicate risk, execution-cost drag, and exit-quality patterns.
6. Add tests that confirm every AI review output has `runtime_effect=observe_only_no_live_authority`.

## Immediate Non-AI Findings From The Scrape

- Event source coverage still needs work: unclassified sources are too high for trusted event inference.
- Data freshness currently flags missing `intraday_refresh` metadata and stale `session_momentum`.
- Runtime health shows lock contention and high warning volume; AI can summarize this, but scheduler/data-source tuning is still the actual fix.
- Recent portfolio rotation logs are succeeding; an earlier `rollout_contract` `NameError` appears stale.

