# ========== RSI(2) 极值反转（Connors 风格） ==========
# 做多：RSI(2) < long_rsi 且收盘 > EMA(slow_len)
# 做空：RSI(2) > short_rsi 且收盘 < EMA(slow_len)
# 止盈：多头收盘价 > SMA(tp_len) 即离场（空头对称：收盘 < SMA(tp_len)）
# 止损：sl_atr × ATR(atr_len)；持仓超 time_stop 根未离场 → 市价平仓
# 接口同 BacktestEngine（init/handle_bar，_action/_price/_reason）
# =========================================================================

def init(context):
    context['rsi_len'] = context.get('rsi_len', 2)
    context['long_rsi'] = context.get('long_rsi', 5.0)
    context['short_rsi'] = context.get('short_rsi', 95.0)
    context['slow_len'] = context.get('slow_len', 200)     # EMA 方向保护
    context['use_ema'] = context.get('use_ema', 1)         # 1=启用EMA方向保护 0=双向自由反转
    context['tp_len'] = context.get('tp_len', 5)           # SMA 止盈
    context['tp_mode'] = context.get('tp_mode', 'sma')     # 'sma'=收盘过SMA止盈 'atr'=固定ATR止盈
    context['tp_atr'] = context.get('tp_atr', 1.0)         # tp_mode='atr' 时的止盈倍数
    context['atr_len'] = context.get('atr_len', 14)
    context['sl_atr'] = context.get('sl_atr', 2.5)
    context['time_stop'] = context.get('time_stop', 30)

    context['history'] = []
    context['stop'] = None
    context['take_profit'] = None
    context['entry_bar'] = None


def _atr(context):
    h = context['history']
    n = context['atr_len']
    if len(h) < n + 1:
        return None
    total = 0.0
    for k in range(len(h) - n, len(h)):
        cur = h[k]
        prev_close = h[k - 1]['close']
        tr = max(cur['high'] - cur['low'],
                 abs(cur['high'] - prev_close),
                 abs(cur['low'] - prev_close))
        total += tr
    return total / n


def handle_bar(context, bar):
    history = context['history']
    history.append(bar)
    i = len(history)

    warmup = context['slow_len'] + context['atr_len'] + 5
    if i < warmup:
        return

    c = bar['close']
    h_ = bar['high']
    l_ = bar['low']
    pos = context.get('position', 0)

    closes = [b['close'] for b in history]

    # ---- 持仓管理 ----
    if pos != 0 and context['stop'] is not None:
        hit = False
        if context['tp_mode'] == 'atr':
            tp_line = context['take_profit']
        else:
            tp_line = sma(closes, context['tp_len'])[-1]
        if pos == 1:
            if l_ <= context['stop']:
                context['_action'] = 'sell'
                context['_price'] = context['stop']
                context['_reason'] = 'RSI2 多/止损 %.1f' % context['stop']
                hit = True
            elif (context['tp_mode'] == 'atr' and h_ >= tp_line) or \
                 (context['tp_mode'] != 'atr' and c > tp_line):
                context['_action'] = 'sell'
                context['_price'] = tp_line if context['tp_mode'] == 'atr' else c
                context['_reason'] = 'RSI2 多/止盈 %.1f' % context['_price']
                hit = True
        else:
            if h_ >= context['stop']:
                context['_action'] = 'cover'
                context['_price'] = context['stop']
                context['_reason'] = 'RSI2 空/止损 %.1f' % context['stop']
                hit = True
            elif (context['tp_mode'] == 'atr' and l_ <= tp_line) or \
                 (context['tp_mode'] != 'atr' and c < tp_line):
                context['_action'] = 'cover'
                context['_price'] = tp_line if context['tp_mode'] == 'atr' else c
                context['_reason'] = 'RSI2 空/止盈 %.1f' % context['_price']
                hit = True

        if not hit and context['entry_bar'] is not None:
            if i - context['entry_bar'] >= context['time_stop']:
                if pos == 1:
                    context['_action'] = 'sell'
                else:
                    context['_action'] = 'cover'
                context['_price'] = c
                context['_reason'] = 'RSI2 时间离场 %.1f' % c
                hit = True

        if hit:
            context['stop'] = None
            context['entry_bar'] = None
            return
        return

    # ---- 入场 ----
    atr = _atr(context)
    if atr is None or atr <= 0:
        return

    rsi_val = rsi(closes, context['rsi_len'])[-1]
    ema_val = ema(closes, context['slow_len'])[-1]

    if context['use_ema']:
        long_ok = c > ema_val
        short_ok = c < ema_val
    else:
        long_ok = True
        short_ok = True

    if rsi_val < context['long_rsi'] and long_ok:
        context['_action'] = 'buy'
        context['_price'] = c
        context['stop'] = c - context['sl_atr'] * atr
        if context['tp_mode'] == 'atr':
            context['take_profit'] = c + context['tp_atr'] * atr
        context['entry_bar'] = i
        context['_reason'] = 'RSI2 做多 %.1f RSI:%.1f 损:%.1f' % (c, rsi_val, context['stop'])
        return

    if rsi_val > context['short_rsi'] and short_ok:
        context['_action'] = 'short'
        context['_price'] = c
        context['stop'] = c + context['sl_atr'] * atr
        if context['tp_mode'] == 'atr':
            context['take_profit'] = c - context['tp_atr'] * atr
        context['entry_bar'] = i
        context['_reason'] = 'RSI2 做空 %.1f RSI:%.1f 损:%.1f' % (c, rsi_val, context['stop'])
        return
