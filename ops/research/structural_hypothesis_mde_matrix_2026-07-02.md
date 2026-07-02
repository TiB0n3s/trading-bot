# Structural Hypothesis Feasibility / MDE Matrix

Created: 2026-07-01
Due: 2026-07-02
Time-box: 6 working hours maximum
Runtime effect: research governance only; no trade, sizing, gate, broker, or
live-signal authority.

## Binding Rules

Source governance: `ops/research/structural_hypothesis_queue.md`.

- Closed family: the original four structural hypotheses.
- Already terminal: PEAD v1 failed and remains in the alpha family.
- Remaining candidates: options/skew/gamma; short-interest/crowding; ETF/sector
  flow or rebalance.
- Program alpha: `0.05`.
- Bonferroni per-hypothesis confirmatory alpha: `0.0125`.
- Minimum power: `80%`.
- No alpha recycling.
- No fresh standalone alpha for newly discovered ideas while this family is
  active.
- Empty matrix outcome is valid: `not_affordably_testable`.
- Panel candidates must use clustered/effective sample size, not naive row count,
  before receiving `ready_for_precommit`.

## How To Fill The Matrix

Use one row per remaining candidate. Fill every cell with one of:

- `pass`: enough evidence exists now to support a frozen contract.
- `fail`: evidence says the candidate is not feasible under the current budget,
  alpha, power, or deployability constraints.
- `unknown`: not enough evidence inside the 6-hour matrix window.

Unknowns do not permit data acquisition, implementation, or contract freezing.
They become bounded lookup tasks or leave the candidate unfrozen.

`unknown` is not a terminal pass and not a reason to keep the family open
indefinitely. If the matrix time-box ends with no `ready_for_precommit`
candidate, unresolved `unknown` rows are parked unless a bounded lookup task is
explicitly created with its own owner, evidence target, and time-box.

## Minimum Fields Per Candidate

Each candidate row must name:

- `candidate`: exact structural hypothesis.
- `signal_unit`: the unit of independent observation.
- `pit_source`: plausible point-in-time source and whether it is affordable.
- `sample_window`: realistic validation window.
- `expected_n`: expected independent observations in that window.
- `outcome_definition`: fixed forward-return/EV label.
- `test_design`: proposed statistical test and within-test correction.
- `alpha`: must be `0.0125` for confirmatory pass.
- `power`: must be at least `80%`.
- `economic_effect_floor`: smallest effect that would matter after costs.
- `mde`: minimum detectable effect at `alpha=0.0125`, `power=80%`, and
  `expected_n`.
- `mde_verdict`: pass only if `mde <= economic_effect_floor`.
- `data_cost_verdict`: pass only if PIT data fits the available budget long
  enough to validate.
- `friction_verdict`: pass only if the effect can survive expected spreads,
  slippage, borrow/options frictions, and account-size constraints.
- `construction_risk`: estimation/model risk before the signal is observable.
- `orthogonality`: whether this adds information not already in OHLCV/context.
- `final_matrix_verdict`: `ready_for_precommit`, `not_affordably_testable`,
  `underpowered`, or `unknown`.

## MDE Calculation Standard

Prefer the simplest power calculation that matches the proposed test:

- Binary lift / win-rate difference: two-proportion power calculation.
- Mean return / EV difference: two-sample or one-sample mean-effect calculation.
- Rank/decile detector: calculate power on the actual top-vs-bottom bucket sizes,
  not the total sample. If the design uses 10 deciles, effective per-tail `n` is
  approximately `floor(expected_n / 10)`.
- Panel/repeated-symbol designs: calculate power on clustered or otherwise
  effective sample size. Naive symbol-period or symbol-day counts may be reported
  as an upper bound, but they cannot produce a `pass` MDE verdict by themselves.
  The cluster plan must at least address repeated symbols and shared market-date
  shocks.

For a rough binary top-vs-bottom lift screen, use:

```text
z_alpha = inverse_normal_cdf(1 - alpha / 2)
z_power = inverse_normal_cdf(power)
baseline = expected base win rate
n_tail = expected observations per compared tail bucket
mde_pp ~= 100 * (z_alpha + z_power) * sqrt(2 * baseline * (1 - baseline) / n_tail)
```

For a rough mean-return screen, use:

```text
z_alpha = inverse_normal_cdf(1 - alpha / 2)
z_power = inverse_normal_cdf(power)
sigma = expected standard deviation of forward return
n_eff = expected independent observations in the tested contrast
mde_return_pct ~= (z_alpha + z_power) * sigma * sqrt(2 / n_eff)
```

These formulas are acceptable for matrix triage. A frozen hypothesis contract may
replace them with a more exact simulation, but it cannot loosen alpha, power, or
economic deployability after seeing results.

Near-threshold rough MDE results do not pass automatically. If rough MDE is
within 10% of the economic effect floor, require exact clustered/simulation
power before freezing a precommit.

## Tie-Breaker Rule

Apply this only after hard gates pass: PIT source, data cost, clustered MDE,
friction/deployability, and construction risk. If more than one candidate clears
all hard gates, select by:

1. official/public PIT source over vendor-modeled or custom data;
2. lower construction/model risk;
3. lower data cost and licensing friction;
4. larger MDE headroom versus the economic effect floor;
5. lower execution/friction complexity.

This rule cannot rescue a candidate whose MDE or source cells are `unknown` or
`fail`.

## Candidate Matrix

| Candidate | Signal unit | PIT source | Sample window | Expected n | Outcome definition | Test design | Alpha | Power | Economic effect floor | MDE | MDE verdict | Data cost verdict | Friction verdict | Construction risk | Orthogonality | Final matrix verdict |
|---|---|---|---|---:|---|---|---:|---:|---|---|---|---|---|---|---|---|
| Options positioning / implied volatility / skew / gamma-context effect | Approved-symbol trading day, feature known after options EOD file availability | ORATS EOD options data appears affordable (`$599` historical from 2007 plus `$99/mo` recurring); Alpaca offers options history only since Feb. 2024 and free indicative data is not true OPRA | 2.4 years via Alpaca-like history, or 5+ years via ORATS EOD | Naive upper bound: 46,585 symbol-days for 77 symbols x ~605 trading days; ORATS 5-year proxy 97,020. Clustered/effective n not computed. | 5-session forward common-stock return after feature availability, net EV after costs | Cross-sectional rank / top-bottom decile lift, blocked by market date, within-feature family correction; must use clustered or block-bootstrap power before contract | 0.0125 | 80% | >= 8pp top-bottom win-rate lift and >= +0.25% net EV after costs | Naive MDE: 3.46pp on 2.4-year proxy; 2.40pp on 5-year proxy. Clustered MDE not computed. | unknown until clustered/simulation power | pass for ORATS EOD; unknown for Alpaca OPRA entitlement | pass for common-stock execution, but feature source is options-market derived | high: skew/gamma construction choices and vendor Greek methodology must be frozen before use | pass: options surface/open-interest state is orthogonal to OHLCV | unknown |
| Short-interest or crowded-positioning effect | Approved-symbol short-interest settlement period, feature known on publication date | FINRA Equity Short Interest: twice-monthly reports, five rolling years via Equity API, historical files available | 5 rolling years | Naive upper bound: 9,240 symbol-periods for 77 symbols x 24 reports/year x 5 years. Effective clustered n not computed; each symbol has ~120 repeated, autocorrelated observations. | 10-session or next-report-window forward common-stock return after publication date, net EV after costs | Cross-sectional rank / top-bottom decile lift by short-interest pressure/change, blocked by publication/settlement period; must cluster/block by symbol and publication period | 0.0125 | 80% | >= 8pp top-bottom win-rate lift and >= +0.25% net EV after costs | Naive MDE: 7.77pp on 5-year API window; 5.01pp if historical files back to 2014 are used. Five-year pass margin is only 0.23pp; any design effect > ~1.06 breaks the 8pp gate. Clustered MDE not computed. | fail for 5-year API under conservative clustered standard; unknown if longer historical files plus clustered power pass | pass: official/public source fits budget | pass: common-stock execution; no options/borrow execution required | low/moderate: reporting lag and float normalization must be frozen | pass: positioning/crowding is orthogonal to OHLCV | underpowered |
| ETF/sector flow or rebalance effect | Weekly aggregate flow event for free public data; symbol/ETF-day only if paid ETF feed is available | Free ICI weekly aggregate flows are public but not symbol-level. Trackinsight/ETF Global offer daily flows/constituents, but pricing/access is contact-sales/custom in this pass | Free source: 5 weekly years. Paid source: unknown until quote/trial terms | Free source 260 weekly observations; paid source not verified | Forward sector/constituent return after flow/rebalance availability, net EV after costs | Free source: aggregate flow regime test. Paid source would need constituent/flow rank test with PIT holdings and clustered power | 0.0125 | 80% | >= 8pp top-bottom win-rate lift and >= +0.25% net EV after costs | Free source 46.31pp; paid 20-ETF daily 5-year proxy would be 4.70pp but data access and clustered effective n are unverified | fail for free source; unknown for paid source | unknown: institutional/custom data likely required for useful symbol-level PIT flow/holdings | pass for common-stock execution if source exists | moderate/high: mapping ETF flows to approved symbols and rebalance timing must be frozen | pass if symbol-level constituent/flow data exists; fail for aggregate-only data | unknown |

## Candidate Notes

### Options Positioning / Implied Volatility / Skew / Gamma Context

- Candidate question: do options-surface / positioning features known after the
  options EOD file predict 5-session common-stock returns for approved symbols?
- Plausible PIT source: ORATS EOD options data is the viable desk-pass source:
  history back to 2007, 5,000+ symbols, Greeks/IV/theoretical values, `$599`
  one-time historical EOD and `$99/mo` recurring EOD. Alpaca is a possible
  existing-broker source but its options history starts only in Feb. 2024 and its
  free indicative feed is not true OPRA.
- Expected event/sample frequency: 77 approved symbols x ~605 trading days
  since Feb. 2024 = 46,585 symbol-days; ORATS 5-year proxy = 97,020
  symbol-days.
- Proposed test construction: rank by one predeclared options feature family
  (for example skew percentile, IV term structure, OI/gamma pressure), block by
  market date, compare top vs bottom decile on 5-session forward return and
  win-rate lift.
- MDE assumptions: alpha `0.0125`, power `80%`, baseline win rate `50%`,
  binary top-bottom decile lift. MDE is `3.46pp` with 46,585 rows
  (`n_tail=4,658`) or `2.40pp` with 97,020 rows (`n_tail=9,702`) before
  clustering. This is an upper-bound power read, not a pass.
- Cost/account-friction assumptions: feature source cost appears affordable via
  ORATS EOD. Trades remain common-stock trades, so execution friction is the
  existing stock spread/slippage/account-size problem, not option execution.
- Blocking unknowns: exact feature construction and vendor Greek/model
  dependence. The precommit must freeze one simple construction before data is
  inspected.
- Verdict: `unknown`; the source and naive power are promising, but no options
  contract should be frozen until one simple feature construction and a clustered
  or date-blocked power simulation are written down.

### Short-Interest / Crowded-Positioning Effect

- Candidate question: do published short-interest/crowding levels or changes
  predict 10-session or next-report-window forward common-stock returns after
  publication?
- Plausible PIT source: FINRA Equity Short Interest is official, twice-monthly,
  and available through an interactive grid, historical files, and an Equity API
  with five rolling years.
- Expected event/sample frequency: 77 approved symbols x 24 reports/year x
  5 years = 9,240 symbol-period observations.
- Proposed test construction: rank symbols by predeclared short-interest
  pressure/change field after publication date, block by settlement/publication
  period, compare top vs bottom decile on forward return and win-rate lift.
- MDE assumptions: alpha `0.0125`, power `80%`, baseline win rate `50%`,
  binary top-bottom decile lift. Naive MDE is `7.77pp` on five rolling years
  (`n_tail=924`) and `5.01pp` if archived files back to 2014 are used
  (`n_tail=2,217`). The five-year margin over the 8pp floor is only `0.23pp`.
  Because each symbol contributes repeated autocorrelated observations, the
  naive five-year MDE is not a valid pass. Any design effect above about `1.06`
  pushes the five-year MDE above the 8pp floor.
- Cost/account-friction assumptions: data is official/public and fits budget.
  Trades remain common-stock trades; no borrow/short execution is required if
  the feature is used only as a long/avoid/size-down signal.
- Blocking unknowns: must freeze whether the feature is level, change, days to
  cover, short-interest/float, or a composite. Must use publication date, not
  settlement date, as `available_at`.
- Verdict: `underpowered` on the five-year API design. A longer historical-file
  design may become viable, but only after clustered/effective-sample power is
  computed before any precommit is frozen.

### ETF / Sector Flow Or Rebalance Effect

- Candidate question: do ETF/sector flows or rebalance/constituent changes
  predict approved-symbol forward returns after the flow/holding data is
  knowable?
- Plausible PIT source: public ICI weekly flow estimates are available but are
  aggregate category-level data, not symbol-level constituent flow. Trackinsight
  and ETF Global offer daily ETF flows/constituents/holdings data, but the pass
  found contact-sales/custom access, not a verified affordable plan.
- Expected event/sample frequency: free public aggregate source has only about
  260 weekly observations over 5 years and is not symbol-level. A hypothetical
  paid 20-ETF daily design over 5 years would have ~25,200 ETF-days, but pricing
  and PIT history terms are unverified.
- Proposed test construction: free source could only support a broad regime
  test. A useful symbol-level test would require daily PIT ETF holdings/flows
  mapped to approved-symbol constituents, with data availability timestamps.
- MDE assumptions: free weekly aggregate design has MDE `46.31pp`
  (`n_tail=26`), which is not realistic. A paid 20-ETF daily proxy would have
  MDE `4.70pp` (`n_tail=2,520`), but the source is not confirmed affordable.
- Cost/account-friction assumptions: common-stock execution is feasible if the
  feature exists. Data cost/access is the blocker.
- Blocking unknowns: paid data pricing, historical PIT terms, constituent/flow
  timestamp semantics, and mapping rules from ETF flows to approved symbols.
- Verdict: `unknown`; no pipeline or contract until source pricing and PIT
  history are verified. This row is parked after the matrix time-box unless a
  bounded pricing/PIT lookup task is explicitly opened.

## Sources Reviewed

- ORATS one-minute/EOD historical options data: https://orats.com/one-minute-data
- ORATS options data API: https://orats.com/data-api
- Alpaca historical option data: https://docs.alpaca.markets/us/docs/historical-option-data
- FINRA Equity Short Interest: https://www.finra.org/finra-data/browse-catalog/equity-short-interest
- FINRA Short Interest Reporting: https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest
- ICI combined estimated long-term flows and ETF net issuance: https://www.ici.org/research/stats/combined_flows
- Trackinsight ETF data services: https://www.trackinsight.com/services/data-services
- ETF Global U.S.-listed data brochure: https://media.etfg.com/files/Data%20Brochure/ETF%20Global%20Data%20Package%20-%20U.S.%20Listed%20-%202025%20-%201.1.25.pdf

## Terminal Outcome

Filled matrix outcome:

- `candidate_selected_for_precommit`: none
- `all_candidates_not_affordably_testable`: true under the current matrix
- `parked_unknowns`: options clustered/date-blocked power and feature
  construction; short-interest longer-history clustered power; ETF/sector flow
  paid data pricing and PIT history terms
- `bounded_followup_tasks_opened`: none
- `structural_program_status`: not_affordably_testable

If all remaining candidates fail or remain unknown under the time-box, record
`structural_program_status = not_affordably_testable` and park the program until
one of the reopen triggers in `ops/research/structural_hypothesis_queue.md`
occurs.

This terminal state does not say the structural ideas are impossible. It says no
candidate is ready for a frozen contract under the current budget, time-box, PIT
source certainty, and clustered-power standard. Any future work on the parked
unknowns requires a separately written bounded task before work starts.
