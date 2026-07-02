# Structural Hypothesis Terminal Outcome

Archived: 2026-07-01
Matrix record: `ops/research/structural_hypothesis_mde_matrix_2026-07-02.md`
Governance record: `ops/research/structural_hypothesis_queue.md`
Runtime effect: research governance only; no trade, sizing, gate, broker, or
live-signal authority.

## Verdict

`not_affordably_testable` under the current matrix.

This does not mean every structural idea is false. It means no remaining
candidate is ready for a frozen precommit under the current budget, time-box,
PIT source certainty, and clustered/effective-sample power standard.

## Candidate Results

| Candidate | Terminal matrix result | Reason |
|---|---|---|
| Options positioning / implied volatility / skew / gamma-context effect | `unknown` | Naive MDE looked promising, but no clustered/date-blocked power calculation or frozen feature construction exists. |
| Short-interest or crowded-positioning effect | `underpowered` | The five-year FINRA API design had naive MDE `7.77pp` against an `8pp` floor, only `0.23pp` headroom; repeated-symbol clustering was not computed and any design effect above about `1.06` breaks the gate. |
| ETF/sector flow or rebalance effect | `unknown` | Free public data is aggregate and underpowered; useful symbol-level PIT flow/holding data needs paid/custom access not verified inside the matrix time-box. |

## Binding Consequence

- `candidate_selected_for_precommit`: none
- `bounded_followup_tasks_opened`: none
- structural-hypothesis program status: parked

Do not start a short-interest, options/skew/gamma, ETF-flow, or PEAD v2 contract
from this matrix. Any future work on parked unknowns requires a separately
written bounded task before work starts.

## Reopen Triggers

Reopen only under the concrete triggers in
`ops/research/structural_hypothesis_queue.md`. Reopening requires a separately
written bounded task before any data acquisition, pipeline work, or frozen
contract. The allowed triggers are:

- Short-interest/crowding: official history beyond the five-year API window plus
  clustered/effective-sample power showing MDE <= `8.0pp` at alpha `0.0125` and
  `80%` power after symbol and publication-period clustering.
- Options/skew/gamma: verified PIT EOD options history for >= `5` years, feature
  fields sufficient to freeze one construction, incremental cost <= `$1,500`
  one-time and <= `$250/month` without reallocating Deep Thought/SaaS budget,
  and clustered/date-blocked power showing MDE <= `8.0pp`.
- ETF/sector flow: verified PIT daily holdings/flows/constituents history for >=
  `5` years, data-availability timestamps, approved-symbol mapping, cost <=
  `$250/month` unless explicitly approved, and clustered power showing MDE <=
  `8.0pp`.
- Budget/economics: explicit operator decision naming the dollar/month cap,
  duration, and non-displaced budget, or an explicit account/deployability/EV
  hurdle change sufficient to rerun the MDE matrix.
- Successor family: a new family-level precommit with family size, alpha
  allocation, MDE/power standard, ranking rule, budget cap, and stopping rule
  before inspecting any new results.

Absent one of these triggers, the trading-research track has no active next
action. Choosing Deep Thought or SaaS work next is a separate operator decision,
not a default budget reallocation from this parked state.
