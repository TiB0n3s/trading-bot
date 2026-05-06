import os
import json
import sqlite3
import logging
from collections import defaultdict
from datetime import date
from pathlib import Path
from anthropic import Anthropic

logger = logging.getLogger(__name__)
client = Anthropic()

TRADING_RULES = '''
You are a risk-aware trading decision engine.
Evaluate signals and respond with JSON only.

HARD RULES:
- Max position size: 2% of account balance per individual buy order (see trend exception below)
- Max total exposure per symbol: 4% of account balance — if current_symbol_position value (qty * current_price) already exceeds 4% of balance, reject any further buy signals for that symbol
- Daily loss limit: reject all if down 3% today
- Only trade 9:45 AM to 3:45 PM Eastern Time
- Max 8 open positions at any time (this limit applies ONLY to opening new positions; sell/close signals must always be approved regardless of current position count)
- Approved symbols only: AAPL, SPY, QQQ, MSFT, NVDA, ORCL, TSCO, TSLA, META, AMD, CVX, XOM
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

def evaluate_signal(signal_data, account_state):
    try:
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

    # Realized P&L from today's filled trades in trades.db (FIFO matching)
    realized_pnl = 0.0
    try:
        db_path = Path(__file__).parent / "trades.db"
        today = date.today().isoformat()
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT action, symbol, qty, fill_price, signal_price FROM trades "
            "WHERE timestamp LIKE ? AND order_id IS NOT NULL",
            (f"{today}%",)
        ).fetchall()
        con.close()

        sym_buys  = defaultdict(list)
        sym_sells = defaultdict(list)
        for r in rows:
            price = r['fill_price'] if r['fill_price'] is not None else r['signal_price']
            entry = {'qty': r['qty'] or 0, 'price': price or 0.0}
            if r['action'] == 'buy':
                sym_buys[r['symbol']].append(entry)
            else:
                sym_sells[r['symbol']].append(entry)

        for sym, sells in sym_sells.items():
            buys = list(sym_buys[sym])
            for sell in sells:
                remaining = sell['qty']
                while remaining > 0 and buys:
                    buy = buys[0]
                    matched = min(remaining, buy['qty'])
                    realized_pnl += (sell['price'] - buy['price']) * matched
                    buy['qty'] -= matched
                    remaining  -= matched
                    if buy['qty'] == 0:
                        buys.pop(0)
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