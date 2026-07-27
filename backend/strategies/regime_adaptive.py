# ========== 状态自适应双模策略：趋势态跟踪 + 震荡态回归 ==========
# 思路：单一策略无法通吃 —— ADX/ER 判定市场状态，切换两套已验证积木：
#   趋势态（ADX(14)>25 且 ER(25)>0.3）：
#       唐奇安40突破 + EMA60 同侧入场；初始止损 2×ATR；
#       吊灯 3×ATR 移动止损；无止盈。（复用 trend_atr_v2 逻辑）
#   震荡态（ADX(14)<20 且 ER(25)<0.2）：
#       BOLL(20,2) 反转 + EMA200 方向保护；TP 1×ATR / SL 1.5×ATR；
#       20 根K线时间止损。（复用 mean_revert 逻辑）
#   中间态：不开新仓；已有持仓按入场时模式规则继续管理。
#   模式切换时若出现反向信号且有持仓：先市价平仓，下一根按新模式开仓。
#
# 接口（与 BacktestEngine 完全兼容）：
#   init(context) / handle_bar(ctx, bar)
#   下单：context['_action'] = 'buy|sell|short|cover'，_price，_reason
#   _reason 以 '趋势' 或 '回归' 开头，便于按模式拆解盈亏。
# =========================================================================

def init(context):
    # ---- regime 判定 ----
    context['enable_range'] = context.get('enable_range', 1)   # 1=双模（定稿）；0=纯趋势（震荡态空仓）
    context['adx_period'] = context.get('adx_period', 14)
    context['adx_trend'] = context.get('adx_trend', 28.0)      # ADX 高于此 → 趋势态
    context['adx_range'] = context.get('adx_range', 20.0)      # ADX 低于此 → 震荡态
    context['er_len'] = context.get('er_len', 25)
    context['er_trend'] = context.get('er_trend', 0.4)         # ER 高于此 → 趋势态
    context['er_range'] = context.get('er_range', 0.15)        # ER 低于此 → 震荡态

    # ---- 趋势模式参数 ----
    context['donchian_len'] = context.get('donchian_len', 40)
    context['ema_fast_len'] = context.get('ema_fast_len', 60)  # 趋势模式 EMA
    context['t_init_sl'] = context.get('t_init_sl', 2.0)
    context['t_trail'] = context.get('t_trail', 3.0)

    # ---- 回归模式参数 ----
    context['boll_len'] = context.get('boll_len', 20)
    context['boll_mult'] = context.get('boll_mult', 2.0)
    context['ema_slow_len'] = context.get('ema_slow_len', 200)  # 回归模式 EMA 方向保护
    context['r_tp'] = context.get('r_tp', 1.0)
    context['r_sl'] = context.get('r_sl', 1.5)
    context['r_time_stop'] = context.get('r_time_stop', 20)

    # ---- ATR ----
    context['atr_len'] = context.get('atr_len', 14)

    # ---- 内部状态 ----
    context['history'] = []
    context['pos_mode'] = None      # 持仓所属模式：'trend' | 'revert'
    context['stop'] = None
    context['take_profit'] = None
    context['entry_bar'] = None
    context['pos_high'] = None
    context['pos_low'] = None
    context['pend_dir'] = 0         # 模式切换反向平仓后的待开仓方向：1=多 -1=空
    context['pend_mode'] = None

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


def _er(context):
    h = context['history']
    n = context['er_len']
    if len(h) < n + 1:
        return None
    seg = h[-n - 1:]
    change = abs(seg[-1]['close'] - seg[0]['close'])
    vol = 0.0
    for k in range(1, len(seg)):
        vol += abs(seg[k]['close'] - seg[k - 1]['close'])
    if vol <= 0:
        return 0.0
    return change / vol


def _boll(context):
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


def _regime(context):
    """返回 'trend' | 'range' | 'neutral'"""
    adx_val = context['adx_val']
    er = _er(context)
    if adx_val is None or er is None:
        return 'neutral'
    if adx_val > context['adx_trend'] and er > context['er_trend']:
        return 'trend'
    if adx_val < context['adx_range'] and er < context['er_range']:
        return 'range'
    return 'neutral'


def _clear_pos_state(context):
    context['pos_mode'] = None
    context['stop'] = None
    context['take_profit'] = None
    context['entry_bar'] = None
    context['pos_high'] = None
    context['pos_low'] = None


def handle_bar(context, bar):
    history = context['history']
    history.append(bar)
    i = len(history)

    _update_adx(context)

    warmup = context['ema_slow_len'] + context['donchian_len'] + context['atr_len'] + context['er_len'] + 5
    if i < warmup:
        return

    c = bar['close']
    h_ = bar['high']
    l_ = bar['low']
    pos = context.get('position', 0)
    atr = _atr(context)
    if atr is None or atr <= 0:
        return

    # ================================================================
    # 1. 持仓管理（按入场时模式）
    # ================================================================
    if pos != 0 and context['pos_mode'] is not None:
        hit = False
        if context['pos_mode'] == 'trend':
            # 吊灯移动止损
            if pos == 1:
                if context['pos_high'] is None or h_ > context['pos_high']:
                    context['pos_high'] = h_
                trail = context['pos_high'] - context['t_trail'] * atr
                if trail > context['stop']:
                    context['stop'] = trail
                if l_ <= context['stop']:
                    context['_action'] = 'sell'
                    context['_price'] = context['stop']
                    context['_reason'] = '趋势 多/吊灯 %.1f' % context['stop']
                    hit = True
            else:
                if context['pos_low'] is None or l_ < context['pos_low']:
                    context['pos_low'] = l_
                trail = context['pos_low'] + context['t_trail'] * atr
                if trail < context['stop']:
                    context['stop'] = trail
                if h_ >= context['stop']:
                    context['_action'] = 'cover'
                    context['_price'] = context['stop']
                    context['_reason'] = '趋势 空/吊灯 %.1f' % context['stop']
                    hit = True
        else:
            # 回归模式：TP / SL / 时间止损
            if pos == 1:
                if l_ <= context['stop']:
                    context['_action'] = 'sell'
                    context['_price'] = context['stop']
                    context['_reason'] = '回归 多/止损 %.1f' % context['stop']
                    hit = True
                elif h_ >= context['take_profit']:
                    context['_action'] = 'sell'
                    context['_price'] = context['take_profit']
                    context['_reason'] = '回归 多/止盈 %.1f' % context['take_profit']
                    hit = True
            else:
                if h_ >= context['stop']:
                    context['_action'] = 'cover'
                    context['_price'] = context['stop']
                    context['_reason'] = '回归 空/止损 %.1f' % context['stop']
                    hit = True
                elif l_ <= context['take_profit']:
                    context['_action'] = 'cover'
                    context['_price'] = context['take_profit']
                    context['_reason'] = '回归 空/止盈 %.1f' % context['take_profit']
                    hit = True
            if not hit and context['entry_bar'] is not None:
                if i - context['entry_bar'] >= context['r_time_stop']:
                    if pos == 1:
                        context['_action'] = 'sell'
                        context['_price'] = c
                        context['_reason'] = '回归 多/时间离场 %.1f' % c
                    else:
                        context['_action'] = 'cover'
                        context['_price'] = c
                        context['_reason'] = '回归 空/时间离场 %.1f' % c
                    hit = True

        if hit:
            _clear_pos_state(context)
            return

        # ---- 模式切换：出现反向信号 → 先平仓，挂单下一根开新仓 ----
        rg = _regime(context)
        sig_dir = 0      # 新模式信号方向：1=多 -1=空
        sig_mode = None
        closes = [b['close'] for b in history]

        if rg == 'trend':
            n = context['donchian_len']
            if i >= n + 1:
                dc_hi = max(b['high'] for b in history[-n - 1:-1])
                dc_lo = min(b['low'] for b in history[-n - 1:-1])
                ema60 = ema(closes, context['ema_fast_len'])[-1]
                if c >= dc_hi and c > ema60:
                    sig_dir = 1
                    sig_mode = 'trend'
                elif c <= dc_lo and c < ema60:
                    sig_dir = -1
                    sig_mode = 'trend'
        elif rg == 'range' and context['enable_range']:
            mid, upper, lower = _boll(context)
            if mid is not None:
                ema200 = ema(closes, context['ema_slow_len'])[-1]
                if c < lower and c > ema200:
                    sig_dir = 1
                    sig_mode = 'revert'
                elif c > upper and c < ema200:
                    sig_dir = -1
                    sig_mode = 'revert'

        if sig_dir != 0 and sig_dir != pos:
            # 反向信号：市价平仓当前持仓
            if pos == 1:
                context['_action'] = 'sell'
                context['_price'] = c
                context['_reason'] = '%s 多/模式切换平仓 %.1f' % ('趋势' if context['pos_mode'] == 'trend' else '回归', c)
            else:
                context['_action'] = 'cover'
                context['_price'] = c
                context['_reason'] = '%s 空/模式切换平仓 %.1f' % ('趋势' if context['pos_mode'] == 'trend' else '回归', c)
            context['pend_dir'] = sig_dir
            context['pend_mode'] = sig_mode
            _clear_pos_state(context)
            return
        return  # 有持仓不开同向新仓

    # ================================================================
    # 2. 执行模式切换后的挂单（下一根入场）
    # ================================================================
    if context['pend_dir'] != 0:
        d = context['pend_dir']
        md = context['pend_mode']
        context['pend_dir'] = 0
        context['pend_mode'] = None
        if d == 1:
            context['_action'] = 'buy'
        else:
            context['_action'] = 'short'
        context['_price'] = c
        context['pos_mode'] = md
        context['entry_bar'] = i
        if md == 'trend':
            if d == 1:
                context['stop'] = c - context['t_init_sl'] * atr
                context['pos_high'] = h_
            else:
                context['stop'] = c + context['t_init_sl'] * atr
                context['pos_low'] = l_
            context['take_profit'] = None
        else:
            if d == 1:
                context['stop'] = c - context['r_sl'] * atr
                context['take_profit'] = c + context['r_tp'] * atr
            else:
                context['stop'] = c + context['r_sl'] * atr
                context['take_profit'] = c - context['r_tp'] * atr
        context['_reason'] = '%s %s %.1f（切换入场）' % (
            '趋势' if md == 'trend' else '回归', '做多' if d == 1 else '做空', c)
        return

    # ================================================================
    # 3. 无持仓：按 regime 找入场信号
    # ================================================================
    rg = _regime(context)
    closes = [b['close'] for b in history]

    if rg == 'trend':
        n = context['donchian_len']
        if i < n + 1:
            return
        dc_hi = max(b['high'] for b in history[-n - 1:-1])
        dc_lo = min(b['low'] for b in history[-n - 1:-1])
        ema60 = ema(closes, context['ema_fast_len'])[-1]
        adx_val = context['adx_val']

        if c >= dc_hi and c > ema60:
            context['_action'] = 'buy'
            context['_price'] = c
            context['stop'] = c - context['t_init_sl'] * atr
            context['take_profit'] = None
            context['pos_high'] = h_
            context['pos_low'] = None
            context['pos_mode'] = 'trend'
            context['entry_bar'] = i
            context['_reason'] = '趋势 做多 %.1f ADX:%.0f 损:%.1f' % (c, adx_val, context['stop'])
            return
        if c <= dc_lo and c < ema60:
            context['_action'] = 'short'
            context['_price'] = c
            context['stop'] = c + context['t_init_sl'] * atr
            context['take_profit'] = None
            context['pos_high'] = None
            context['pos_low'] = l_
            context['pos_mode'] = 'trend'
            context['entry_bar'] = i
            context['_reason'] = '趋势 做空 %.1f ADX:%.0f 损:%.1f' % (c, adx_val, context['stop'])
            return

    elif rg == 'range' and context['enable_range']:
        mid, upper, lower = _boll(context)
        if mid is None:
            return
        ema200 = ema(closes, context['ema_slow_len'])[-1]
        adx_val = context['adx_val']

        if c < lower and c > ema200:
            context['_action'] = 'buy'
            context['_price'] = c
            context['stop'] = c - context['r_sl'] * atr
            context['take_profit'] = c + context['r_tp'] * atr
            context['pos_mode'] = 'revert'
            context['entry_bar'] = i
            context['_reason'] = '回归 做多 %.1f 损:%.1f 盈:%.1f ADX:%.0f' % (
                c, context['stop'], context['take_profit'], adx_val)
            return
        if c > upper and c < ema200:
            context['_action'] = 'short'
            context['_price'] = c
            context['stop'] = c + context['r_sl'] * atr
            context['take_profit'] = c - context['r_tp'] * atr
            context['pos_mode'] = 'revert'
            context['entry_bar'] = i
            context['_reason'] = '回归 做空 %.1f 损:%.1f 盈:%.1f ADX:%.0f' % (
                c, context['stop'], context['take_profit'], adx_val)
            return
