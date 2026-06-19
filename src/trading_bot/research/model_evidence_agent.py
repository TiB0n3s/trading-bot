"""Adversarial, observe-only AI review of model-promotion evidence.

This module turns the numeric diagnostics already produced by
``model_promotion_evidence_service`` into a Bar-structured evidence packet and
then runs a second, adversarial Claude pass that tries to *refute* it. It is
deliberately non-authoritative: it can summarize and critique evidence, but it
cannot promote a model, load an artifact, size, approve, block, or alter live
trading authority. Promotion remains a human decision recorded in the rollout
contract.

The design mirrors ``services/ai_event_context_service.py``: an injectable
provider abstraction (so tests run with no network), JSON-only response
contracts validated on our side, and a deterministic fail-open path so a missing
``anthropic`` package or API key never fails a scheduled job.

The Bar (from the Trading Project operating rules) is the acceptance test, and
its five gates are the spine of every output here:

1. discrimination  - measured decile lift >= 8pp, not just calibration
2. regime_robust   - holds across regimes; survives a blocked null on clustered data
3. leakage_clean   - point-in-time integrity audited against primary sources
4. net_cost_ev     - net-of-cost EV >= +0.25% at the real account size (~$531)
5. enough_days     - enough independent days to trust it
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable

MODEL_EVIDENCE_VERSION = "model_evidence_agent_v1"

# The only runtime effect this module is ever allowed to claim. Mirrors the
# observe-only governance lane (ai_leverage_audit.md, model-governance). The
# enforcement test asserts every output carries exactly this value.
RESEARCH_RUNTIME_EFFECT = "observe_only_no_live_authority"

# Fields an authority-bearing component might emit. This module must never
# produce any of them; ``_strip_authority_fields`` removes them defensively and
# the test asserts they never appear.
FORBIDDEN_AUTHORITY_FIELDS = frozenset(
    {
        "promote",
        "promoted",
        "promotion",
        "approve",
        "approved",
        "approval",
        "live",
        "live_status",
        "size",
        "sizing",
        "order",
        "execute",
        "registry_write",
        "set_live",
    }
)

# The five Bar gates, in evaluation order. Keep keys stable: schemas, prompts,
# and graduation logic all index on them.
BAR_GATES: tuple[tuple[str, str], ...] = (
    ("discrimination", "Measured decile lift >= 8pp, not merely good calibration."),
    ("regime_robust", "Holds across regimes and survives a blocked null on clustered data."),
    ("leakage_clean", "Point-in-time integrity audited against primary sources."),
    ("net_cost_ev", "Net-of-cost EV >= +0.25% at the real account size (~$531)."),
    ("enough_days", "Enough independent days to trust the estimate."),
)
BAR_GATE_KEYS: tuple[str, ...] = tuple(key for key, _ in BAR_GATES)

# A provider takes a cached system context plus a per-call instruction and
# returns the model's raw text (expected to be JSON). Splitting the two lets the
# large diagnostic packet be sent once and prompt-cached across both passes.
ResearchProvider = Callable[..., str]

_EVIDENCE_GATE_STATUSES = {"pass", "fail", "insufficient"}
_REDTEAM_RECOMMENDATIONS = {"worth_human_review", "rejected"}


@dataclass(frozen=True)
class ModelEvidenceConfig:
    enabled: bool = False
    provider_name: str = "disabled"
    evidence_model: str = "claude-opus-4-8"
    redteam_model: str = "claude-opus-4-8"
    # 'high' is the sweet spot; bump the red-team to 'max' when correctness
    # matters more than cost.
    evidence_effort: str = "high"
    redteam_effort: str = "high"
    # Minimum number of panelists that must affirmatively survive a gate (with
    # zero refuters) for that gate to survive the panel. Guards against a gate
    # "surviving" only because every panelist errored out.
    redteam_min_survivors: int = 1


# --------------------------------------------------------------------------- #
# Validation helpers (plain-dict, no Pydantic dependency — matches the event
# service so the fallback path has no heavy imports).
# --------------------------------------------------------------------------- #
def _safe_str(value: Any, default: str = "unknown", max_len: int = 600) -> str:
    text = str(value if value is not None else default).strip()
    return (text or default)[:max_len]


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "refuted", "pass"}
    return default


def _load_payload(payload: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    try:
        loaded = json.loads(str(payload))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _strip_authority_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Recursively drop any authority-bearing keys an LLM might invent."""
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key in FORBIDDEN_AUTHORITY_FIELDS:
            continue
        if isinstance(value, dict):
            value = _strip_authority_fields(value)
        cleaned[key] = value
    return cleaned


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
def build_evidence_prompt() -> str:
    gate_lines = "\n".join(f"- {key}: {desc}" for key, desc in BAR_GATES)
    return (
        "You are reviewing observe-only model-promotion evidence for a paper-trading "
        "system. Numeric attribution is primary; you narrate it, you do not invent it. "
        "You have NO authority to promote, approve, size, or alter live trading. "
        "Assess the candidate against each Bar gate using ONLY the diagnostics in the "
        "packet. If the packet lacks the numbers a gate needs, mark that gate "
        "'insufficient' — never assume.\n\n"
        f"Bar gates:\n{gate_lines}\n\n"
        "Return JSON only with keys: candidate_id (string), summary (string), "
        "gates (object keyed by the gate names above; each value an object with "
        "keys status ['pass'|'fail'|'insufficient'], claim (string), "
        "numeric_support (string quoting the figures), sample_size (string))."
    )


def build_redteam_prompt() -> str:
    gate_lines = "\n".join(f"- {key}: {desc}" for key, desc in BAR_GATES)
    return (
        "You are an adversarial reviewer. Your job is to REFUTE the evidence packet's "
        "claim that this candidate is worth promoting. Default to refuted=true for any "
        "gate unless the packet's numbers clearly and independently establish it. "
        "Hunt specifically for: calibration dressed up as discrimination; regime "
        "fragility or a result that would not survive a blocked null on clustered "
        "data; point-in-time leakage (feature_available_at after the prediction "
        "cutoff); EV that is positive frictionless but not net-of-cost at the real "
        "~$531 account; and too few independent days. You have NO authority to "
        "promote or approve anything; you only decide whether a human should spend "
        "time reviewing this.\n\n"
        f"Bar gates:\n{gate_lines}\n\n"
        "Return JSON only with keys: recommendation "
        "['worth_human_review'|'rejected'], confidence (string), "
        "gates (object keyed by the gate names above; each value an object with "
        "keys refuted (boolean) and reason (string)). A candidate is "
        "'worth_human_review' only if NO gate is refuted."
    )


# --------------------------------------------------------------------------- #
# Normalization (forces non-authority fields onto every output)
# --------------------------------------------------------------------------- #
def _empty_gates(default_status: str) -> dict[str, Any]:
    return {
        key: {
            "status": default_status,
            "claim": "",
            "numeric_support": "",
            "sample_size": "",
        }
        for key in BAR_GATE_KEYS
    }


def normalize_evidence(payload: dict[str, Any] | str, *, provider_name: str) -> dict[str, Any]:
    raw = _strip_authority_fields(_load_payload(payload))
    gates_raw = raw.get("gates") if isinstance(raw.get("gates"), dict) else {}
    gates = _empty_gates("insufficient")
    for key in BAR_GATE_KEYS:
        entry = gates_raw.get(key) if isinstance(gates_raw.get(key), dict) else {}
        status = _safe_str(entry.get("status"), default="insufficient", max_len=20)
        gates[key] = {
            "status": status if status in _EVIDENCE_GATE_STATUSES else "insufficient",
            "claim": _safe_str(entry.get("claim"), default=""),
            "numeric_support": _safe_str(entry.get("numeric_support"), default=""),
            "sample_size": _safe_str(entry.get("sample_size"), default=""),
        }
    return {
        "version": MODEL_EVIDENCE_VERSION,
        "provider": provider_name,
        "runtime_effect": RESEARCH_RUNTIME_EFFECT,
        "candidate_id": _safe_str(raw.get("candidate_id"), default="unknown", max_len=120),
        "summary": _safe_str(raw.get("summary"), default="No evidence summary available."),
        "gates": gates,
    }


def normalize_redteam(payload: dict[str, Any] | str, *, provider_name: str) -> dict[str, Any]:
    raw = _strip_authority_fields(_load_payload(payload))
    gates_raw = raw.get("gates") if isinstance(raw.get("gates"), dict) else {}
    gates: dict[str, Any] = {}
    any_refuted = False
    for key in BAR_GATE_KEYS:
        entry = gates_raw.get(key) if isinstance(gates_raw.get(key), dict) else {}
        # Refute-by-default: a missing or malformed verdict counts as refuted.
        refuted = _as_bool(entry.get("refuted"), default=True) if entry else True
        any_refuted = any_refuted or refuted
        gates[key] = {
            "refuted": refuted,
            "reason": _safe_str(entry.get("reason"), default="no verdict returned"),
        }
    recommendation = _safe_str(raw.get("recommendation"), default="rejected", max_len=24)
    if recommendation not in _REDTEAM_RECOMMENDATIONS:
        recommendation = "rejected"
    # A red-team that refutes any gate cannot recommend review, regardless of
    # what the model wrote in the recommendation field.
    if any_refuted:
        recommendation = "rejected"
    return {
        "version": MODEL_EVIDENCE_VERSION,
        "provider": provider_name,
        "runtime_effect": RESEARCH_RUNTIME_EFFECT,
        "recommendation": recommendation,
        "confidence": _safe_str(raw.get("confidence"), default="unknown", max_len=24),
        "gates": gates,
    }


def aggregate_redteam(
    panel_results: dict[str, dict[str, Any] | None],
    *,
    min_survivors: int = 1,
) -> dict[str, Any]:
    """Combine a heterogeneous red-team panel into one verdict.

    Strict on refutation, robust to flaky panelists: a gate survives only if NO
    responding panelist refutes it AND at least ``min_survivors`` panelists
    affirmatively survive it. A panelist that errored (``None``) is recorded as
    a non-vote — it never fabricates a refutation, but it does not count toward
    the survivor quorum either. Per-panelist verdicts and cross-vendor dissent
    are preserved for the human reviewer.
    """
    panelists = sorted(panel_results)
    responded = [name for name in panelists if panel_results.get(name) is not None]
    silent = [name for name in panelists if panel_results.get(name) is None]

    gates: dict[str, Any] = {}
    dissent: list[dict[str, Any]] = []
    for key in BAR_GATE_KEYS:
        refuters: list[str] = []
        survivors: list[str] = []
        reasons: list[str] = []
        for name in responded:
            entry = panel_results[name].get("gates", {}).get(key, {})  # type: ignore[union-attr]
            refuted = bool(entry.get("refuted", True))
            if refuted:
                refuters.append(name)
                reasons.append(
                    f"{name}: {_safe_str(entry.get('reason'), default='refuted', max_len=160)}"
                )
            else:
                survivors.append(name)
        gate_refuted = bool(refuters) or len(survivors) < max(1, min_survivors)
        if refuters and survivors:
            dissent.append({"gate": key, "refuters": refuters, "survivors": survivors})
        if not refuters and len(survivors) < max(1, min_survivors):
            reasons.append(f"insufficient survivor quorum ({len(survivors)}/{min_survivors})")
        gates[key] = {
            "refuted": gate_refuted,
            "reason": "; ".join(reasons) or "survives panel",
            "refuters": refuters,
            "survivors": survivors,
        }

    any_refuted = any(gate["refuted"] for gate in gates.values())
    return {
        "version": MODEL_EVIDENCE_VERSION,
        "provider": "panel:" + ",".join(panelists),
        "runtime_effect": RESEARCH_RUNTIME_EFFECT,
        "recommendation": "rejected" if any_refuted else "worth_human_review",
        "confidence": f"{len(responded)}/{len(panelists)} panelists responded",
        "min_survivors": min_survivors,
        "responded": responded,
        "silent": silent,
        "dissent": dissent,
        "gates": gates,
        "panelists": {name: panel_results.get(name) for name in panelists},
    }


def deterministic_review(reason: str) -> dict[str, Any]:
    """Fail-open skeleton when no provider is available. Never graduates."""
    return {
        "version": MODEL_EVIDENCE_VERSION,
        "runtime_effect": RESEARCH_RUNTIME_EFFECT,
        "evidence": {
            "version": MODEL_EVIDENCE_VERSION,
            "provider": "deterministic_fallback",
            "runtime_effect": RESEARCH_RUNTIME_EFFECT,
            "candidate_id": "unknown",
            "summary": f"AI review unavailable: {reason}. Inspect numeric diagnostics directly.",
            "gates": _empty_gates("insufficient"),
        },
        "red_team": {
            "version": MODEL_EVIDENCE_VERSION,
            "provider": "deterministic_fallback",
            "runtime_effect": RESEARCH_RUNTIME_EFFECT,
            "recommendation": "rejected",
            "confidence": "none",
            "gates": {key: {"refuted": True, "reason": "no red-team run"} for key in BAR_GATE_KEYS},
        },
        "graduated": False,
        "graduation_reason": f"no AI review performed ({reason})",
    }


def graduate(evidence: dict[str, Any], red_team: dict[str, Any]) -> tuple[bool, str]:
    """A candidate is worth a human's time only if every Bar gate passes the
    evidence pass AND survives the adversarial pass. This grants no authority;
    it only routes a refutable, sample-sized artifact to human review."""
    failing = [
        key
        for key in BAR_GATE_KEYS
        if evidence.get("gates", {}).get(key, {}).get("status") != "pass"
    ]
    if failing:
        return False, f"evidence gates not all passing: {', '.join(failing)}"
    refuted = [
        key for key in BAR_GATE_KEYS if red_team.get("gates", {}).get(key, {}).get("refuted", True)
    ]
    if refuted:
        return False, f"red-team refuted gates: {', '.join(refuted)}"
    if red_team.get("recommendation") != "worth_human_review":
        return False, "red-team did not recommend human review"
    return True, "all Bar gates pass evidence and survive adversarial review"


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
class ModelEvidenceAgent:
    """Runs the evidence pass, then a heterogeneous adversarial red-team panel,
    over one diagnostics packet.

    ``provider`` runs the evidence pass and, if no ``redteam_panel`` is given,
    is also the sole red-team panelist (single-vendor back-compat). Pass a
    ``redteam_panel`` of named providers (different models/vendors) for a
    cross-model red-team — any vendor's refutation blocks graduation.
    """

    def __init__(
        self,
        *,
        config: ModelEvidenceConfig | None = None,
        provider: ResearchProvider | None = None,
        redteam_panel: dict[str, ResearchProvider] | None = None,
    ):
        self.config = config or ModelEvidenceConfig()
        self.provider = provider
        if redteam_panel:
            self.redteam_panel = dict(redteam_panel)
        elif provider is not None:
            self.redteam_panel = {self.config.provider_name: provider}
        else:
            self.redteam_panel = {}

    def review(self, diagnostics: dict[str, Any]) -> dict[str, Any]:
        if not self.config.enabled or self.provider is None or not self.redteam_panel:
            return deterministic_review("provider disabled or unavailable")

        packet = json.dumps(diagnostics, sort_keys=True, default=str)
        try:
            evidence = normalize_evidence(
                self.provider(system_context=packet, instruction=build_evidence_prompt()),
                provider_name=self.config.provider_name,
            )
        except Exception as exc:  # fail open — a research job must never crash live cron
            return deterministic_review(f"evidence provider error: {str(exc)[:160]}")

        # Each panelist is independent: one erroring out is a non-vote, not a crash.
        panel_results: dict[str, dict[str, Any] | None] = {}
        for name, prov in self.redteam_panel.items():
            try:
                panel_results[name] = normalize_redteam(
                    prov(system_context=packet, instruction=build_redteam_prompt()),
                    provider_name=name,
                )
            except Exception as exc:
                panel_results[name] = None
                _ = exc  # recorded as a silent (non-voting) panelist below

        red_team = aggregate_redteam(panel_results, min_survivors=self.config.redteam_min_survivors)
        graduated, reason = graduate(evidence, red_team)
        return {
            "version": MODEL_EVIDENCE_VERSION,
            "runtime_effect": RESEARCH_RUNTIME_EFFECT,
            "evidence": evidence,
            "red_team": red_team,
            "graduated": graduated,
            "graduation_reason": reason,
        }


# --------------------------------------------------------------------------- #
# Anthropic provider (lazy, fail-open, Opus-4.8 request surface)
# --------------------------------------------------------------------------- #
def anthropic_research_provider(
    *,
    model: str = "claude-opus-4-8",
    effort: str = "high",
    max_tokens: int = 8000,
) -> ResearchProvider:
    """Return a lazy Anthropic provider for research evidence review.

    The large diagnostics packet is sent as a prompt-cached system block so the
    evidence pass and the adversarial pass (same packet, different instruction)
    share the cached prefix. Uses adaptive thinking and the effort parameter;
    sampling parameters are not sent (removed on Opus 4.8). Structured output is
    requested but the caller still validates and forces non-authority fields.
    """
    client: Any | None = None

    def _provider(*, system_context: str, instruction: str) -> str:
        nonlocal client
        if client is None:
            try:
                from anthropic import Anthropic
            except ModuleNotFoundError as exc:
                raise RuntimeError("anthropic is required for model evidence review") from exc
            client = Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            system=[
                {
                    "type": "text",
                    "text": (
                        "You review observe-only ML evidence for a frozen-authority "
                        "paper-trading system. You never grant authority.\n\n"
                        "DIAGNOSTICS_PACKET=" + system_context
                    ),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": instruction}],
        )
        parts = []
        for item in getattr(response, "content", []) or []:
            text = getattr(item, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts)

    return _provider


# Known OpenAI-compatible base URLs for heterogeneous red-team panelists. Any
# vendor exposing /chat/completions works; these are convenience presets.
OPENAI_COMPATIBLE_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyun.com/compatible-mode/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "ollama": "http://127.0.0.1:11434/v1",
}


def openai_compatible_research_provider(
    *,
    base_url: str,
    model: str,
    api_key_env: str | None = None,
    max_tokens: int = 4000,
    timeout: int = 120,
) -> ResearchProvider:
    """Return a lazy provider for any OpenAI-compatible /chat/completions API.

    Heterogeneity for the red-team panel: point this at GPT/Codex, GLM,
    DeepSeek, Qwen, Kimi, or a local Ollama model. Uses stdlib HTTP (no extra
    dependency) and the caller still validates and forces non-authority fields.
    Raises on missing key / transport error so the panel records it as a
    non-voting (silent) panelist rather than a fabricated verdict.
    """
    import json as _json
    import urllib.request

    def _provider(*, system_context: str, instruction: str) -> str:
        api_key = os.environ.get(api_key_env, "").strip() if api_key_env else ""
        if api_key_env and not api_key:
            raise RuntimeError(f"{api_key_env} not set for {model}")
        body = _json.dumps(
            {
                "model": model,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You review observe-only ML evidence for a "
                            "frozen-authority paper-trading system. You never "
                            "grant authority.\n\nDIAGNOSTICS_PACKET=" + system_context
                        ),
                    },
                    {"role": "user", "content": instruction},
                ],
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = _json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    return _provider
