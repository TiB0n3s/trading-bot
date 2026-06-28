import sys
sys.path.insert(0, '/home/tradingbot/trading-bot')
sys.path.insert(0, '/home/tradingbot/trading-bot/scripts')
sys.path.insert(0, '/home/tradingbot/trading-bot/src')
from pipeline.cold_learning_archive import _training_evidence
ev = _training_evidence()
print('GATE ready :', ev['ready'], flush=True)
print('hook_status:', ev['hook_status'], '| exit_code:', ev['hook_exit_code'], flush=True)
for label, dd in ev['diagnostics'].items():
    print('  %-22s trained=%s sample=%s' % (label, dd['trained'], dd['sample_size']), flush=True)
