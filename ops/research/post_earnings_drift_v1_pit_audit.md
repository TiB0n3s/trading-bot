# Post-Earnings Drift V1 Point-In-Time Audit

Created: 2026-06-16

Complete this audit before trusting any `post_earnings_drift_v1` scan output.
The script validator checks shape and obvious timestamp contradictions only; it
cannot prove that the source data is point-in-time correct.

## Dataset Under Audit

- Input JSONL:
- Source/vendor:
- Date range:
- Symbols:
- Event rows:
- Auditor:
- Audit date:

## Required Manual Row Checks

Hand-check at least 5-6 event rows before the first scan. Prefer rows spanning:

- at least two symbols,
- both `before_open` and `after_close` events if present,
- at least one positive surprise,
- at least one negative surprise,
- at least one high-priced symbol where whole-share friction matters.

For each sampled row, record:

| Row | Symbol | Earnings TS | Available At | Timing | Primary/source evidence | Consensus evidence | Surprise tie-out | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 |  |  |  |  |  |  |  | pass/fail |
| 2 |  |  |  |  |  |  |  | pass/fail |
| 3 |  |  |  |  |  |  |  | pass/fail |
| 4 |  |  |  |  |  |  |  | pass/fail |
| 5 |  |  |  |  |  |  |  | pass/fail |
| 6 |  |  |  |  |  |  |  | pass/fail |

## Point-In-Time Checks

For every sampled row, verify:

- `earnings_ts` is the actual announcement/release timestamp, not only the
  reporting date.
- `available_at` is after the announcement was knowable and before the scan
  entry anchor.
- `report_timing` is correct:
  - `before_open` events become tradable after the morning availability time.
  - `after_close` events become tradable no earlier than the next available
    session.
  - ambiguous timing is marked and excluded or treated conservatively.
- `eps_surprise_pct` and `revenue_surprise_pct`, when present, are computed
  against the consensus estimate as it existed before the print.
- Consensus values were not sourced from a backfilled or restated historical
  endpoint unless the source explicitly provides point-in-time estimates.
- Reported values match the primary earnings release, filing, or issuer source.
- Symbols that later delisted, merged, or were acquired are not silently dropped
  from the test universe if they were in-scope at the time.
- No row uses data collected later as if it had been available at the decision
  timestamp.

## Cost Assumption Checks

Before evaluating pass/fail, record:

- Account equity used in scan:
- Max position percent used in scan:
- Spread assumption source:
- Slippage assumption source:
- Symbols requiring worse-than-default spread/slippage:

If per-symbol costs are not available, use conservative assumptions and mark the
scan as provisional until actual symbol-level costs are attached.

## Audit Verdict

- `pass`: sampled rows tie out, timing is conservative, and no point-in-time
  leak was found.
- `fail`: any sampled row has unreconciled timestamp, consensus, source, or
  survivorship issues.
- `provisional`: source is usable for plumbing, but not trustworthy enough for
  promotion evidence.

Final PIT audit verdict:

Required action:

