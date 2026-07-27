# ========== 唐奇安通道 + EMA + ADX 趋势跟踪策略（吊灯移动止损） ==========
# 设计目标：Calmar 比率（总收益 / 最大回撤）最大化 —— 平均回撤小、盈利高。
#
# 规则（多空对称）：
#   【入场】收盘价突破过去 N 根K线（不含当前）最高/最低点（唐奇安通道）
#           + 收盘价在 EMA(ema_len) 同侧
#           + ADX(adx_period) > adx_threshold 才允许开仓
#           + 已有持仓不加仓
#   【初始止损】开仓价 ∓ init_sl_atr × ATR(atr_period)
#   【出场】吊灯移动止损：多头跟踪「持仓以来最高价 − trail_atr × ATR」，
#           空头镜像；止损只向有利方向移动（只升不降 / 只降不升）。
#           不设固定止盈，不做保本止损（保本止损会杀死趋势）。
#
# 接口（与 BacktestEngine 完全兼容）：
#   init(context) / handle_bar(ctx, bar)
#   下单：context['_action'] = 'buy|sell|short|cover'，_price，_reason
#   内置函数：sma, ema, rsi, calc_verts
#   注意：引擎 __builtins__ 受限，仅可用 len/range/min/max/abs/sum/int/
#         float/list/dict/all/any/sorted/round/str/enumerate/zip/Exception
# =========================================================================

def init(context):
    # ---- 入场 ----
    context['donchian_len'] = context.get('donchian_len', 40)      # 唐奇安通道周期（不含当前K线）
    context['ema_len'] = context.get('ema_len', 60)                # 趋势过滤 EMA
    context['adx_period'] = context.get('adx_period', 14)          # ADX Wilder 周期
    context['adx_threshold'] = context.get('adx_threshold', 25.0)  # ADX 开仓阈值

    # ---- 止损 / 移动止损 ----
    context['atr_period'] = context.get('atr_period', 14)          # ATR 周期（简单均值）
    context['init_sl_atr'] = context.get('init_sl_atr', 2.0)       # 初始止损 ATR 倍数
    context['trail_atr'] = context.get('trail_atr', 3.0)           # 吊灯止损 ATR 倍数

    # ---- 内部状态 ----
    context['history'] = []
    context['stop'] = None          # 当前止损价
    context['pos_high'] = None      # 持仓以来最高价（多头）
    context['pos_low'] = None       # 持仓以来最低价（空头）

    # ADX Wilder 平滑状态（实现方式同 eagle_ladder_k_adx）
    context['adx_tr_s'] = None
    context['adx_pdm_s'] = None
    context['adx_mdm_s'] = None
    context['adx_val'] = None
    context['adx_dx_buf'] = []
    context['adx_raw_n'] = 0


# ---------------------------------------------------------------- helpers
def _atr(context):
    """近 atr_period 根简单 ATR"""
    h = context['history']
    n = context['atr_period']
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


def _update_adx(context):
    """标准 Wilder ADX 增量更新（同 eagle_ladder_k_adx 的实现方式）"""
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

    warmup = context['ema_len'] + context['atr_period'] + context['adx_period'] + 5
    if i < warmup:
        return

    c = bar['close']
    h_ = bar['high']
    l_ = bar['low']
    pos = context.get('position', 0)

    # ================================================================
    # 1. 持仓：吊灯移动止损（先更新止损，再判定是否触发）
    # ================================================================
    if pos != 0 and context['stop'] is not None:
        atr_now = _atr(context)
        if pos == 1:
            # 更新持仓以来最高价
            if context['pos_high'] is None or h_ > context['pos_high']:
                context['pos_high'] = h_
            if atr_now is not None:
                trail = context['pos_high'] - context['trail_atr'] * atr_now
                if trail > context['stop']:      # 止损只升不降
                    context['stop'] = trail
            if l_ <= context['stop']:
                context['_action'] = 'sell'
                context['_price'] = context['stop']
                context['_reason'] = '趋势ATR 多止损/吊灯 %.1f ADX:%.0f' % (
                    context['stop'], context['adx_val'] if context['adx_val'] is not None else -1)
                context['stop'] = None
                context['pos_high'] = None
                context['pos_low'] = None
                return
        else:
            if context['pos_low'] is None or l_ < context['pos_low']:
                context['pos_low'] = l_
            if atr_now is not None:
                trail = context['pos_low'] + context['trail_atr'] * atr_now
                if trail < context['stop']:      # 止损只降不升
                    context['stop'] = trail
            if h_ >= context['stop']:
                context['_action'] = 'cover'
                context['_price'] = context['stop']
                context['_reason'] = '趋势ATR 空止损/吊灯 %.1f ADX:%.0f' % (
                    context['stop'], context['adx_val'] if context['adx_val'] is not None else -1)
                context['stop'] = None
                context['pos_high'] = None
                context['pos_low'] = None
                return
        return  # 已有持仓不加仓

    # ================================================================
    # 2. 入场：唐奇安突破 + EMA 同侧 + ADX 过滤
    # ================================================================
    n = context['donchian_len']
    if i < n + 1:
        return

    donchian_high = max(b['high'] for b in history[-n - 1:-1])
    donchian_low = min(b['low'] for b in history[-n - 1:-1])

    closes = [b['close'] for b in history]
    ema_val = ema(closes, context['ema_len'])[-1]

    adx_val = context['adx_val']
    adx_ok = (adx_val is not None) and (adx_val > context['adx_threshold'])

    atr = _atr(context)
    if atr is None or atr <= 0:
        return

    # ---- 做多 ----
    if c >= donchian_high and c > ema_val and adx_ok:
        context['_action'] = 'buy'
        context['_price'] = c
        context['stop'] = c - context['init_sl_atr'] * atr
        context['pos_high'] = h_
        context['pos_low'] = None
        context['_reason'] = '趋势ATR 做多 %.1f DC:%.0f EMA:%.0f ADX:%.0f 损:%.1f' % (
            c, donchian_high, ema_val, adx_val, context['stop'])
        return

    # ---- 做空 ----
    if c <= donchian_low and c < ema_val and adx_ok:
        context['_action'] = 'short'
        context['_price'] = c
        context['stop'] = c + context['init_sl_atr'] * atr
        context['pos_high'] = None
        context['pos_low'] = l_
        context['_reason'] = '趋势ATR 做空 %.1f DC:%.0f EMA:%.0f ADX:%.0f 损:%.1f' % (
            c, donchian_low, ema_val, adx_val, context['stop'])
        return
