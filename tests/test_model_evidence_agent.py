"""Observe-only enforcement and adversarial-graduation tests for the model
evidence agent. Providers are injected (no network), mirroring
test_ai_event_context_service.py."""

from __future__ import annotations

import json

from trading_bot.research.model_evidence_agent import (
    BAR_GATE_KEYS,
    FORBIDDEN_AUTHORITY_FIELDS,
    RESEARCH_RUNTIME_EFFECT,
    ModelEvidenceAgent,
    ModelEvidenceConfig,
    graduate,
)


def _clean_evidence(extra: dict | None = None) -> dict:
    payload = {
        "candidate_id": "cand_123",
        "summary": "Candidate clears every gate on the available diagnostics.",
        "gates": {
            key: {
                "status": "pass",
                "claim": f"{key} satisfied",
                "numeric_support": "lift=9.1pp; ev=+0.31%",
                "sample_size": "47 independent days",
            }
            for key in BAR_GATE_KEYS
        },
    }
    if extra:
        payload.update(extra)
    return payload


def _clean_redteam(refute: str | None = None) -> dict:
    gates = {key: {"refuted": False, "reason": "survives"} for key in BAR_GATE_KEYS}
    if refute:
        gates[refute] = {"refuted": True, "reason": "EV not net-of-cost at $531"}
    return {
        "recommendation": "worth_human_review",
        "confidence": "medium",
        "gates": gates,
    }


def _provider_factory(evidence: dict, redteam: dict):
    def _provider(*, system_context: str, instruction: str) -> str:
        # The red-team prompt is the only one that asks the model to REFUTE.
        return json.dumps(redteam if "REFUTE" in instruction else evidence)

    return _provider


def _agent(evidence: dict, redteam: dict) -> ModelEvidenceAgent:
    return ModelEvidenceAgent(
        config=ModelEvidenceConfig(enabled=True, provider_name="test_provider"),
        provider=_provider_factory(evidence, redteam),
    )


def _assert_observe_only(result: dict) -> None:
    assert result["runtime_effect"] == RESEARCH_RUNTIME_EFFECT
    assert result["evidence"]["runtime_effect"] == RESEARCH_RUNTIME_EFFECT
    assert result["red_team"]["runtime_effect"] == RESEARCH_RUNTIME_EFFECT


def test_clean_pass_graduates_and_is_observe_only():
    result = _agent(_clean_evidence(), _clean_redteam()).review({"diagnostics": "..."})
    _assert_observe_only(result)
    assert result["graduated"] is True


def test_red_team_refutation_blocks_graduation():
    result = _agent(_clean_evidence(), _clean_redteam(refute="net_cost_ev")).review({})
    _assert_observe_only(result)
    assert result["graduated"] is False
    # A refuted gate forces the recommendation to rejected regardless of the field.
    assert result["red_team"]["recommendation"] == "rejected"


def test_failing_evidence_gate_blocks_graduation():
    evidence = _clean_evidence()
    evidence["gates"]["discrimination"]["status"] = "insufficient"
    result = _agent(evidence, _clean_redteam()).review({})
    assert result["graduated"] is False
    assert "discrimination" in result["graduation_reason"]


def test_forbidden_authority_fields_are_stripped():
    # An LLM that tries to emit promotion/authority fields must not leak them.
    evidence = _clean_evidence({"promote": True, "live_status": "active"})
    result = _agent(evidence, _clean_redteam()).review({})
    serialized = json.dumps(result)
    for field in FORBIDDEN_AUTHORITY_FIELDS:
        assert f'"{field}"' not in serialized


def test_malformed_output_fails_closed():
    def _bad_provider(*, system_context: str, instruction: str) -> str:
        return "not json at all"

    agent = ModelEvidenceAgent(
        config=ModelEvidenceConfig(enabled=True, provider_name="test_provider"),
        provider=_bad_provider,
    )
    result = agent.review({})
    _assert_observe_only(result)
    # Refute-by-default: malformed red-team output blocks graduation.
    assert result["graduated"] is False
    assert all(result["red_team"]["gates"][key]["refuted"] is True for key in BAR_GATE_KEYS)


def test_disabled_agent_is_deterministic_and_never_graduates():
    result = ModelEvidenceAgent(config=ModelEvidenceConfig(enabled=False)).review({})
    _assert_observe_only(result)
    assert result["graduated"] is False
    assert result["evidence"]["provider"] == "deterministic_fallback"


def test_graduate_requires_all_gates():
    evidence = _clean_evidence()
    ok, _ = graduate(evidence, _clean_redteam())
    assert ok is True
    blocked, reason = graduate(evidence, _clean_redteam(refute="leakage_clean"))
    assert blocked is False
    assert "leakage_clean" in reason


# --------------------------------------------------------------------------- #
# Heterogeneous red-team panel
# --------------------------------------------------------------------------- #
def _evidence_only_provider(evidence: dict):
    def _provider(*, system_context: str, instruction: str) -> str:
        return json.dumps(evidence)

    return _provider


def _redteam_only_provider(redteam: dict):
    def _provider(*, system_context: str, instruction: str) -> str:
        return json.dumps(redteam)

    return _provider


def _raising_provider(*, system_context: str, instruction: str) -> str:
    raise RuntimeError("vendor unreachable")


def _panel_agent(panel: dict, *, min_survivors: int = 1) -> ModelEvidenceAgent:
    return ModelEvidenceAgent(
        config=ModelEvidenceConfig(
            enabled=True,
            provider_name="evidence_vendor",
            redteam_min_survivors=min_survivors,
        ),
        provider=_evidence_only_provider(_clean_evidence()),
        redteam_panel=panel,
    )


def test_panel_any_vendor_refutation_blocks_and_records_dissent():
    panel = {
        "vendor_a": _redteam_only_provider(_clean_redteam()),
        "vendor_b": _redteam_only_provider(_clean_redteam(refute="leakage_clean")),
    }
    result = _panel_agent(panel).review({})
    _assert_observe_only(result)
    assert result["graduated"] is False
    assert result["red_team"]["recommendation"] == "rejected"
    dissent_gates = {d["gate"] for d in result["red_team"]["dissent"]}
    assert "leakage_clean" in dissent_gates


def test_panel_silent_vendor_is_non_voting_not_a_refutation():
    panel = {
        "vendor_a": _redteam_only_provider(_clean_redteam()),
        "vendor_b": _raising_provider,  # errors -> silent, must not block on its own
    }
    result = _panel_agent(panel, min_survivors=1).review({})
    assert result["graduated"] is True
    assert "vendor_b" in result["red_team"]["silent"]


def test_panel_quorum_blocks_when_all_vendors_silent():
    panel = {"vendor_a": _raising_provider, "vendor_b": _raising_provider}
    result = _panel_agent(panel, min_survivors=1).review({})
    assert result["graduated"] is False
    assert sorted(result["red_team"]["silent"]) == ["vendor_a", "vendor_b"]
