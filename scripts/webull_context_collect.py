#!/usr/bin/env python3
"""Collect Webull screener-derived context and normalize it for market context."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from market_intelligence.webull_market_evidence import (  # noqa: E402
    DEFAULT_STATE_PATH as WEBULL_MARKET_STATE_PATH,
)
from market_intelligence.webull_market_evidence import normalize_webull_market_evidence_state
from market_intelligence.webull_morning_brief import (  # noqa: E402
    DEFAULT_STATE_PATH as WEBULL_MORNING_STATE_PATH,
)
from market_intelligence.webull_morning_brief import normalize_webull_morning_brief_state
from trading_bot.services.webull_market_data_service import (  # noqa: E402
    WebullCredentials,
    webull_credentials_from_env,
)

DEFAULT_PAGE_SIZE = 20


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _date_today() -> str:
    return datetime.now().date().isoformat()


def _float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(str(value).strip().replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _float(value)
    return int(number) if number is not None else None


def _response_payload(response: Any) -> Any:
    status_code = getattr(response, "status_code", None)
    if status_code is not None and int(status_code) >= 400:
        text = getattr(response, "text", "")
        raise RuntimeError(f"Webull response status={status_code} body={text}")
    json_method = getattr(response, "json", None)
    if callable(json_method):
        return json_method()
    return response


def _payload_rows(payload: Any) -> list[dict[str, Any]]:
    payload = _response_payload(payload)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "items", "results", "rows", "list"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        nested = payload.get("data")
        if isinstance(nested, dict):
            return _payload_rows(nested)
    return []


def _build_client(credentials: WebullCredentials) -> Any:
    from webull.core.client import ApiClient  # type: ignore
    from webull.data.data_client import DataClient  # type: ignore

    previous_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        api_client = ApiClient(
            credentials.api_key,
            credentials.api_secret,
            credentials.region.lower(),
        )
        setattr(api_client, "_stream_logger_set", True)
        setattr(api_client, "_file_logger_set", True)
        return DataClient(api_client)
    finally:
        logging.disable(previous_disable)


def _try_screener_call(callable_obj: Any, *args: Any) -> list[dict[str, Any]]:
    response = callable_obj(*args)
    return _payload_rows(response)


def collect_webull_screener_payload(
    *,
    credentials: WebullCredentials | None = None,
    rank_type: str = "PRE_MARKET",
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    credentials = credentials or webull_credentials_from_env()
    if not credentials.configured:
        raise RuntimeError(
            "WEBULL_API_KEY/WEBULL_API_SECRET/WEBULL_ACCOUNT_ID are not fully configured"
        )

    client = _build_client(credentials)
    screener = client.screener
    rank_types = [rank_type]
    if rank_type != "DAY_1":
        rank_types.append("DAY_1")

    last_error: Exception | None = None
    for candidate_rank_type in rank_types:
        try:
            top_active = _try_screener_call(
                screener.get_most_active,
                "US_STOCK",
                "VOLUME",
                "VOLUME",
                1,
                page_size,
                "DESC",
            )
            gainers = _try_screener_call(
                screener.get_gainers_losers,
                candidate_rank_type,
                "US_STOCK",
                "CHANGE_RATIO",
                1,
                page_size,
                "DESC",
            )
            losers = _try_screener_call(
                screener.get_gainers_losers,
                candidate_rank_type,
                "US_STOCK",
                "CHANGE_RATIO",
                1,
                page_size,
                "ASC",
            )
            return {
                "source": "webull_openapi_screener_proxy",
                "published_at": _utc_now(),
                "rank_type": candidate_rank_type,
                "screeners": {
                    "top_active": top_active,
                    "gainers": gainers,
                    "losers": losers,
                },
                "raw_rankings": {
                    "top_active": top_active,
                    "gainers": gainers,
                    "losers": losers,
                },
            }
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Webull screener collection failed: {last_error}")


def _symbol(row: dict[str, Any]) -> str | None:
    value = row.get("symbol") or row.get("ticker")
    if isinstance(value, str) and value.strip():
        return value.strip().upper()
    return None


def _change_pct(row: dict[str, Any]) -> float | None:
    change = _float(
        row.get("change_pct")
        or row.get("change_ratio")
        or row.get("changeRatio")
        or row.get("pct_change")
    )
    if change is None:
        return None
    if abs(change) <= 3:
        return round(change * 100.0, 4)
    return round(change, 4)


def _row_name(row: dict[str, Any]) -> str:
    return str(row.get("name") or row.get("symbol") or "unknown").strip()


def _row_price(row: dict[str, Any]) -> float | None:
    return _float(row.get("price") or row.get("close") or row.get("last"))


def _add_symbol(
    symbols: dict[str, dict[str, Any]],
    *,
    row: dict[str, Any],
    bucket: str,
    rank: int,
) -> None:
    symbol = _symbol(row)
    if not symbol:
        return
    pct = _change_pct(row)
    if bucket == "gainers":
        signal = "webull_top_gainer"
        bias = "supportive"
    elif bucket == "losers":
        signal = "webull_top_loser"
        bias = "caution"
    else:
        signal = "webull_top_active"
        bias = "neutral"
    entry = symbols.setdefault(
        symbol,
        {
            "brief_signal": signal,
            "event_bias": bias,
            "ranking_tags": [],
            "reason": f"Webull {bucket} rank {rank}: {_row_name(row)}",
        },
    )
    if bucket != "top_active" or entry.get("brief_signal") == "webull_top_active":
        entry["brief_signal"] = signal
        entry["event_bias"] = bias
        entry["reason"] = f"Webull {bucket} rank {rank}: {_row_name(row)}"
    entry["pct_change"] = pct
    entry["price"] = _row_price(row)
    entry["attention_rank"] = min(_int(entry.get("attention_rank")) or rank, rank)
    entry["attention_count"] = _int(row.get("volume")) or _int(row.get("turnover"))
    entry["ranking_tags"].append({"bucket": bucket, "rank": rank})


def build_morning_brief_payload(
    market_payload: dict[str, Any],
    *,
    brief_date: str,
) -> dict[str, Any]:
    screeners = market_payload.get("screeners") or {}
    symbols: dict[str, dict[str, Any]] = {}
    for bucket in ("top_active", "gainers", "losers"):
        rows = screeners.get(bucket) if isinstance(screeners, dict) else []
        if not isinstance(rows, list):
            continue
        for rank, row in enumerate((r for r in rows if isinstance(r, dict)), start=1):
            _add_symbol(symbols, row=row, bucket=bucket, rank=rank)

    return {
        "source": "webull_openapi_screener_proxy",
        "brief_date": brief_date,
        "published_at": market_payload.get("published_at") or _utc_now(),
        "macro_read": "mixed_neutral",
        "calendar": {},
        "index_futures": {},
        "technical_signal_balance": {},
        "news": [],
        "symbols": symbols,
        "raw_rankings": market_payload.get("raw_rankings") or screeners,
        "notes": (
            "Webull OpenAPI exposes screener rankings, not the app Morning Brief panel; "
            "this is normalized as morning-brief-compatible non-authoritative context."
        ),
    }


def build_market_evidence_payload(market_payload: dict[str, Any]) -> dict[str, Any]:
    screeners = market_payload.get("screeners") or {}
    attention_symbols = {}
    top_active = screeners.get("top_active") if isinstance(screeners, dict) else []
    if isinstance(top_active, list):
        for rank, row in enumerate((r for r in top_active if isinstance(r, dict)), start=1):
            symbol = _symbol(row)
            if not symbol:
                continue
            attention_symbols[symbol] = {
                "rank": rank,
                "attention_count": _int(row.get("volume")) or _int(row.get("turnover")),
            }
    return {
        "source": "webull_openapi_screener_proxy",
        "published_at": market_payload.get("published_at") or _utc_now(),
        "screeners": screeners,
        "attention": {"symbols": attention_symbols},
        "news": {"summaries": []},
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _maybe_delegate_to_webull_venv(argv: list[str]) -> int | None:
    if os.getenv("WEBULL_CONTEXT_COLLECT_CHILD") == "1":
        return None
    try:
        import webull  # noqa: F401

        return None
    except Exception:
        python = ROOT / "venv-webull/bin/python"
        if not python.exists():
            return None
        env = dict(os.environ)
        env["WEBULL_CONTEXT_COLLECT_CHILD"] = "1"
        completed = subprocess.run([str(python), __file__, *argv], cwd=ROOT, env=env)
        return completed.returncode


def main() -> int:
    delegated = _maybe_delegate_to_webull_venv(sys.argv[1:])
    if delegated is not None:
        return delegated

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=_date_today())
    parser.add_argument("--rank-type", default=os.getenv("WEBULL_SCREENER_RANK_TYPE", "PRE_MARKET"))
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument(
        "--raw-input", help="Use a fixture/raw Webull screener payload instead of API."
    )
    parser.add_argument("--morning-output")
    parser.add_argument("--market-output")
    parser.add_argument("--morning-state-output", default=str(WEBULL_MORNING_STATE_PATH))
    parser.add_argument("--market-state-output", default=str(WEBULL_MARKET_STATE_PATH))
    args = parser.parse_args()

    morning_output = _resolve(
        Path(args.morning_output or f"data/webull/morning_brief_{args.date}.json")
    )
    market_output = _resolve(
        Path(args.market_output or f"data/webull/market_evidence_{args.date}.json")
    )
    morning_state_output = _resolve(Path(args.morning_state_output))
    market_state_output = _resolve(Path(args.market_state_output))

    if args.raw_input:
        raw_path = Path(args.raw_input)
        if not raw_path.is_absolute():
            raw_path = ROOT / raw_path
        market_payload = json.loads(raw_path.read_text())
    else:
        market_payload = collect_webull_screener_payload(
            rank_type=args.rank_type,
            page_size=args.page_size,
        )

    morning_payload = build_morning_brief_payload(market_payload, brief_date=args.date)
    market_evidence_payload = build_market_evidence_payload(market_payload)
    _write_json(morning_output, morning_payload)
    _write_json(market_output, market_evidence_payload)

    morning_state = normalize_webull_morning_brief_state(morning_payload)
    market_state = normalize_webull_market_evidence_state(market_evidence_payload)
    _write_json(morning_state_output, morning_state)
    _write_json(market_state_output, market_state)

    print(
        "Wrote Webull context "
        f"morning_symbols={len(morning_state.get('symbols') or {})} "
        f"market_symbols={(market_state.get('coverage') or {}).get('symbol_count', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
