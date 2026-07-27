# ========== 连K动能衰竭反转 ==========
# 连续 streak_n 根阳线（close>open）且累计涨幅 > move_atr × ATR(14) → 做空
# 连续 streak_n 根阴线且累计跌幅 > move_atr × ATR(14) → 做多
# 止盈 tp_atr × ATR；止损 sl_atr × ATR；时间止损 time_stop 根
# 接口同 BacktestEngine（init/handle_bar，_action/_price/_reason）
# =========================================================================

def init(context):
    context['streak_n'] = context.get('streak_n', 3)
    context['move_atr'] = context.get('move_atr', 1.5)
    context['atr_len'] = context.get('atr_len', 14)
    context['tp_atr'] = context.get('tp_atr', 0.8)
    context['sl_atr'] = context.get('sl_atr', 1.2)
    context['time_stop'] = context.get('time_stop', 15)

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

    warmup = context['atr_len'] + context['streak_n'] + 3
    if i < warmup:
        return

    c = bar['close']
    h_ = bar['high']
    l_ = bar['low']
    pos = context.get('position', 0)

    # ---- 持仓管理 ----
    if pos != 0 and context['stop'] is not None:
        hit = False
        if pos == 1:
            if l_ <= context['stop']:
                context['_action'] = 'sell'
                context['_price'] = context['stop']
                context['_reason'] = '连K 多/止损 %.1f' % context['stop']
                hit = True
            elif h_ >= context['take_profit']:
                context['_action'] = 'sell'
                context['_price'] = context['take_profit']
                context['_reason'] = '连K 多/止盈 %.1f' % context['take_profit']
                hit = True
        else:
            if h_ >= context['stop']:
                context['_action'] = 'cover'
                context['_price'] = context['stop']
                context['_reason'] = '连K 空/止损 %.1f' % context['stop']
                hit = True
            elif l_ <= context['take_profit']:
                context['_action'] = 'cover'
                context['_price'] = context['take_profit']
                context['_reason'] = '连K 空/止盈 %.1f' % context['take_profit']
                hit = True

        if not hit and context['entry_bar'] is not None:
            if i - context['entry_bar'] >= context['time_stop']:
                if pos == 1:
                    context['_action'] = 'sell'
                else:
                    context['_action'] = 'cover'
                context['_price'] = c
                context['_reason'] = '连K 时间离场 %.1f' % c
                hit = True

        if hit:
            context['stop'] = None
            context['take_profit'] = None
            context['entry_bar'] = None
            return
        return

    # ---- 入场 ----
    atr = _atr(context)
    if atr is None or atr <= 0:
        return

    n = context['streak_n']
    seg = history[-n:]
    up = True
    dn = True
    for b in seg:
        if b['close'] <= b['open']:
            up = False
        if b['close'] >= b['open']:
            dn = False

    move = abs(seg[-1]['close'] - seg[0]['open'])
    if move <= context['move_atr'] * atr:
        return

    if up:
        context['_action'] = 'short'
        context['_price'] = c
        context['stop'] = c + context['sl_atr'] * atr
        context['take_profit'] = c - context['tp_atr'] * atr
        context['entry_bar'] = i
        context['_reason'] = '连K 做空 %d阳 %.1f 损:%.1f 盈:%.1f' % (
            n, c, context['stop'], context['take_profit'])
        return

    if dn:
        context['_action'] = 'buy'
        context['_price'] = c
        context['stop'] = c - context['sl_atr'] * atr
        context['take_profit'] = c + context['tp_atr'] * atr
        context['entry_bar'] = i
        context['_reason'] = '连K 做多 %d阴 %.1f 损:%.1f 盈:%.1f' % (
            n, c, context['stop'], context['take_profit'])
        return
