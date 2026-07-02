# Post-Earnings Drift Research Reports

This directory is for research outputs from
`scripts/post_earnings_drift_research.py`.

## Completed Archives

- `pead_v1_terminal_outcome_2026-06-27.md` - PEAD v1 failed its frozen
  precommit contract on the June 27 scan: `events_labeled=141`,
  net EV `-1.402001%`, blocked-null p-value `0.1045`, family-wise p-value
  `0.7015`, and `provisional_no_symbol_costs`.

Before reading any scan output, compare it against:

- `ops/research/post_earnings_drift_v1_precommit.md`
- `ops/research/post_earnings_drift_v1_pit_audit.md`
- the JSON report emitted by `validate-jsonl`
- the scan report emitted by `scan`

Use this result-note template when archiving a completed slice:

```text
Hypothesis: post-earnings drift over 5 sessions
Input file:
PIT audit file:
Validation report:
Scan report:
Event rows:
Labeled rows:
Minimum labeled rows threshold: 30
Point-in-time verdict: pass/fail
Absolute decile lift: __ pct points; threshold: >= 8.0
Blocked-null p-value: __; threshold: <= 0.05
Family-wise p-value: __; threshold: <= 0.05
Regime coherence verdict: pass/fail/provisional
Net expected value after costs: __%; threshold: >= +0.25%
Whole-share/account-size verdict: pass/fail
Per-symbol cost verdict: pass/fail/provisional
Final verdict: pass/fail
Required action:
  - pass: reduce to simple paper-only rule/model
  - fail: archive and move to next ranked hypothesis
Notes:
```

Generated JSON reports may be local artifacts; commit only the summary note when
it is useful as durable project evidence.
