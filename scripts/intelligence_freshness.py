#!/usr/bin/env python3
"""
Freshness checks for generated intelligence files.

Used by:
- /status intelligence snapshot
- portfolio_rotation_manager safety checks
- CLI diagnostics

Fail-safe principle:
If a live trading decision depends on generated intelligence and that file is
missing/stale/error, the live action should be blocked or degraded to observe.
"""

import json
from datetime import datetime
from pathlib import Path

import pytz

BASE_DIR = Path(__file__).resolve().parents[1]
ET = pytz.timezone("America/New_York")

FILES = {
    "strategy_memory": {
        "path": BASE_DIR / "strategy_memory.json",
        "max_age_minutes": 36 * 60,
    },
    "portfolio_replacement": {
        "path": BASE_DIR / "portfolio_replacement_memory.json",
        "max_age_minutes": 30,
    },
    "policy_backtest": {
        "path": BASE_DIR / "policy_backtest_summary.json",
        "max_age_minutes": 36 * 60,
    },
    "missed_opportunity": {
        "path": BASE_DIR / "missed_opportunity_memory.json",
        "max_age_minutes": 36 * 60,
    },
    "excursion": {
        "path": BASE_DIR / "excursion_memory.json",
        "max_age_minutes": 36 * 60,
    },
    "market_context": {
        "path": BASE_DIR / "market_context.json",
        "max_age_minutes": 24 * 60,
    },
}


def _now():
    return datetime.now(ET)


def _parse_generated_at(value):
    if not value:
        return None

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(str(value)[:19], fmt)
            return ET.localize(dt)
        except Exception:
            pass

    return None


def _load_json(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def freshness_for_file(name):
    cfg = FILES.get(name)
    if not cfg:
        return {
            "name": name,
            "status": "unknown",
            "fresh": False,
            "reason": f"unknown intelligence file key: {name}",
        }

    path = cfg["path"]
    max_age_minutes = int(cfg["max_age_minutes"])

    if not path.exists():
        return {
            "name": name,
            "path": str(path),
            "status": "missing",
            "fresh": False,
            "reason": f"{path.name} not found",
            "max_age_minutes": max_age_minutes,
        }

    obj = _load_json(path)
    if obj is None:
        return {
            "name": name,
            "path": str(path),
            "status": "error",
            "fresh": False,
            "reason": f"failed to parse {path.name}",
            "max_age_minutes": max_age_minutes,
        }

    generated_at = obj.get("generated_at")

    # market_context uses market_date instead of generated_at.
    if name == "market_context" and not generated_at:
        generated_at = obj.get("market_date")

    generated_dt = _parse_generated_at(generated_at)

    # Fallback to file mtime if generated_at is absent/unparseable.
    source = "generated_at"
    if generated_dt is None:
        try:
            generated_dt = datetime.fromtimestamp(path.stat().st_mtime, ET)
            source = "mtime"
        except Exception:
            return {
                "name": name,
                "path": str(path),
                "status": "error",
                "fresh": False,
                "reason": "could not determine timestamp",
                "generated_at": generated_at,
                "max_age_minutes": max_age_minutes,
            }

    age_minutes = (_now() - generated_dt).total_seconds() / 60.0

    if age_minutes <= max_age_minutes:
        status = "fresh"
        fresh = True
        reason = f"age {age_minutes:.1f}m <= max {max_age_minutes}m"
    else:
        status = "stale"
        fresh = False
        reason = f"age {age_minutes:.1f}m > max {max_age_minutes}m"

    return {
        "name": name,
        "path": str(path),
        "status": status,
        "fresh": fresh,
        "reason": reason,
        "generated_at": generated_at,
        "timestamp_source": source,
        "age_minutes": round(age_minutes, 1),
        "max_age_minutes": max_age_minutes,
    }


def get_intelligence_freshness():
    return {name: freshness_for_file(name) for name in FILES}


def is_fresh(name):
    return bool(freshness_for_file(name).get("fresh"))


if __name__ == "__main__":
    print(json.dumps(get_intelligence_freshness(), indent=2, sort_keys=True))
