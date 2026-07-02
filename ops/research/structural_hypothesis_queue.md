# Structural Hypothesis Queue

Created: 2026-07-01

Runtime effect: research governance only; no trade, sizing, gate, broker, or
live-signal authority.

Status: parked. The feasibility/MDE matrix completed with
`structural_program_status = not_affordably_testable`; see
`reports/structural_hypothesis/structural_hypothesis_terminal_outcome_2026-07-02.md`.

## Current Status

The PEAD v1 precommit listed this ranked queue:

1. Post-earnings drift.
2. Options positioning / implied volatility / skew / gamma-context effect.
3. Short-interest or crowded-positioning effect.
4. ETF/sector flow or rebalance effect.

PEAD v1 is failed and archived. The remaining queue items are not frozen
contracts.

## Ranking Provenance

No checked-in document currently defines the original ranking criterion that put
PEAD first, options/skew/gamma second, short-interest/crowding third, and
ETF/sector flow fourth. Treat the ordering as an informal placeholder, not as a
permission to start the next item by list position.

Before any successor hypothesis is promoted to a frozen precommit, re-rank the
remaining candidates with an explicit scorecard.

## Required Pre-Contract Triage

Each candidate must be scored before data acquisition or implementation:

- Point-in-time source availability: can the signal be represented at
  `available_at` without lookahead?
- Data cost and licensing: can the account/research budget support the required
  feed long enough to validate?
- Expected event/sample frequency: how many independent observations are
  realistically available over the intended window?
- Minimum detectable effect: what lift or EV can the proposed design detect at
  the program-corrected alpha after within-test correction, given the expected
  sample?
- Trading friction and account deployability: can the expected effect survive
  spreads, slippage, borrow/option/friction, and whole-share/account-size
  constraints?
- Model/construction risk: how much estimation machinery is required before the
  feature is even observable?
- Orthogonality: does the candidate add information not already captured by
  OHLCV or existing context fields?

## Program-Level Alpha

The structural hypothesis queue is one research family. Control family-wise
false-positive risk across the four queued structural hypotheses at `alpha =
0.05`.

Use Bonferroni allocation for the program gate:

- planned family size: `4` structural hypotheses
- program alpha: `0.05`
- per-hypothesis confirmatory alpha: `0.0125`

PEAD v1 is included in the family even though it already failed. Do not recycle
unused alpha from failed hypotheses. A future candidate must clear its own
within-test correction first, then its final corrected confirmatory p-value must
be `<= 0.0125` to count as a pass. A result with `0.0125 < p <= 0.05` is a
research lead, not a contract pass.

If a future queue contains a different number of predeclared structural
hypotheses, freeze the family and alpha allocation before any member result is
inspected.

## New Hypotheses

The current research family is closed at the four structural hypotheses listed
above. A newly discovered structural idea does not retroactively enter this
family, does not shrink the already frozen `0.0125` per-hypothesis alpha, and
does not receive a fresh standalone `0.05` while this family is still active.

New ideas go to a backlog until one of these happens:

- the current four-hypothesis family reaches a terminal state; or
- a human explicitly retires/supersedes the current family before any additional
  confirmatory test is run.

Any successor family must be frozen before its first member result is inspected.
Its family size, alpha allocation, ranking rule, budget constraint, MDE standard,
and stopping rule must be written down at creation time.

## MDE Gate

The minimum-detectable-effect calculation happens before a hypothesis contract is
frozen. This is a formal power calculation, not a qualitative feasibility
judgment.

Power standard:

- minimum power: `80%`
- alpha: the program-corrected confirmatory alpha, currently `0.0125`
- effect target: the candidate's predeclared minimum economically meaningful
  effect after costs and account/deployability constraints
- correction surface: include the candidate's intended within-test multiple
  comparison correction and the program-level alpha above

If realistic sample frequency implies that the design has less than 80% power to
detect the minimum economically meaningful effect at `alpha <= 0.0125`, the
candidate is not ready for pipeline work. If the detectable effect is larger than
the smallest effect that would be deployable after costs, the candidate is also
not ready.

This rule exists because PEAD v1 reached 141 labeled events but the cited
decile-lift feature still split into buckets of 14 rows, yielding a 95% CI of
`[-50.0, 21.4]` percentage points and failing the p-value gates. A future test
must know that power limit before data work begins.

## Matrix Time-Box

The pre-contract feasibility/MDE matrix is time-boxed to one focused research
session with a hard cap of `6` working hours, due no later than `2026-07-02`.
The deliverable is a documented matrix with explicit `pass`, `fail`, or
`unknown` cells and the assumptions used for expected sample frequency, cost,
and MDE. Unknowns do not justify data acquisition or implementation; they either
become bounded lookup tasks or leave the candidate unfrozen.

## Empty-Matrix Outcome

It is acceptable for the matrix to find that none of the remaining candidates
are affordably testable at 80% power under the `0.0125` program-corrected alpha.
That result is a terminal research-program state for the current budget/data
regime, not a reason to lower the power standard, loosen alpha, extend the
timeline, or reallocate SaaS/Deep Thought budget by default.

If the matrix is empty, record the result as `not_affordably_testable` and park
the structural-hypothesis program. Reopening requires a written bounded task
before any data acquisition, pipeline work, or frozen contract. At least one of
these concrete triggers must be satisfied:

- Short-interest/crowding: a clustered/effective-sample power calculation using
  official history beyond the five-year API window shows MDE <= `8.0pp` at
  alpha `0.0125` and `80%` power after symbol and publication-period clustering.
  Evidence target: exact history span plus formula/simulation output. Time-box:
  <= `6` working hours.
- Options/skew/gamma: a verified point-in-time EOD options source covers >= `5`
  historical years for the approved-symbol universe, includes chain/IV/OI/Greek
  fields or raw fields sufficient to freeze one feature, and fits within an
  incremental research-data cap of <= `$1,500` one-time and <= `$250/month`
  without reallocating Deep Thought/SaaS budget. A clustered/date-blocked power
  calculation must still show MDE <= `8.0pp` at alpha `0.0125` and `80%` power.
- ETF/sector flow: a verified point-in-time daily ETF holdings/flows/constituents
  source covers >= `5` historical years, exposes data-availability timestamps,
  maps constituents to approved symbols, and costs <= `$250/month` unless an
  explicit operator budget decision is recorded before lookup. A clustered power
  calculation must still show MDE <= `8.0pp` at alpha `0.0125` and `80%` power.
- Budget/economics: an explicit operator decision changes the research-data
  budget, account-size/deployability assumptions, or EV-after-cost hurdle enough
  to rerun the MDE matrix. The decision must name the dollar/month cap, duration,
  and which existing budget is not being displaced.
- Successor family: a new structural family is frozen with family size, alpha
  allocation, MDE/power standard, ranking rule, budget cap, and stopping rule
  before any new results are inspected.

If none of those triggers is met, `parked` means no active trading-research next
action. Choosing Deep Thought or SaaS work next remains a separate operator
decision, not a default reallocation from the parked program.

## Next Decision

The next task is not automatically "hypothesis #2". The next task is a
pre-contract feasibility/MDE matrix for the remaining candidates. Only after
that matrix exists should one candidate receive a frozen hypothesis contract.
Use `ops/research/structural_hypothesis_mde_matrix_2026-07-02.md` as the
evidence record for that matrix.
