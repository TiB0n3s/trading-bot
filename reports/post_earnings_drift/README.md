# Post-Earnings Drift Research Reports

This directory is for research outputs from
`scripts/post_earnings_drift_research.py`.

Before reading any scan output, compare it against:

- `ops/research/post_earnings_drift_v1_precommit.md`
- the JSON report emitted by `validate-jsonl`
- the scan report emitted by `scan`

Use this result-note template when archiving a completed slice:

```text
Hypothesis: post-earnings drift over 5 sessions
Input file:
Validation report:
Scan report:
Event rows:
Labeled rows:
Point-in-time verdict: pass/fail
Detector verdict: pass/fail
Family-wise correction verdict: pass/fail
Expected-value verdict: pass/fail
Whole-share/account-size verdict: pass/fail
Final verdict: pass/fail
Required action:
  - pass: reduce to simple paper-only rule/model
  - fail: archive and move to next ranked hypothesis
Notes:
```

Generated JSON reports may be local artifacts; commit only the summary note when
it is useful as durable project evidence.

