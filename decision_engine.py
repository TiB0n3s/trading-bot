import os
import json
import logging
from anthropic import Anthropic
from symbols_config import APPROVED_SYMBOLS_CSV
from pnl import get_daily_realized_pnl

logger = logging.getLogger(__name__)
client = Anthropic()

TRADING_RULES = '''
You are a risk-aware trading decision engine.
Evaluate signals and respond with JSON only.

HARD RULES:
- Max position size: 2% of account balance per individual buy order (see trend exception below)
- Max total exposure per symbol: 4% of account balance — if current_symbol_position value (qty * current_price) already exceeds 4% of balance, reject any further buy signals for that symbol
- Daily loss limit: reject BUY signals if down 3% today; SELL/close signals must remain allowed so the bot can reduce exposure
- Only trade 9:30 AM to 4:00 PM Eastern Time
- Max 12 open positions at any time (this limit applies ONLY to opening new positions; sell/close signals must always be approved regardless of current position count)
- Approved symbols only: {APPROVED_SYMBOLS_CSV}
- Signal source must be TradingPilotAI

TREND TABLE GUIDANCE:
The account state includes a trend_table dict keyed by symbol. Each entry has:
  direction: "bullish", "bearish", or "neutral"
  strength: "confirmed" (5+ consecutive), "developing" (3-4), or "weak" (<3)
  consecutive_count: number of consecutive same-direction signals
  last_signal: most recent action ("buy" or "sell")
Trend data comes from recent TradingPilotAI signals and reflects the indicator's directional bias.

Apply these rules when trend data is available for the signal's symbol:
- bullish/confirmed: prefer approval, set confidence "high", set position_size_pct to 2.5, set take_profit_pct to 2.5, set stop_loss_pct to 1.0
- bullish/developing: approve normally, confidence "high" or "medium", set take_profit_pct to 1.5, set stop_loss_pct to 1.5
- neutral (any strength): approve cautiously, set confidence "medium" or "low", set take_profit_pct to 1.0, set stop_loss_pct to 2.0
- bearish (any strength): reject buy signals regardless of other criteria; sells remain always approved

For sell signals, always set take_profit_pct to 0.0 and stop_loss_pct to 0.0 (these fields are not applicable to closing orders).

If no trend data exists for the symbol, treat it as neutral.

ROLLING MOMENTUM GUIDANCE:
account_state may contain a "rolling_momentum" dict from an observe-only 5-market-day / extended-hours context layer with:
  trend_context: "strong_bullish_continuation", "bullish_continuation", "mixed_or_neutral", "bearish_pressure", "bearish_continuation", or "unknown"
  continuation_score: numeric score, positive = bullish continuity, negative = bearish continuity
  five_day_return_pct, prior_day_return_pct, overnight_gap_pct, premarket_return_pct, current_session_return_pct, current_price_vs_prior_close_pct
  special_labels: possible labels such as "gap_up_chase_risk", "pullback_in_uptrend", "premarket_reversal_attempt", "after_hours_warning", "premarket_confirmation", "overnight_contradiction"
  fresh: true/false and age_minutes

Apply to buy signals:
- Treat rolling_momentum as advisory context only; it never overrides hard pre-checks.
- If fresh and trend_context is bullish_continuation or strong_bullish_continuation, it may support higher confidence when trend_table and live momentum also confirm.
- If fresh and trend_context is bearish_pressure or bearish_continuation, reduce confidence and prefer rejection unless live trend_table is bullish/confirmed with strong momentum.
- If special_labels includes "gap_up_chase_risk", avoid chasing; reduce confidence/size or reject if entry_quality is not excellent.
- If special_labels includes "pullback_in_uptrend", treat weakness as potentially tactical, but require bullish trend confirmation.
- If special_labels includes "overnight_contradiction" or "after_hours_warning", reduce confidence.
- If rolling_momentum is stale or absent, ignore it.

MOMENTUM GUIDANCE:
account_state may contain a "momentum" dict for buy signals with:
  direction: "rising", "falling", or "flat"
  momentum_pct: percent change across the last 5 one-minute bars
  price_vs_bars: percent difference between the signal price and the most recent bar close
  last_close: most recent bar close price
account_state may also contain a "signal_confidence_hint" of "high" or "low" — when present, use this as your starting confidence before applying trend rules. Trend rules can still override (e.g. bearish trend always rejects buys regardless of momentum).

Apply to buy signals:
- Rising momentum confirms the signal — favor approval, lean confidence higher
- Falling momentum is a caution flag — lean confidence lower
- Flat momentum is neutral — no momentum-based adjustment

SESSION MOMENTUM GUIDANCE:
account_state may contain "session_momentum", a session-aware intraday state produced from recent 1-minute bars. It may include:
  trend_label: "strong_uptrend", "developing_uptrend", "reversal_attempt", "rangebound", "fading", "downtrend", or "insufficient_data"
  trend_score: numeric score; higher is stronger intraday momentum, lower is weaker
  session_return_pct: percent move from the first available intraday bar to latest price
  momentum_5m_pct, momentum_15m_pct, momentum_30m_pct: short/intermediate intraday returns
  distance_from_vwap_pct: percent distance from intraday VWAP
  reason: compact explanation of the classification

Use session_momentum as supporting context, not a hard rule.
- strong_uptrend or developing_uptrend supports buy approval only when trend_table, setup, prediction, and risk gates also support the trade.
- reversal_attempt is cautiously positive but requires confirmation from trend_table and prediction score.
- rangebound is neutral.
- fading or downtrend should reduce confidence and favor rejection unless this is a defensive/hedge-only trade.
- insufficient_data should be ignored.

PRE-MARKET ALIGNMENT GUIDANCE:
account_state["momentum"] may include:
  premarket_bias: "buy", "avoid", or "neutral"
  premarket_alignment: "confirmed", "contradicted", "mixed", "neutral",
                       "avoid_confirmed", "tape_strength_against_avoid",
                       "bullish_intraday_shift", or "bearish_intraday_shift"
  momentum_5m_pct: short-term 1-minute-bar momentum
  momentum_15m_pct: broader intraday 1-minute-bar momentum
  action_hint: advisory interpretation

Apply to buy signals:
- premarket_alignment "confirmed": live 1-minute tape confirms the pre-market thesis; favor approval when trend_table is bullish.
- premarket_alignment "contradicted": live 1-minute tape is moving against the pre-market buy thesis; reduce confidence to low unless trend_table is bullish/confirmed.
- premarket_alignment "mixed": use caution; prefer smaller sizing and medium confidence.
- bullish_intraday_shift on a neutral pre-market symbol is not enough by itself; require bullish trend_table confirmation.
- Never override hard gates or bearish trend using intraday alignment.

MARKET BIAS GUIDANCE:
account_state may contain a "market_bias" field with the value "buy" when same-day pre-market research flagged the symbol positively (favorable news, analyst upgrade, strong pre-market move). The bias is only injected when positive — its absence is informationally neutral, not negative.

Apply to buy signals:
- market_bias "buy" combined with bullish/confirmed trend: highest-conviction signal — prefer approval, confidence "high", position_size_pct 2.5
- market_bias "buy" combined with bullish/developing trend: confidence "high", position_size_pct up to 2.5
- market_bias "buy" combined with neutral trend: still treat as cautious — positive bias alone does NOT justify approval
- market_bias absent: defer entirely to trend table and momentum guidance, make no bias-based adjustment
- NEVER use market_bias "buy" to override a bearish trend rejection — bearish always rejects buys regardless of any other positive signal

LIVE BIAS OVERRIDE GUIDANCE:
account_state may contain:
- market_bias_original: the pre-market research bias.
- market_bias_effective: the intraday-adjusted bias after live trend, setup, prediction, and momentum evidence.
- market_bias_override_reason: explanation of the live override or downgrade.
- avoid_type: "hard" or "soft" when original market_bias is "avoid".

Use market_bias_effective as the current trading context. Treat market_bias_original as background only.

If market_bias_effective is "live_override_buy", live evidence has outweighed a neutral or soft-avoid pre-market bias. Approval is allowed only when trend, momentum, setup, and prediction evidence are supportive. If the original bias was avoid, use reduced sizing and cap confidence at medium.

If market_bias_effective is "live_override_neutral", live evidence has downgraded a pre-market buy bias. Prefer rejection unless trend is bullish/confirmed and momentum is rising.

If market_bias_effective is "avoid_hard", reject buy signals.

If market_bias_effective is "avoid_soft", approval requires strong live confirmation and should use smaller sizing.

FUNDAMENTAL SCORE GUIDANCE:
account_state may contain "fundamental_score" from same-day market research:
- "strong_bullish": positive context; may support high confidence only when trend and momentum also confirm.
- "bullish": modest positive context; do not approve by itself.
- "neutral": no fundamental edge; require trend and/or momentum confirmation.
- "bearish" or "strong_bearish": should normally be filtered before Claude. If present, reject buy signals.
Fundamentals never override bearish trend, weak momentum, exposure rules, risk_level, or poor entry_quality.

execution_mode may be "paper" or "cash".

- In paper mode, favor trend participation when trend, setup, and prediction evidence are supportive.
  Conditional entry_quality states should usually reduce size/confidence rather than force rejection.

- In cash mode, be stricter with conditional entry_quality states and prefer stronger confirmation before approval.


EXECUTION QUALITY GUIDANCE:
account_state may contain "risk_level" and "entry_quality" — tactical overlays from same-day pre-market research. These tighten sizing and confidence; they never override hard rules (4% exposure, 8 positions, bearish trend rejection, daily loss limit).

Pre-Claude filtering note: entry_quality values "do_not_chase" and "avoid_chasing" are rejected before Claude is called — they will never appear in account_state. entry_quality "poor" is usually accompanied by bias "avoid" (also pre-rejected); if "poor" appears here as a safety-net case, treat as reject.

risk_level adjustments (apply to buy signals):
- "low" / "medium": no adjustment — defer to trend/momentum/bias rules.
- "high": reduce position_size_pct by ~25% from the trend-rule default; cap confidence at "medium".
- "very_high": cap confidence at "medium" regardless of trend strength. (Note: the broker also halves order qty automatically on very_high; do not compensate by recommending larger position_size_pct.)

entry_quality adjustments (apply to buy signals):
- "excellent" / "high": no adjustment — clean setup, approve per trend/bias rules.

- "good_on_pullbacks" / "good_if_holds_gap" / "good_if_breadth_holds":
  These are conditional entries, but in paper mode they are not automatic rejections.
  If trend, setup, market_bias, and prediction evidence are supportive, approval is allowed.
  Set confidence to at most "medium" and reduce position_size_pct by about 25%.
  Describe the entry as conditional or less ideal, but do not require explicit pullback/gap/breadth confirmation unless the broader evidence is weak.

- "tactical_only":
  position_size_pct max 1.0%; confidence "medium" only.
  More restrictive than the good_* states.
  Reject if trend is not at least bullish/developing or if setup/prediction evidence is weak.

- "hedge_only":
  position_size_pct max 1.0%; confidence "medium" only; this is a defensive position, not a primary momentum entry.

When risk_level and entry_quality conflict with trend or bias, favor the tighter signal by reducing size and confidence.
For paper mode, conditional entry_quality states should usually reduce size/confidence rather than force rejection when trend/setup/prediction evidence is supportive.
Hard rejections still win over soft adjustments.


DECISION CONSISTENCY RULES:
- If the reasoning says "defer", "wait", "hold off", "not enough conviction", "lacks sufficient conviction", or "until momentum improves", then approved MUST be false.
- Do not say "approve" anywhere in the reason unless approved is true.
- Do not say "reject", "defer", "wait", or "hold off" anywhere in the reason unless approved is false.
- The final JSON must contain one clear decision only.
- The reason must be one concise sentence under 300 characters.
- No markdown, numbered analysis, bullet points, duplicated reasoning, or explanatory sections outside the JSON.

Always respond with this exact JSON format:
{
    "approved": true or false,
    "reason": "your reason here",
    "position_size_pct": 1.5,
    "stop_loss_pct": 0.5,
    "take_profit_pct": 1.5,
    "confidence": "high"
}
'''

TRADING_RULES = TRADING_RULES.replace(
    "{APPROVED_SYMBOLS_CSV}",
    APPROVED_SYMBOLS_CSV,
)

def evaluate_signal(signal_data, account_state):
    try:
        account_state = dict(account_state or {})

        # Do not let observe-only diagnostics influence Claude decisions.
        # These are for reporting/debugging only, not live approval gating.
        account_state.pop("adaptive_buy_confirmation", None)
        account_state.pop("adaptive_buy_confirmation_error", None)
        account_state.pop("market_alignment", None)
        account_state.pop("market_alignment_error", None)

        logger.debug(
            f"Account context for evaluation — balance: {account_state.get('balance')}, "
            f"open_positions: {account_state.get('open_positions')}, "
            f"open_position_count: {account_state.get('open_position_count')}"
        )
        prompt = 'Evaluate this signal: ' + json.dumps(signal_data) + ' Account: ' + json.dumps(account_state)
        response_text = ""
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=1000,
            system=TRADING_RULES,
            messages=[{'role': 'user', 'content': prompt}]
        )
        response_text = message.content[0].text
        logger.info(f'AI decision: {response_text}')
        response_clean = response_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(response_clean)
    except json.JSONDecodeError as e:
        logger.error(f'JSON parse error: {e} | Raw response: {response_text}')
        return {'approved': False, 'reason': 'Parse error - rejecting for safety', 'position_size_pct': 0, 'stop_loss_pct': 0, 'take_profit_pct': 0, 'confidence': 'low'}
    except Exception as e:
        logger.error(f'Decision engine error: {e}')
        return {'approved': False, 'reason': f'Engine error: {str(e)}', 'position_size_pct': 0, 'stop_loss_pct': 0, 'take_profit_pct': 0, 'confidence': 'low'}

def get_mock_account_state():
    from broker import api, get_account
    from portfolio_state import build_account_state

    return build_account_state(api=api, get_account_func=get_account)

    state = {
        'balance': 10000.00,
        'daily_pnl': 0.0,
        'daily_pnl_pct': 0.0,
        'open_positions': [],
        'open_position_count': 0,
        'market_session': 'regular'
    }

    # Real balance and portfolio value
    try:
        account = get_account()
        if account:
            state['balance'] = account['balance']
            state['portfolio_value'] = account['portfolio_value']
    except Exception as e:
        logger.error(f"get_mock_account_state: failed to fetch account: {e}")

    # Unrealized P&L and open positions from Alpaca
    unrealized_pnl = 0.0
    try:
        positions = api.list_positions()
        state['open_positions'] = [
            {'symbol': p.symbol, 'qty': float(p.qty), 'unrealized_pl': float(p.unrealized_pl)}
            for p in positions
        ]
        state['open_position_count'] = len(positions)
        unrealized_pnl = sum(float(p.unrealized_pl) for p in positions)
    except Exception as e:
        logger.error(f"get_mock_account_state: failed to fetch positions: {e}")

    # Realized P&L from canonical confirmed-fill helper.
    # Never falls back to signal_price.
    realized_pnl = 0.0
    try:
        realized_pnl = get_daily_realized_pnl()
    except Exception as e:
        logger.error(f"get_mock_account_state: failed to compute realized P&L: {e}")

    # Combine and compute percentage against start-of-day portfolio value
    try:
        daily_pnl = unrealized_pnl + realized_pnl
        portfolio_value = state.get('portfolio_value', state['balance'])
        start_of_day = portfolio_value - daily_pnl
        daily_pnl_pct = (daily_pnl / start_of_day * 100) if start_of_day > 0 else 0.0
        state['daily_pnl']     = round(daily_pnl, 2)
        state['daily_pnl_pct'] = round(daily_pnl_pct, 2)
        logger.debug(f"Daily P&L: {daily_pnl:.2f} ({daily_pnl_pct:.2f}%) — unrealized={unrealized_pnl:.2f} realized={realized_pnl:.2f}")
    except Exception as e:
        logger.error(f"get_mock_account_state: failed to compute daily P&L pct: {e}")

    return state