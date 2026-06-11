"""ML authority gate trace adapter."""

from typing import Any

from ..trace import GateResult


def build_ml_authority_gate(account_state: dict[str, Any]) -> GateResult:
    layered = account_state.get("layered_model_decision")
    layered = layered if isinstance(layered, dict) else {}
    if layered:
        instruction = str(layered.get("final_instruction") or "").strip().lower()
        final_size = layered.get("final_size_pct")
        if instruction == "veto":
            decision = "block"
        elif instruction in {"size_increase", "paper_approval", "pass"}:
            decision = "pass"
        elif instruction == "watch":
            decision = "warn"
        else:
            decision = "observe"
        return GateResult(
            gate_id="ml_authority",
            layer="ml",
            decision=decision,
            authority="paper",
            enforced=decision == "block",
            reason="; ".join(str(reason) for reason in (layered.get("reasons") or [])[:4])
            or "layered model authority evaluated",
            size_cap_pct=final_size if decision == "cap" else None,
            inputs={
                "version": layered.get("version"),
                "runtime_effect": layered.get("runtime_effect"),
                "symbol": layered.get("symbol"),
                "action": layered.get("action"),
                "final_instruction": instruction,
                "final_size_pct": final_size,
            },
            outputs={
                "level_0_regime": layered.get("level_0_regime"),
                "level_1_expert_ensemble": layered.get("level_1_expert_ensemble"),
                "level_2_meta_label": layered.get("level_2_meta_label"),
                "level_3_sizing": layered.get("level_3_sizing"),
            },
        )

    evidence = account_state.get("ml_authority") or account_state.get("ml_authority_gate")
    evidence = evidence if isinstance(evidence, dict) else {}
    raw_decision = str(
        evidence.get("decision")
        or evidence.get("severity")
        or evidence.get("status")
        or evidence.get("result")
        or ""
    ).lower()
    if raw_decision in {"block", "blocked", "hard_block", "reject", "rejected"}:
        decision = "block"
    elif raw_decision in {"size_down", "reduce", "cap"}:
        decision = "cap"
    elif raw_decision in {"warn", "warning", "caution"}:
        decision = "warn"
    elif raw_decision in {"pass", "allow", "approved", "ok"}:
        decision = "pass"
    else:
        decision = "observe"
    return GateResult(
        gate_id="ml_authority",
        layer="ml",
        decision=decision,
        authority="none",
        enforced=False,
        reason=str(
            evidence.get("reason")
            or evidence.get("summary")
            or "ML authority evidence not present in account_state"
        ),
        size_cap_pct=evidence.get("size_cap_pct") or evidence.get("max_size_pct"),
        inputs=evidence,
        outputs={"trace_source": "account_state"},
    )
