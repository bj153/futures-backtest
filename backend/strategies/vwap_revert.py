# ========== 日内 VWAP 均值回归 ==========
# VWAP 按"交易日"累计：夜盘（>=20:00）开始的K线开启新交易日，
# 夜盘跨午夜（00:00）不做拆分（池内品种夜盘均 23:00 收盘，无跨午夜）。
# 偏离：价格偏离 VWAP 超过 dev_atr × ATR(14) → 反向开仓
#       （σ 用 ATR 替代，简单可靠，报告已注明）
# 止盈：价格回到 VWAP（多头 high >= vwap 即按 vwap 平）
# 止损：sl_atr × ATR；时间止损 time_stop 根
# 强制平仓（不隔夜）：14:55~15:05 或 22:55~23:00 的K线按收盘价平仓
# 接口同 BacktestEngine（init/handle_bar，_action/_price/_reason）
# =========================================================================

def init(context):
    context['dev_atr'] = context.get('dev_atr', 1.5)     # 偏离阈值（ATR 倍数）
    context['atr_len'] = context.get('atr_len', 14)
    context['sl_atr'] = context.get('sl_atr', 1.5)
    context['time_stop'] = context.get('time_stop', 20)
    context['min_bars'] = context.get('min_bars', 10)    # 每交易日至少累计N根才交易

    context['history'] = []
    context['stop'] = None
    context['entry_bar'] = None
    # VWAP 状态
    context['sess_key'] = None
    context['cum_pv'] = 0.0
    context['cum_v'] = 0.0
    context['sess_bars'] = 0


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


def _sess_key(timestr, prev_key):
    """交易日分组键：'YYYY-MM-DD HH:MM...' → 会话编号。
    夜盘(>=20:00)开启新会话；日盘日期变化开启新会话；其余沿用。"""
    date = timestr[:10]
    hm = timestr[11:16]
    hour = int(hm[:2])
    if prev_key is None:
        return date + ('N' if hour >= 20 else 'D')
    prev_date = prev_key[:10]
    prev_tag = prev_key[10:]
    if hour >= 20:
        # 夜盘开始：若上一会话是同日日盘或更早，开新会话
        if prev_tag == 'D' and prev_date == date:
            return date + 'N'
        if prev_date != date:
            return date + 'N'
        return prev_key
    else:
        # 日盘：日期变化开新会话；同日期沿用
        if prev_date != date:
            return date + 'D'
        return prev_key


def handle_bar(context, bar):
    history = context['history']
    history.append(bar)
    i = len(history)

    c = bar['close']
    h_ = bar['high']
    l_ = bar['low']
    v = bar.get('volume', 0)
    tstr = bar.get('time', '')
    hm = tstr[11:16] if len(tstr) >= 16 else ''

    # ---- VWAP 会话累计 ----
    key = _sess_key(tstr, context['sess_key'])
    if key != context['sess_key']:
        context['sess_key'] = key
        context['cum_pv'] = 0.0
        context['cum_v'] = 0.0
        context['sess_bars'] = 0
    tp = (h_ + l_ + c) / 3.0
    context['cum_pv'] += tp * v
    context['cum_v'] += v
    context['sess_bars'] += 1
    vwap = context['cum_pv'] / context['cum_v'] if context['cum_v'] > 0 else c

    if i < context['atr_len'] + 5:
        return

    pos = context.get('position', 0)
    atr = _atr(context)

    # ---- 强制平仓（不隔夜）：14:55~15:05 或 22:55~23:00 ----
    force = (hm >= '14:55' and hm <= '15:05') or (hm >= '22:55' and hm <= '23:00')
    if pos != 0 and force:
        if pos == 1:
            context['_action'] = 'sell'
        else:
            context['_action'] = 'cover'
        context['_price'] = c
        context['_reason'] = 'VWAP 日内强平 %.1f' % c
        context['stop'] = None
        context['entry_bar'] = None
        return

    # ---- 持仓管理 ----
    if pos != 0 and context['stop'] is not None and atr is not None:
        hit = False
        if pos == 1:
            if l_ <= context['stop']:
                context['_action'] = 'sell'
                context['_price'] = context['stop']
                context['_reason'] = 'VWAP 多/止损 %.1f' % context['stop']
                hit = True
            elif h_ >= vwap:
                context['_action'] = 'sell'
                context['_price'] = vwap
                context['_reason'] = 'VWAP 多/回归 %.1f' % vwap
                hit = True
        else:
            if h_ >= context['stop']:
                context['_action'] = 'cover'
                context['_price'] = context['stop']
                context['_reason'] = 'VWAP 空/止损 %.1f' % context['stop']
                hit = True
            elif l_ <= vwap:
                context['_action'] = 'cover'
                context['_price'] = vwap
                context['_reason'] = 'VWAP 空/回归 %.1f' % vwap
                hit = True

        if not hit and context['entry_bar'] is not None:
            if i - context['entry_bar'] >= context['time_stop']:
                if pos == 1:
                    context['_action'] = 'sell'
                else:
                    context['_action'] = 'cover'
                context['_price'] = c
                context['_reason'] = 'VWAP 时间离场 %.1f' % c
                hit = True

        if hit:
            context['stop'] = None
            context['entry_bar'] = None
            return
        return

    # ---- 入场 ----
    if atr is None or atr <= 0:
        return
    if context['sess_bars'] < context['min_bars']:
        return
    # 临近强平时间不开新仓
    if (hm >= '14:40' and hm <= '15:05') or (hm >= '22:40' and hm <= '23:00'):
        return

    dev = context['dev_atr'] * atr
    if c < vwap - dev:
        context['_action'] = 'buy'
        context['_price'] = c
        context['stop'] = c - context['sl_atr'] * atr
        context['entry_bar'] = i
        context['_reason'] = 'VWAP 做多 %.1f vwap:%.1f 损:%.1f' % (c, vwap, context['stop'])
        return
    if c > vwap + dev:
        context['_action'] = 'short'
        context['_price'] = c
        context['stop'] = c + context['sl_atr'] * atr
        context['entry_bar'] = i
        context['_reason'] = 'VWAP 做空 %.1f vwap:%.1f 损:%.1f' % (c, vwap, context['stop'])
        return
