#!/usr/bin/env python3
"""Observe-only orchestrator: model-promotion evidence -> Claude evidence pass
-> Claude adversarial red-team -> Bar-structured artifact.

This is the fast half of the model-evidence pipeline. It does NOT rebuild the
heavy diagnostics payload -- that is materialized separately by
``pipeline/model_evidence_payload_export.py`` into a cached columnar export.
This job reads that cached payload, optionally triggers a guarded retrain
first, then runs the two-pass Claude review (evidence + heterogeneous red-team
panel) from ``trading_bot.research.model_evidence_agent``. Decoupling the build
keeps this job fast enough to finish in its slot and reliably write an artifact;
the old in-review build was I/O-starved and SIGTERM'd before it ever wrote one.

It cannot promote, size, approve, or alter live authority. Like
``post_session_review``, it is warn-only: a missing provider, a missing API
key, an LLM error, or a missing/stale payload cache degrades to a deterministic
skeleton and exits 0 so it never looks like a failed runtime job. But a
fail-open run is never silent: it always still writes the artifact, records a
clear ``[WARN]`` and a health marker, and daily_summary independently surfaces a
missing artifact. Promotion stays a human decision through the rollout contract.

Wire it under the existing cron ``job_runner.py`` lock/ledger path in dark
hours (see run_model_evidence_review.sh), AFTER the payload-export job's slot;
never run it against live SQLite during market hours.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
for _p in (BASE_DIR, BASE_DIR / "src", BASE_DIR / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from trading_bot.research.model_evidence_agent import (  # noqa: E402
    OPENAI_COMPATIBLE_BASE_URLS,
    ModelEvidenceAgent,
    ModelEvidenceConfig,
    anthropic_research_provider,
    deterministic_review,
    openai_compatible_research_provider,
)
from trading_bot.services.model_evidence_payload_cache_service import (  # noqa: E402
    DEFAULT_CACHE_MAX_AGE_HOURS,
    read_payload_cache,
    write_health_marker,
)

REVIEW_SUBDIR = ("ops", "model_promotion_evidence", "ai_review")

# Where the vault's /learn routine reads immutable raw sources from. Mirrors the
# destination used by ops/export_for_vault.sh.
DEFAULT_VAULT_RAW_DIR = "/mnt/d/AI Brain/Trading Project/01-raw"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _emit_vault_markdown(payload: dict[str, Any], date: str, raw_dir: Path) -> Path:
    """Write a vault-ingestible raw source. The /learn routine compiles this into
    02-wiki; it is an observe-only candidate signal, never an authority change."""
    review = payload["review"]
    rt = review.get("red_team", {})
    ev = review.get("evidence", {})
    lines = [
        "---",
        f"title: Model Evidence Review {date}",
        "tags: [trading-bot/blocker, status/provisional]",
        f"generated_at: {payload['generated_at']}",
        f"runtime_effect: {payload['runtime_effect']}",
        f"graduated: {review.get('graduated')}",
        "---",
        "",
        f"# Model Evidence Review — {date}",
        "",
        f"> Observe-only AI review ({payload['agent']}). "
        f"Graduated to human review: **{review.get('graduated')}** — "
        f"{review.get('graduation_reason')}. This grants no authority; "
        "promotion remains a human decision recorded in `30-decisions/`.",
        "",
        f"- Candidate: `{ev.get('candidate_id', 'unknown')}`",
        f"- Red-team panel: {rt.get('provider', 'n/a')} "
        f"({rt.get('confidence', 'n/a')}); recommendation: {rt.get('recommendation', 'n/a')}",
    ]
    silent = rt.get("silent") or []
    if silent:
        lines.append(f"- Silent (non-voting) panelists: {', '.join(silent)}")
    dissent = rt.get("dissent") or []
    if dissent:
        lines.append("- Cross-vendor dissent:")
        for d in dissent:
            lines.append(
                f"  - `{d['gate']}` — refuted by {', '.join(d['refuters'])}; "
                f"survived by {', '.join(d['survivors'])}"
            )
    lines += ["", "## Bar gates", ""]
    for key, gate in (ev.get("gates") or {}).items():
        verdict = rt.get("gates", {}).get(key, {})
        lines.append(
            f"- **{key}**: evidence=`{gate.get('status')}`, "
            f"red-team refuted=`{verdict.get('refuted')}` — {gate.get('claim', '')}"
        )
    lines += [
        "",
        "## Full review payload",
        "",
        "```json",
        json.dumps(payload, indent=2, sort_keys=True),
        "```",
        "",
    ]
    raw_dir.mkdir(parents=True, exist_ok=True)
    out = raw_dir / f"model-evidence-review-{date}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


# Heterogeneous panel presets: vendor -> (api-key env var, default model).
# All reachable through the OpenAI-compatible base URLs in the agent module.
# Models are easily overridden via MODEL_EVIDENCE_<VENDOR>_MODEL; a wrong/missing
# model just makes that panelist silent (non-voting), never fatal.
_VENDOR_DEFAULTS: dict[str, tuple[str | None, str]] = {
    "openai": ("OPENAI_API_KEY", "gpt-5.1"),
    "glm": ("GLM_API_KEY", "glm-4.6"),
    "deepseek": ("DEEPSEEK_API_KEY", "deepseek-reasoner"),
    "qwen": ("DASHSCOPE_API_KEY", "qwen-max"),
    "kimi": ("MOONSHOT_API_KEY", "kimi-k2"),
    "ollama": (None, "llama3.1"),  # local; no key
}


def _build_redteam_panel(anthropic_model: str, anthropic_effort: str) -> dict:
    """Anthropic is always a panelist; add any OpenAI-compatible vendor listed in
    MODEL_EVIDENCE_PANEL whose API key is present (ollama needs no key)."""
    panel = {
        f"anthropic:{anthropic_model}": anthropic_research_provider(
            model=anthropic_model, effort=anthropic_effort
        )
    }
    # Each token is "vendor" (uses the env/default model) or "vendor/model" to
    # pin a specific model — the latter lets you enroll several local models
    # (e.g. ollama/llama3.1,ollama/qwen2.5) as distinct cross-family panelists.
    requested = [
        v.strip().lower()
        for v in os.environ.get("MODEL_EVIDENCE_PANEL", "").split(",")
        if v.strip()
    ]
    for token in requested:
        vendor, _, model_override = token.partition("/")
        if vendor not in _VENDOR_DEFAULTS or vendor not in OPENAI_COMPATIBLE_BASE_URLS:
            continue
        key_env, default_model = _VENDOR_DEFAULTS[vendor]
        if key_env and not os.environ.get(key_env, "").strip():
            continue  # no key -> skip rather than enroll a guaranteed-silent panelist
        model = model_override or os.environ.get(
            f"MODEL_EVIDENCE_{vendor.upper()}_MODEL", default_model
        )
        base_url = os.environ.get(
            f"MODEL_EVIDENCE_{vendor.upper()}_BASE_URL", OPENAI_COMPATIBLE_BASE_URLS[vendor]
        )
        panel[f"{vendor}:{model}"] = openai_compatible_research_provider(
            base_url=base_url, model=model, api_key_env=key_env
        )
    return panel


def _build_agent() -> ModelEvidenceAgent:
    """Enable the AI passes only when explicitly opted in AND a key is present.

    Defaults to disabled (deterministic) so the job is safe to schedule before
    credentials/quotas are set up.
    """
    opted_in = os.environ.get("MODEL_EVIDENCE_REVIEW_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    if not (opted_in and has_key):
        return ModelEvidenceAgent(config=ModelEvidenceConfig(enabled=False))

    model = os.environ.get("MODEL_EVIDENCE_MODEL", "claude-opus-4-8")
    redteam_effort = os.environ.get("MODEL_EVIDENCE_REDTEAM_EFFORT", "high")
    try:
        min_survivors = int(os.environ.get("MODEL_EVIDENCE_MIN_SURVIVORS", "1"))
    except ValueError:
        min_survivors = 1
    config = ModelEvidenceConfig(
        enabled=True,
        provider_name=f"anthropic:{model}",
        evidence_model=model,
        redteam_model=model,
        redteam_effort=redteam_effort,
        redteam_min_survivors=min_survivors,
    )
    evidence_provider = anthropic_research_provider(model=model, effort="high")
    redteam_panel = _build_redteam_panel(model, redteam_effort)
    return ModelEvidenceAgent(
        config=config, provider=evidence_provider, redteam_panel=redteam_panel
    )


def _maybe_retrain(date: str) -> dict[str, Any]:
    """Run the guarded, observe-only retrain via subprocess so it keeps its own
    fcntl lock, memory cap, and runtime guard. Registry writes stay
    metadata-only; this never promotes."""
    cmd = [
        sys.executable,
        str(BASE_DIR / "pipeline" / "retrain.py"),
        "--date",
        date,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("MODEL_EVIDENCE_RETRAIN_TIMEOUT", "1800")),
        )
        return {
            "ran": True,
            "returncode": proc.returncode,
            "stderr_tail": (proc.stderr or "")[-500:],
        }
    except Exception as exc:  # warn-only — retrain failure must not fail the review
        return {"ran": False, "error": str(exc)[:240]}


def _cache_max_age_hours() -> float:
    try:
        return float(os.environ.get("MODEL_EVIDENCE_CACHE_MAX_AGE_HOURS", ""))
    except ValueError:
        return DEFAULT_CACHE_MAX_AGE_HOURS


def run(
    date: str,
    *,
    retrain: bool,
    write: bool,
    emit_vault: bool = True,
    base_dir: Path = BASE_DIR,
) -> dict[str, Any]:
    retrain_result = _maybe_retrain(date) if retrain else {"ran": False, "skipped": True}

    # Read the materialized payload instead of rebuilding it. A missing or stale
    # cache fails open to the deterministic skeleton WITH a surfaced warning —
    # never a silent no-op.
    cache = read_payload_cache(base_dir, date=date, max_age_hours=_cache_max_age_hours())
    warnings: list[str] = []
    if not cache.ok:
        warnings.append(
            f"payload cache unavailable ({cache.reason}); run "
            "pipeline/model_evidence_payload_export.py — falling back to deterministic review"
        )
        review = deterministic_review(f"payload cache unavailable: {cache.reason}")
        agent_used = "deterministic_fallback"
    elif cache.stale:
        age = f"{cache.age_hours:.1f}h" if cache.age_hours is not None else "unknown age"
        warnings.append(
            f"payload cache is stale ({age}); the export job may have failed — "
            "falling back to deterministic review"
        )
        review = deterministic_review(f"payload cache stale ({age})")
        agent_used = "deterministic_fallback"
    else:
        agent = _build_agent()
        review = agent.review(cache.diagnostics)
        agent_used = agent.config.provider_name

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_date": date,
        "runtime_effect": review["runtime_effect"],
        "agent": agent_used,
        "retrain": retrain_result,
        "cache_status": cache.summary(),
        "warnings": warnings,
        "review": review,
    }

    if write:
        out_dir = base_dir.joinpath(*REVIEW_SUBDIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date}_{_utc_stamp()}.json"
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        payload["artifact"] = str(out_path)

    if emit_vault:
        raw_dir = os.environ.get("MODEL_EVIDENCE_VAULT_RAW_DIR", DEFAULT_VAULT_RAW_DIR).strip()
        if raw_dir:
            try:
                payload["vault_source"] = str(_emit_vault_markdown(payload, date, Path(raw_dir)))
            except Exception as exc:  # warn-only — vault drop is best-effort
                payload["vault_source_error"] = str(exc)[:240]

    # Record the outcome so a degraded/fail-open run is visible to a human even
    # though an artifact was still written. Best-effort; never fails the job.
    try:
        write_health_marker(
            base_dir,
            {
                "status": _run_status(review, warnings),
                "target_date": date,
                "generated_at": payload["generated_at"],
                "agent": agent_used,
                "graduated": review.get("graduated"),
                "artifact": payload.get("artifact"),
                "cache_status": payload["cache_status"],
                "warnings": warnings,
            },
        )
    except Exception:  # noqa: BLE001 — health marker is best-effort
        pass

    return payload


def _run_status(review: dict[str, Any], warnings: list[str]) -> str:
    if warnings:
        return "degraded_fail_open"
    if review.get("graduated"):
        return "graduated_candidate"
    return "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="Target date label for the artifact (default: today UTC).",
    )
    parser.add_argument(
        "--retrain",
        action="store_true",
        help="Run the guarded observe-only retrain first (default: off).",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print the review but do not write an artifact.",
    )
    parser.add_argument(
        "--no-vault",
        action="store_true",
        help="Do not write the vault-ingestible raw source into Trading Project/01-raw.",
    )
    args = parser.parse_args(argv)

    payload = run(
        args.date,
        retrain=args.retrain,
        write=not args.no_write,
        emit_vault=not args.no_vault,
    )

    review = payload["review"]
    for warning in payload.get("warnings", []):
        print(f"[model-evidence-review][WARN] {args.date} {warning}")
    print(
        f"[model-evidence-review] {args.date} agent={payload['agent']} "
        f"graduated={review.get('graduated')} reason={review.get('graduation_reason')} "
        f"cache={payload['cache_status'].get('reason')} "
        f"artifact={payload.get('artifact', 'NOT WRITTEN')}"
    )
    # Warn-only: always exit 0 so a no-graduation result is not a failed job.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
