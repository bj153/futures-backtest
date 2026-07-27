# ========== 稳定均值回归（StableReversion）==========
# 综合 rsi2_revert + mean_revert + regime_adaptive 的最优基因
#
# 核心逻辑:
#   【市场过滤】ADX(14) < 25 → 只做震荡市
#   【方向过滤】收盘 > EMA(200) → 只做多；收盘 < EMA(200) → 只做空
#   【时机信号】RSI(2) < 10（超卖）/ > 90（超买）→ 均值回归入场
#   【风控出场】ATR(14) 2x止损 + 3x止盈 + 12K线时间止损
#
# 最优参数 (20组扫描，MA609 15m 2025-09~2026-07):
#   RSI<10/>90  ADX<25  SL=2.0xATR  TP=3.0xATR  无VWAP
#   MA609: +4,530 / 95笔 / 34.7%胜率 / 0.6%回撤 / 夏普0.66
#
# 全品种21合约回测 (默认参数 2026-07-27):
#   ★★★ MA609 +3819  jm2609 +2364
#   ★★  eg2609 +2327  fu2609 +1468
#   ★   ao2609 +982  pg2608 +790  SR609 +647  sp2609 +591  SH609 +419
#   ✗   CF609 -5211  p2609 -3351  bu2609 -2036  y2609 -1435
#   建议仅用于 MA、jm、eg、fu
# =================================================================

def init(context):
    context['rsi_len'] = context.get('rsi_len', 2)
    context['long_rsi'] = context.get('long_rsi', 10.0)
    context['short_rsi'] = context.get('short_rsi', 90.0)

    context['ema_len'] = context.get('ema_len', 200)

    context['adx_period'] = context.get('adx_period', 14)
    context['adx_max'] = context.get('adx_max', 25.0)

    context['atr_len'] = context.get('atr_len', 14)
    context['vwap_dev'] = context.get('vwap_dev', 0.0)   # 0=禁用VWAP过滤，1.0~2.0=启用
    context['sl_atr'] = context.get('sl_atr', 2.0)
    context['tp_atr'] = context.get('tp_atr', 3.0)
    context['time_stop'] = context.get('time_stop', 12)

    context['history'] = []
    context['stop'] = None
    context['take_profit'] = None
    context['entry_bar'] = None

    # ADX 内部状态
    context['tr_list'] = []
    context['pdm_list'] = []
    context['mdm_list'] = []
    context['dx_list'] = []
    context['adx_list'] = []

    # VWAP 内部状态
    context['sess_key'] = None
    context['cum_pv'] = 0.0
    context['cum_v'] = 0.0


# -------- helpers --------
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
    date = timestr[:10]
    hm = timestr[11:16]
    hour = int(hm[:2])
    if prev_key is None:
        return date + ('N' if hour >= 20 else 'D')
    prev_date = prev_key[:10]
    prev_tag = prev_key[10:]
    if hour >= 20:
        if prev_tag == 'D' and prev_date == date:
            return date + 'N'
        if prev_date != date:
            return date + 'N'
        return prev_key
    else:
        if prev_date != date:
            return date + 'D'
        return prev_key


def _update_adx(context):
    history = context['history']
    if len(history) < 2:
        return
    cur = history[-1]
    prev = history[-2]
    tr = max(cur['high'] - cur['low'],
             abs(cur['high'] - prev['close']),
             abs(cur['low'] - prev['close']))
    up_move = cur['high'] - prev['high']
    dn_move = prev['low'] - cur['low']
    pdm = up_move if (up_move > dn_move and up_move > 0) else 0.0
    mdm = dn_move if (dn_move > up_move and dn_move > 0) else 0.0

    context['tr_list'].append(tr)
    context['pdm_list'].append(pdm)
    context['mdm_list'].append(mdm)

    n = context['adx_period']
    if len(context['tr_list']) < n:
        return
    tr_s = 0.0
    pdm_s = 0.0
    mdm_s = 0.0
    for k in range(-n, 0):
        tr_s += context['tr_list'][k]
        pdm_s += context['pdm_list'][k]
        mdm_s += context['mdm_list'][k]
    if tr_s <= 0:
        return
    pdi = 100.0 * pdm_s / tr_s
    mdi = 100.0 * mdm_s / tr_s
    di_sum = pdi + mdi
    dx = 100.0 * abs(pdi - mdi) / di_sum if di_sum > 0 else 0.0
    context['dx_list'].append(dx)
    if len(context['dx_list']) < n:
        return
    dx_s = 0.0
    for k in range(-n, 0):
        dx_s += context['dx_list'][k]
    adx = dx_s / n
    context['adx_list'].append(adx)


# -------- main --------
def handle_bar(context, bar):
    history = context['history']
    history.append(bar)
    i = len(history)

    _update_adx(context)

    c = bar['close']
    h_ = bar['high']
    l_ = bar['low']
    v = bar.get('volume', 0)
    tstr = bar.get('time', '')
    hm = tstr[11:16] if len(tstr) >= 16 else ''
    pos = context.get('position', 0)

    # ---- VWAP 累计 ----
    key = _sess_key(tstr, context['sess_key'])
    if key != context['sess_key']:
        context['sess_key'] = key
        context['cum_pv'] = 0.0
        context['cum_v'] = 0.0
    tp = (h_ + l_ + c) / 3.0
    context['cum_pv'] += tp * v
    context['cum_v'] += v
    vwap = context['cum_pv'] / context['cum_v'] if context['cum_v'] > 0 else c

    warmup = context['ema_len'] + context['atr_len'] + 20
    if i < warmup:
        return

    # ---- 指标 ----
    atr = _atr(context)
    if atr is None or atr <= 0:
        return

    closes = [b['close'] for b in history]
    rsi_val = rsi(closes, context['rsi_len'])[-1]
    ema_val = ema(closes, context['ema_len'])[-1]

    # ADX 震荡过滤
    if len(context['adx_list']) < 1:
        return
    adx_val = context['adx_list'][-1]
    if adx_val >= context['adx_max']:
        return

    # ---- 日内强平（14:55~15:05, 22:55~23:00）----
    force = (hm >= '14:55' and hm <= '15:05') or (hm >= '22:55' and hm <= '23:00')
    if pos != 0 and force:
        if pos > 0:
            context['_action'] = 'sell'
        else:
            context['_action'] = 'cover'
        context['_price'] = c
        context['_reason'] = '强平 %.1f' % c
        context['stop'] = None
        context['take_profit'] = None
        context['entry_bar'] = None
        return

    # ---- 持仓管理 ----
    if pos != 0 and context['stop'] is not None:
        hit = False
        if pos > 0:
            if l_ <= context['stop']:
                context['_action'] = 'sell'
                context['_price'] = context['stop']
                context['_reason'] = '多/止损 %.1f' % context['stop']
                hit = True
            elif h_ >= context['take_profit']:
                context['_action'] = 'sell'
                context['_price'] = context['take_profit']
                context['_reason'] = '多/止盈 %.1f' % context['take_profit']
                hit = True
        else:
            if h_ >= context['stop']:
                context['_action'] = 'cover'
                context['_price'] = context['stop']
                context['_reason'] = '空/止损 %.1f' % context['stop']
                hit = True
            elif l_ <= context['take_profit']:
                context['_action'] = 'cover'
                context['_price'] = context['take_profit']
                context['_reason'] = '空/止盈 %.1f' % context['take_profit']
                hit = True

        if not hit and context['entry_bar'] is not None:
            if i - context['entry_bar'] >= context['time_stop']:
                if pos > 0:
                    context['_action'] = 'sell'
                else:
                    context['_action'] = 'cover'
                context['_price'] = c
                context['_reason'] = '时间离场 %.1f' % c
                hit = True

        if hit:
            context['stop'] = None
            context['take_profit'] = None
            context['entry_bar'] = None
            return
        return

    # ---- 入场信号（三重确认）----
    # 确认1: 方向过滤
    long_dir = c > ema_val
    short_dir = c < ema_val

    # 确认2: VWAP偏离（价格必须远离公允值），vwap_dev=0时禁用
    dev = context['vwap_dev'] * atr
    if context['vwap_dev'] > 0:
        long_deviated = c < vwap - dev
        short_deviated = c > vwap + dev
    else:
        long_deviated = True
        short_deviated = True

    # 确认3: RSI极值 + 组合确认
    long_signal = (rsi_val < context['long_rsi']
                   and long_dir
                   and long_deviated)

    short_signal = (rsi_val > context['short_rsi']
                    and short_dir
                    and short_deviated)

    # 临近强平不开新仓
    if (hm >= '14:40' and hm <= '15:05') or (hm >= '22:40' and hm <= '23:00'):
        return

    if long_signal:
        context['_action'] = 'buy'
        context['_price'] = c
        context['stop'] = c - context['sl_atr'] * atr
        context['take_profit'] = c + context['tp_atr'] * atr
        context['entry_bar'] = i
        context['_reason'] = ('做多 %.1f RSI:%.0f ADX:%.0f V:%.1f 损:%.1f 盈:%.1f' %
                              (c, rsi_val, adx_val, vwap, context['stop'], context['take_profit']))
        return

    if short_signal:
        context['_action'] = 'short'
        context['_price'] = c
        context['stop'] = c + context['sl_atr'] * atr
        context['take_profit'] = c - context['tp_atr'] * atr
        context['entry_bar'] = i
        context['_reason'] = ('做空 %.1f RSI:%.0f ADX:%.0f V:%.1f 损:%.1f 盈:%.1f' %
                              (c, rsi_val, adx_val, vwap, context['stop'], context['take_profit']))
        return
