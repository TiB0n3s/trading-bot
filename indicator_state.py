from __future__ import annotations

from typing import Sequence


def _normalize_actions(actions: Sequence[str], max_len: int = 10) -> list[str]:
    out: list[str] = []
    for action in actions[:max_len]:
        value = str(action).strip().lower()
        if value in {"buy", "sell"}:
            out.append(value)
    return out


def _leading_streak(actions: Sequence[str]) -> tuple[str | None, int]:
    if not actions:
        return None, 0

    first = actions[0]
    count = 0

    for action in actions:
        if action != first:
            break
        count += 1

    return first, count


def _previous_opposite_streak(actions: Sequence[str], current_action: str, start_idx: int) -> int:
    opposite = "sell" if current_action == "buy" else "buy"
    count = 0

    for action in actions[start_idx:]:
        if action != opposite:
            break
        count += 1

    return count


def compute_indicator_state(
    recent_actions: Sequence[str],
    *,
    buy_flip_min: int = 2,
    sell_flip_min: int = 2,
    confirmed_min: int = 3,
) -> dict:
    actions = _normalize_actions(recent_actions)

    if not actions:
        return {
            "direction": "neutral",
            "strength": "weak",
            "consecutive_count": 0,
            "last_signal": None,
            "flip_event": "none",
            "confirmed_entry": False,
            "confirmed_exit": False,
            "bullish_candidate": False,
            "bearish_candidate": False,
            "previous_opposite_count": 0,
        }

    current_action, consecutive_count = _leading_streak(actions)
    assert current_action in {"buy", "sell"}

    previous_opposite_count = _previous_opposite_streak(
        actions,
        current_action=current_action,
        start_idx=consecutive_count,
    )

    bullish_candidate = current_action == "buy" and consecutive_count >= 1
    bearish_candidate = current_action == "sell" and consecutive_count >= 1

    buy_flip = (
        current_action == "buy"
        and consecutive_count >= buy_flip_min
        and previous_opposite_count >= 1
    )
    sell_flip = (
        current_action == "sell"
        and consecutive_count >= sell_flip_min
        and previous_opposite_count >= 1
    )

    confirmed_entry = current_action == "buy" and consecutive_count >= confirmed_min
    confirmed_exit = current_action == "sell" and consecutive_count >= confirmed_min

    if current_action == "buy" and consecutive_count >= buy_flip_min:
        direction = "bullish"
    elif current_action == "sell" and consecutive_count >= sell_flip_min:
        direction = "bearish"
    else:
        direction = "neutral"

    if consecutive_count >= max(confirmed_min + 2, 5):
        strength = "confirmed"
    elif consecutive_count >= confirmed_min:
        strength = "developing"
    else:
        strength = "weak"

    flip_event = "buy_flip" if buy_flip else "sell_flip" if sell_flip else "none"

    return {
        "direction": direction,
        "strength": strength,
        "consecutive_count": consecutive_count,
        "last_signal": current_action,
        "flip_event": flip_event,
        "confirmed_entry": confirmed_entry,
        "confirmed_exit": confirmed_exit,
        "bullish_candidate": bullish_candidate,
        "bearish_candidate": bearish_candidate,
        "previous_opposite_count": previous_opposite_count,
    }

def is_fast_lane_buy_flip(trend: dict, required_buy_confirmations: int) -> bool:
    return (
        int(required_buy_confirmations) == 2
        and trend.get("direction") == "bullish"
        and trend.get("last_signal") == "buy"
        and trend.get("flip_event") == "buy_flip"
        and int(trend.get("consecutive_count") or 0) >= 2
    )

def is_fast_lane_sell_flip(trend: dict, required_sell_confirmations: int) -> bool:
    return (
        int(required_sell_confirmations) == 2
        and trend.get("direction") == "bearish"
        and trend.get("last_signal") == "sell"
        and trend.get("flip_event") == "sell_flip"
        and int(trend.get("consecutive_count") or 0) >= 2
    )