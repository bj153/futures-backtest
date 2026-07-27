# ========== 均值回归策略：BOLL 反转 + EMA 方向保护 + ADX 震荡过滤 ==========
# 适用场景：震荡市（本组合 23 个品种中 22 个在回测区间为震荡市）。
# 主战场：15m（固定 1 手）。
#
# 规则（多空对称）：
#   【入场】BOLL(boll_len, boll_mult)：收盘价跌破下轨 → 下一根K线做多；
#           收盘价突破上轨 → 下一根K线做空。
#   【方向保护】use_ema_filter=1 时：收盘 > EMA(ema_len) 只做多，
#               < EMA 只做空；use_ema_filter=2 时允许双向，但逆 EMA 方向
#               要求更深偏离（boll_mult × counter_mult 的通道才触发）。
#   【震荡过滤】ADX(adx_period) < adx_max 才允许开仓（与趋势策略互斥）。
#   【出场】止盈 tp_atr × ATR(atr_len)（按入场时 ATR 定价），
#           止损 sl_atr × ATR；持仓 time_stop 根K线未触任一端 → 市价离场。
#
# 接口（与 BacktestEngine 完全兼容）：
#   init(context) / handle_bar(ctx, bar)
#   下单：context['_action'] = 'buy|sell|short|cover'，_price，_reason
#   注意：引擎 __builtins__ 受限，仅可用 len/range/min/max/abs/sum/int/
#         float/list/dict/all/any/sorted/round/str/enumerate/zip/Exception
# =========================================================================

def init(context):
    # ---- 布林通道 ----
    context['boll_len'] = context.get('boll_len', 20)          # BOLL 周期
    context['boll_mult'] = context.get('boll_mult', 2.0)       # 标准差倍数

    # ---- 方向保护 ----
    context['use_ema_filter'] = context.get('use_ema_filter', 1)  # 0=关闭 1=只顺EMA 2=双向但逆向更深
    context['ema_len'] = context.get('ema_len', 200)
    context['counter_mult'] = context.get('counter_mult', 1.25)   # 逆 EMA 方向要求的通道倍数放大

    # ---- 震荡过滤 ----
    context['adx_period'] = context.get('adx_period', 14)
    context['adx_max'] = context.get('adx_max', 25.0)          # ADX 低于该值才开仓

    # ---- 入场方式 ----
    context['entry_mode'] = context.get('entry_mode', 'break')  # 'break'=突破即挂单下一根 | 'reentry'=收回通道内才入场
    context['tp_mode'] = context.get('tp_mode', 'atr')          # 'atr'=固定ATR止盈 | 'mid'=中轨止盈

    # ---- 出场 ----
    context['atr_len'] = context.get('atr_len', 14)
    context['tp_atr'] = context.get('tp_atr', 1.0)             # 止盈 ATR 倍数
    context['sl_atr'] = context.get('sl_atr', 1.5)             # 止损 ATR 倍数
    context['time_stop'] = context.get('time_stop', 20)        # 持仓K线数上限

    # ---- 内部状态 ----
    context['history'] = []
    context['stop'] = None
    context['take_profit'] = None
    context['entry_bar'] = None
    context['pend_long'] = 0      # 上一根触发做多，本根执行
    context['pend_short'] = 0
    context['pend_mid'] = None    # 触发时中轨（tp_mode='mid' 用）

    # ADX Wilder 平滑状态
    context['adx_tr_s'] = None
    context['adx_pdm_s'] = None
    context['adx_mdm_s'] = None
    context['adx_val'] = None
    context['adx_dx_buf'] = []
    context['adx_raw_n'] = 0


# ---------------------------------------------------------------- helpers
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


def _boll(context):
    """返回 (mid, upper, lower)，基于最近 boll_len 根收盘价（含当前）"""
    h = context['history']
    n = context['boll_len']
    if len(h) < n:
        return None, None, None
    seg = [b['close'] for b in h[-n:]]
    mid = sum(seg) / n
    var = 0.0
    for v in seg:
        var += (v - mid) * (v - mid)
    sd = (var / n) ** 0.5
    m = context['boll_mult']
    return mid, mid + m * sd, mid - m * sd


def _update_adx(context):
    h = context['history']
    n = context['adx_period']
    if len(h) < 2:
        return
    cur = h[-1]
    prev = h[-2]

    tr = max(cur['high'] - cur['low'],
             abs(cur['high'] - prev['close']),
             abs(cur['low'] - prev['close']))
    up_move = cur['high'] - prev['high']
    dn_move = prev['low'] - cur['low']
    pdm = up_move if (up_move > dn_move and up_move > 0) else 0.0
    mdm = dn_move if (dn_move > up_move and dn_move > 0) else 0.0

    context['adx_raw_n'] += 1

    if context['adx_tr_s'] is None:
        if context['adx_raw_n'] < n:
            context['adx_dx_buf'].append((tr, pdm, mdm))
            return
        elif context['adx_raw_n'] == n:
            context['adx_dx_buf'].append((tr, pdm, mdm))
            tr_s = 0.0
            pdm_s = 0.0
            mdm_s = 0.0
            for t, p, m in context['adx_dx_buf']:
                tr_s += t
                pdm_s += p
                mdm_s += m
            context['adx_tr_s'] = tr_s
            context['adx_pdm_s'] = pdm_s
            context['adx_mdm_s'] = mdm_s
            context['adx_dx_buf'] = []
            return
    else:
        context['adx_tr_s'] = context['adx_tr_s'] - context['adx_tr_s'] / n + tr
        context['adx_pdm_s'] = context['adx_pdm_s'] - context['adx_pdm_s'] / n + pdm
        context['adx_mdm_s'] = context['adx_mdm_s'] - context['adx_mdm_s'] / n + mdm

    tr_s = context['adx_tr_s']
    if tr_s is None or tr_s <= 0:
        return
    pdi = 100.0 * context['adx_pdm_s'] / tr_s
    mdi = 100.0 * context['adx_mdm_s'] / tr_s
    di_sum = pdi + mdi
    if di_sum <= 0:
        dx = 0.0
    else:
        dx = 100.0 * abs(pdi - mdi) / di_sum

    if context['adx_val'] is None:
        context['adx_dx_buf'].append(dx)
        if len(context['adx_dx_buf']) >= n:
            total = 0.0
            for d in context['adx_dx_buf']:
                total += d
            context['adx_val'] = total / n
            context['adx_dx_buf'] = []
    else:
        context['adx_val'] = (context['adx_val'] * (n - 1) + dx) / n


def handle_bar(context, bar):
    history = context['history']
    history.append(bar)
    i = len(history)

    _update_adx(context)

    warmup = context['ema_len'] + context['boll_len'] + context['atr_len'] + 5
    if i < warmup:
        return

    c = bar['close']
    h_ = bar['high']
    l_ = bar['low']
    pos = context.get('position', 0)

    # ================================================================
    # 1. 持仓：止盈 / 止损 / 时间止损
    # ================================================================
    if pos != 0 and context['stop'] is not None:
        hit = False
        if pos == 1:
            if l_ <= context['stop']:
                context['_action'] = 'sell'
                context['_price'] = context['stop']
                context['_reason'] = '均值回归 多止损 %.1f' % context['stop']
                hit = True
            elif h_ >= context['take_profit']:
                context['_action'] = 'sell'
                context['_price'] = context['take_profit']
                context['_reason'] = '均值回归 多止盈 %.1f' % context['take_profit']
                hit = True
        else:
            if h_ >= context['stop']:
                context['_action'] = 'cover'
                context['_price'] = context['stop']
                context['_reason'] = '均值回归 空止损 %.1f' % context['stop']
                hit = True
            elif l_ <= context['take_profit']:
                context['_action'] = 'cover'
                context['_price'] = context['take_profit']
                context['_reason'] = '均值回归 空止盈 %.1f' % context['take_profit']
                hit = True

        # 时间止损：持仓 time_stop 根K线未触任一端 → 市价离场
        if not hit and context['entry_bar'] is not None:
            if i - context['entry_bar'] >= context['time_stop']:
                if pos == 1:
                    context['_action'] = 'sell'
                    context['_price'] = c
                    context['_reason'] = '均值回归 多/时间离场 %.1f' % c
                else:
                    context['_action'] = 'cover'
                    context['_price'] = c
                    context['_reason'] = '均值回归 空/时间离场 %.1f' % c
                hit = True

        if hit:
            context['stop'] = None
            context['take_profit'] = None
            context['entry_bar'] = None
            return
        return  # 有持仓不开新仓

    # ================================================================
    # 2. 执行上一根K线触发的挂单（下一根入场）
    # ================================================================
    atr = _atr(context)
    if atr is None or atr <= 0:
        context['pend_long'] = 0
        context['pend_short'] = 0
        return

    if context['pend_long']:
        context['pend_long'] = 0
        context['_action'] = 'buy'
        context['_price'] = c
        context['stop'] = c - context['sl_atr'] * atr
        if context['tp_mode'] == 'mid' and context.get('pend_mid') is not None:
            context['take_profit'] = context['pend_mid']
        else:
            context['take_profit'] = c + context['tp_atr'] * atr
        context['entry_bar'] = i
        context['_reason'] = '均值回归 做多 %.1f 损:%.1f 盈:%.1f ADX:%.0f' % (
            c, context['stop'], context['take_profit'],
            context['adx_val'] if context['adx_val'] is not None else -1)
        return

    if context['pend_short']:
        context['pend_short'] = 0
        context['_action'] = 'short'
        context['_price'] = c
        context['stop'] = c + context['sl_atr'] * atr
        if context['tp_mode'] == 'mid' and context.get('pend_mid') is not None:
            context['take_profit'] = context['pend_mid']
        else:
            context['take_profit'] = c - context['tp_atr'] * atr
        context['entry_bar'] = i
        context['_reason'] = '均值回归 做空 %.1f 损:%.1f 盈:%.1f ADX:%.0f' % (
            c, context['stop'], context['take_profit'],
            context['adx_val'] if context['adx_val'] is not None else -1)
        return

    # ================================================================
    # 3. 信号判定（本根收盘触发，下一根入场）
    # ================================================================
    mid, upper, lower = _boll(context)
    if mid is None:
        return

    # ADX 震荡过滤
    adx_val = context['adx_val']
    if adx_val is None or adx_val >= context['adx_max']:
        return

    closes = [b['close'] for b in history]
    ema_val = ema(closes, context['ema_len'])[-1]

    # 方向保护
    mode = context['use_ema_filter']
    long_ok = True
    short_ok = True
    up_band = upper
    dn_band = lower
    if mode == 1:
        if c > ema_val:
            short_ok = False
        elif c < ema_val:
            long_ok = False
    elif mode == 2:
        # 允许双向，但逆 EMA 方向要求更深偏离
        width = (upper - mid) * (context['counter_mult'] - 1.0)
        if c > ema_val:
            up_band = upper + width   # 逆势做空需要更深突破
        elif c < ema_val:
            dn_band = lower - width   # 逆势做多需要更深跌破

    if context['entry_mode'] == 'reentry':
        # 收回确认：上一根收在通道外，本根收回通道内 → 立即入场
        pc = history[-2]['close']
        long_trig = long_ok and pc < dn_band and c >= dn_band
        short_trig = short_ok and pc > up_band and c <= up_band
        if long_trig:
            context['_action'] = 'buy'
            context['_price'] = c
            context['stop'] = c - context['sl_atr'] * atr
            if context['tp_mode'] == 'mid':
                context['take_profit'] = mid
            else:
                context['take_profit'] = c + context['tp_atr'] * atr
            context['entry_bar'] = i
            context['_reason'] = '均值回归 多/收回 %.1f 损:%.1f 盈:%.1f ADX:%.0f' % (
                c, context['stop'], context['take_profit'], adx_val)
            return
        if short_trig:
            context['_action'] = 'short'
            context['_price'] = c
            context['stop'] = c + context['sl_atr'] * atr
            if context['tp_mode'] == 'mid':
                context['take_profit'] = mid
            else:
                context['take_profit'] = c - context['tp_atr'] * atr
            context['entry_bar'] = i
            context['_reason'] = '均值回归 空/收回 %.1f 损:%.1f 盈:%.1f ADX:%.0f' % (
                c, context['stop'], context['take_profit'], adx_val)
            return
        return

    if long_ok and c < dn_band:
        context['pend_long'] = 1
        context['pend_mid'] = mid
    elif short_ok and c > up_band:
        context['pend_short'] = 1
        context['pend_mid'] = mid
