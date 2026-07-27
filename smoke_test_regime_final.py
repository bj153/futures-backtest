# 冒烟测试：用与 BacktestEngine._run_miqin_style 相同的受限 exec 作用域
# 在合成 1h K 线上执行 regime_adaptive_final.py，验证无异常且能产生信号
import random

random.seed(42)

# 生成 2000 根合成K线（趋势段 + 震荡段交替）
bars = []
price = 3000.0
for i in range(2000):
    if (i // 250) % 2 == 0:
        drift = 3.0 if (i // 250) % 4 == 0 else -3.0   # 趋势段
    else:
        drift = (3000 - price) * 0.02                  # 震荡段（均值回归）
    o = price
    c = o + drift + random.gauss(0, 8)
    h = max(o, c) + abs(random.gauss(0, 4))
    l = min(o, c) - abs(random.gauss(0, 4))
    bars.append({'open': o, 'high': h, 'low': l, 'close': c,
                 'volume': 1000, 'time': '2026-01-01 %02d:00' % (i % 24)})
    price = c

code = open(r'F:\Source\170\futures-backtest\backend\strategies\regime_adaptive_final.py',
            encoding='utf-8').read()

BUILTINS = {'len': len, 'range': range, 'min': min, 'max': max, 'abs': abs,
            'sum': sum, 'int': int, 'float': float, 'list': list, 'dict': dict,
            'all': all, 'any': any, 'sorted': sorted, 'round': round, 'str': str,
            'enumerate': enumerate, 'zip': zip, 'Exception': Exception,
            'NameError': NameError}

def sma(v, p):
    return [sum(v[max(0, i - p + 1):i + 1]) / len(v[max(0, i - p + 1):i + 1]) for i in range(len(v))]

context = {'capital': 100000, 'position': 0, 'entry_price': 0, 'trades': [],
           'equity_curve': [], 'total_commission': 0, 'bars': bars}

scope = {'context': context, 'init': lambda ctx: None,
         'handle_bar': lambda ctx, bd: None,
         'sma': sma, 'ema': sma, 'rsi': sma, 'calc_verts': lambda *a: None,
         '__builtins__': BUILTINS}
exec(code, scope)
scope['init'](context)

position = 0
entry_price = 0
trades = []
for bar in bars:
    context['current_bar'] = 0
    context['bar'] = bar
    context['position'] = position
    scope['handle_bar'](context, bar)
    action = context.get('_action')
    if action and action != 'hold':
        price_ = context.get('_price', bar['close'])
        if action in ('buy', 'short') and position == 0:
            position = 1 if action == 'buy' else -1
            entry_price = price_
            trades.append((action, round(price_, 1), context.get('_reason', '')))
        elif action in ('sell', 'cover') and position != 0:
            trades.append((action, round(price_, 1), context.get('_reason', '')))
            position = 0
        elif action in ('flip_long', 'flip_short'):
            position = 1 if action == 'flip_long' else -1
            entry_price = price_
            trades.append((action, round(price_, 1), context.get('_reason', '')))
        context['_action'] = None

print('bars:', len(bars))
print('trades:', len(trades))
print('final position:', position)
print('adx computed:', len(context['adx_list']), 'values; last regime_adx:',
      round(context['adx_list'][-48] and sum(context['adx_list'][-48:]) / 48, 2) if len(context['adx_list']) >= 48 else 'N/A')
for t in trades[:6]:
    print(' ', t)
print('...')
for t in trades[-4:]:
    print(' ', t)
print('SMOKE TEST OK')
