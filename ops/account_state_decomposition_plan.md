# account_state Decomposition & GateContext Plan

Status: **design / proposal** (no live-code changes here). Authored as the
sequenced, test-gated path to retire the mutable `account_state` god-dict and
unblock the gate-chain (`Gate[]`) extraction in
`src/trading_bot/signals/live/processor.py`.

This plan operates under the project's standing rules: auto-buy is FROZEN in
observe/research mode; **every step below is behavior-preserving**; no step
modifies execution, sizing, risk-gate, broker, webhook-routing, or market-hours
*behavior*. Each phase lands behind characterization tests and the fast safety
harness. Broker batching remains out of scope and gated.

---

## 1. Problem statement

`account_state` is a single mutable `dict[str, Any]` (~140 keys) that is built
upstream, then **mutated in place** by ~10 layers and read everywhere. Measured
surface (current `main`):

- **~130 in-place mutation sites**, concentrated in
  `signals/context/builder.py` (48) and `signals/approval/service.py` (54), with
  the remainder in `services/sizing_service.py` (6), `services/policies/sizing_policy.py`
  (6), `services/setup_context_service.py` (5), `services/preflight_service.py` (3),
  `services/decision/engine.py` (3), `services/decision/orchestrator.py` (2),
  `signals/live/processor.py` (2), and the two managers (1 each).
- **~63 nested-dict section reads** (`account_state.get("x") or {}`) across 16
  files.

Consequences: no schema or type safety; any layer can add/observe a key; a
single function is untestable in isolation without reconstructing the whole dict;
and — the blocker for #3 — the live gate sequence in `processor.process()`
threads interleaved per-signal locals (`current_et`, `existing_position`,
`macro_risk`, `bias_entry`, `decision`, `rejection_adapter`,
`claude_account_state`) as ad-hoc variables, so gates cannot share a uniform
`evaluate(ctx)` signature.

## 2. Already in place (foundation)

- `signals/context/account_state_view.py` — `AccountStateView`, a frozen,
  zero-copy **read lens** over `account_state` whose accessors mirror
  `account_state.get(k) or {}` exactly. 13 section accessors + 3 scalars +
  `get`/`__contains__`/`raw` escape hatch. Tested in `tests/test_account_state_view.py`.
- Adopted (read side) by the fully-typed **approval cluster**:
  `evaluate_approval_decision`, `_paper_learning_override_decision`,
  `_paper_exploration_authority_decision`.
- Persistence connection consolidation + `db.retry_on_locked` are complete and
  unrelated to this plan except that they reduced repo-level raw access.

## 3. The three-category model

The ~130 mutation keys partition cleanly by *when* and *why* they are written.
This partition is the design.

### 3a. INPUTS — built once, read-only thereafter
Populated before any gate runs; never mutated by gates. Owners today:
`context/builder.py`, `setup_context_service.py`, `preflight_service.py`.

```
setup_observation, setup_quality, setup_quality_outcome, setup_structure,
buy_opportunity, prediction_gate, session_momentum, momentum, rolling_momentum,
tape, trend_table, market_alignment, market_bias, market_bias_original,
market_context_summary, market_microstructure, market_participation,
market_regime, regime_observation, regime_observation_context,
regime_routing_decision, macro_risk, volatility_normalization,
downside_asymmetry, exit_decision_quality, execution_quality, ml_prediction,
fundamental_score, risk_level, entry_quality, avoid_type, soft_avoid_reason,
signal_confidence_hint, prior_session, recent_favorable_setup,
adaptive_buy_confirmation, sell_confirmation, fast_lane_buy_flip,
fast_lane_sell_flip, open_momentum_fast_lane, premarket_alignment_source,
portfolio_decision, execution_mode,
current_symbol_position, correlation_exposure, adaptive_churn_reentry   # preflight
```
→ Target: an immutable `SignalIntelligence` dataclass (the typed successor to
`AccountStateView`). The view already models the highest-frequency members.

### 3b. DECISION OUTPUTS — write-once markers emitted during gate evaluation
Produced by gates/approval/sizing as they decide. Owners today:
`approval/service.py`, `sizing_service.py`, `decision/engine.py`,
`decision/orchestrator.py`, `processor.py`.

```
# approval/service.py
paper_exploration_authority, paper_learning_authority_override, ml_authority,
ml_authority_mode, ml_authority_reason, ml_authority_triggered, ml_outcome,
layered_model_decision, historical_bar_meta_label_authority,
decision_policy, decision_policy_authority, decision_policy_outcome,
decision_policy_size_down, decision_policy_max_position_size_pct,
confidence_gate_medium_override, market_bias_effective,
market_bias_override_reason, opportunity_score, session_gate_outcome,
session_gate_size_hint, session_momentum_gate, weak_prediction_setup_gate,
late_chase_entry_gate, intra_session_tape_degradation,
advisory_feature_size_cap, advisory_feature_size_gate,
advisory_feature_max_position_size_pct, strategy_memory, portfolio_rotation,
intelligence_context, weekly_symbol_performance,
soft_avoid_prediction_gate_bypassed, soft_avoid_prediction_gate_bypass_reason
# sizing_service.py
conviction_stack, dominant_limiter, max_position_size_pct_override,
max_position_size_pct, slippage_kelly_sizing
# decision engine / orchestrator
decision_trace, canonical_decision_trace, intelligence_adjudication,
canonical_orchestration_status, canonical_orchestration_delegate
# processor.py
regime_circuit_breaker, setup_policy_override
```
→ Target: a `DecisionTrace` accumulator with explicit `record(name, payload)` —
append-only, observable, never silently overwritten. Replaces the current
"any gate writes any key onto the shared dict" pattern.

### 3c. GATE LOCALS — interleaved per-signal values in `process()`
Currently local variables threaded by hand between gate calls:
`current_et`, `existing_position`, `macro_risk`, `bias_entry`, `decision`,
`claude_account_state`, `rejection_adapter`.
→ Target: fields on `GateContext` (below). This is the specific thing that today
prevents a uniform gate signature.

## 4. Target design (proposed types)

```python
# proposed — signals/live/gate_context.py
from dataclasses import dataclass, field
from typing import Any

@dataclass
class DecisionTrace:
    """Append-only decision-output accumulator (replaces scattered writes)."""
    _outputs: dict[str, Any] = field(default_factory=dict)

    def record(self, name: str, payload: Any) -> None:
        self._outputs[name] = payload

    def as_dict(self) -> dict[str, Any]:
        return dict(self._outputs)

@dataclass
class GateContext:
    """Per-signal evaluation context shared by every gate.

    intelligence: immutable inputs (AccountStateView today, SignalIntelligence later).
    trace: append-only decision outputs.
    Remaining fields are the interleaved per-signal locals process() threads today.
    """
    intelligence: "AccountStateView"
    trace: DecisionTrace
    symbol: str
    action: str
    price: float | None
    dedupe_key: str | None
    current_et: Any | None = None
    existing_position: dict[str, Any] | None = None
    macro_risk: dict[str, Any] = field(default_factory=dict)
    bias_entry: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    rejection_adapter: Any | None = None
```

Gate target signature: `def evaluate(self, ctx: GateContext) -> GateResult`,
where `GateResult` is the existing `StageResult`/`ApprovalGateResult` unified to
carry `rejected` + optional payload. `process()` becomes a sequence (later a
list) of `gate.evaluate(ctx)` calls with the existing short-circuit semantics.

Important compatibility note: during migration, `GateContext.intelligence.raw`
**is** the live `account_state` dict (zero-copy). Writers that have not yet moved
to `DecisionTrace` keep mutating that dict and reads stay consistent. This is what
makes the migration incremental and behavior-preserving rather than a big-bang.

## 5. Write-ownership map (target)

| Key group | Written today by | Target owner | Category |
|---|---|---|---|
| setup_*, *_observation, market_*, momentum, tape, regime_*, macro_risk, prediction_gate, buy_opportunity, session_momentum, volatility/downside/exit quality | `context/builder.py`, `setup_context_service.py` | `SignalIntelligence` (built once) | INPUT |
| position/exposure/churn facts | `preflight_service.py` | `SignalIntelligence` | INPUT |
| ml_authority*, decision_policy*, paper_*_authority, *_gate, advisory_feature_*, market_bias_effective, opportunity_score, intelligence_context | `approval/service.py` | `DecisionTrace.record(...)` | OUTPUT |
| conviction_stack, dominant_limiter, *size*_override, slippage_kelly_sizing | `sizing_service.py` | `DecisionTrace.record(...)` | OUTPUT |
| *_trace, *_adjudication, canonical_orchestration_* | `decision/engine.py`, `decision/orchestrator.py` | `DecisionTrace.record(...)` | OUTPUT |
| regime_circuit_breaker, setup_policy_override | `processor.py` | `DecisionTrace.record(...)` | OUTPUT |
| current_et, existing_position, bias_entry, decision, rejection_adapter | `process()` locals | `GateContext` fields | LOCAL |

## 6. Sequenced migration (each phase test-gated, behavior-preserving)

1. **Characterization harness first.** Before any structural change, extend
   `test_live_signal_characterization` / `test_live_risk_gates` /
   `test_signal_safety_gates` until every gate's reject path and every emitted
   decision-output key is asserted on a fixed input corpus. This is the safety
   net the rest depends on; it must pass against current `main` unchanged.
2. **Finish read-lens adoption** (low risk, optional/parallel): migrate the
   remaining ~63 section reads to `AccountStateView` file-by-file
   (`context/builder.py` reads, `trade_audit_service`, `canonical_intelligence_service`,
   `adjudicator`, `decision_snapshot_service`, …). Pure maintainability.
3. **Introduce `GateContext` + `DecisionTrace`** (additive). Build a `GateContext`
   at the top of `process()`; populate the local fields from the existing
   variables. `intelligence` wraps the live dict (zero-copy). No gate signature
   changes yet — `process()` still calls gates as today. Behavior identical.
4. **Route OUTPUT writes through `DecisionTrace`** one writer-file at a time
   (start with `processor.py`'s 2, then `decision/*`, then `sizing_service.py`,
   then `approval/service.py`'s 54 in clusters). Each write becomes
   `ctx.trace.record(k, v)` **and** continues to mirror into the dict during the
   transition (so unmigrated readers are unaffected) until all readers of that
   key are migrated; then drop the mirror. Per-key, test-gated.
5. **Freeze INPUTS** into `SignalIntelligence`: once builder/setup/preflight are
   the only writers and all reads go through the view, snapshot the inputs into an
   immutable structure built at the pipeline boundary; make `intelligence`
   read-only. Removes the "any layer can add an input key" hazard.
6. **Unify gate signatures to `evaluate(ctx)`** mechanically (gates already are
   named methods; only their parameter plumbing changes — all inputs now on
   `ctx`). Behavior identical; characterization tests are the gate.
7. **Convert `process()` to a `Gate[]` list** with the existing short-circuit
   loop. The interleaved hydration steps become explicit ordered entries
   (hydration "steps" vs reject "gates"); the terminal Claude/order stages stay
   distinct (they produce decision/execution, not just reject). This is #3,
   now mechanical.

## 7. Invariants / risk register

- **Behavior-preserving at every commit.** No reordering of gates, no change to
  reject categories/reasons, no change to emitted keys' values. Characterization
  tests + `run_safety_checks.py` (37 files) must stay green.
- **Live-path latency guards untouched.** `prediction_repo` (50ms) and
  `bar_pattern_feature_repo` tight-timeout reads stay as-is.
- **No authority/gate loosening.** This is a structural refactor only; thresholds
  and gate decisions are unchanged. Promotion remains a human decision.
- **Broker path excluded and gated.** No change to order submission.
- **Mirror-then-drop discipline** for OUTPUT keys: never remove the dict mirror
  for a key until a grep proves no remaining reader reads it from the dict.
- **`DecisionTrace` is append-only**; if two writers target the same key today
  (e.g. `session_momentum` appears in both builder INPUT and approval OUTPUT),
  resolve the collision explicitly in Phase 4 before routing — do not assume.

## 8. Definition of done

`processor.process()` is a short-circuit loop over a `Gate[]` list operating on a
`GateContext`; `account_state` as a free-form mutable dict is gone from the live
signal path (inputs immutable, outputs in `DecisionTrace`); the full
characterization + safety suites pass unchanged in behavior.
