# ========== RegimeAdaptive 自适应策略（1小时线定稿版）==========
# 移植自 strategy_final.py（2026年1-7月回测: 200笔 +39,198元，每次1手）
#
# 市场状态判断:
#   regime_adx = ADX(14) 的 48 周期滚动均值
#   regime_adx > 25 → 趋势模式: Donchian(48) 突破入场，反向突破出场
#   regime_adx < 25 → 震荡模式: 布林带(24, 2.0) 突破入场，回归中轨出场
#
# 信号在当根K线收盘时产生，下一根K线开盘执行（与原回测一致）。
#
# 接口（与 BacktestEngine 完全兼容）：
#   init(context) / handle_bar(ctx, bar)
#   下单：context['_action'] = 'buy|sell|short|cover|flip_long|flip_short'
#         context['_price'] = 价格  context['_reason'] = '理由'
#   _reason 以 '趋势' 或 '震荡' 开头，便于按模式拆解盈亏。
# =================================================================

def init(context):
    # ---- 策略参数（可在策略参数袋中覆盖）----
    context['dc_period'] = context.get('dc_period', 48)      # Donchian 通道周期
    context['bb_period'] = context.get('bb_period', 24)      # 布林带周期
    context['bb_std'] = context.get('bb_std', 2.0)           # 布林带标准差倍数
    context['adx_period'] = context.get('adx_period', 14)    # ADX 计算周期
    context['adx_smooth'] = context.get('adx_smooth', 48)    # ADX 平滑周期
    context['adx_thresh'] = context.get('adx_thresh', 25.0)  # 趋势/震荡分界线

    # ---- 内部状态 ----
    context['history'] = []
    context['tr_list'] = []    # 真实波幅序列
    context['pdm_list'] = []   # +DM 序列
    context['mdm_list'] = []   # -DM 序列
    context['dx_list'] = []    # DX 序列
    context['adx_list'] = []   # ADX 序列（简单均值版，与 pandas rolling().mean() 一致）
    context['pend_pos'] = 0    # 收盘确定的目标仓位，下一根开盘执行：1=多 -1=空 0=清仓 None=不变


# ---------------------------------------------------------------- helpers
def _mean_tail(arr, n):
    """最后 n 个元素的均值"""
    seg = arr[-n:]
    total = 0.0
    for v in seg:
        total += v
    return total / n


def _update_adx(context, bar):
    """增量更新 ADX（简单移动平均版，与 strategy_final.py 的 rolling().mean() 一致）"""
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

    atr_sma = _mean_tail(context['tr_list'], n)
    if atr_sma <= 0:
        return
    pdi = 100.0 * _mean_tail(context['pdm_list'], n) / atr_sma
    mdi = 100.0 * _mean_tail(context['mdm_list'], n) / atr_sma
    di_sum = pdi + mdi
    if di_sum <= 0:
        return
    dx = 100.0 * abs(pdi - mdi) / di_sum
    context['dx_list'].append(dx)

    if len(context['dx_list']) < n:
        return
    adx = _mean_tail(context['dx_list'], n)
    context['adx_list'].append(adx)


def _regime_adx(context):
    """ADX 平滑值（未就绪返回 None）"""
    m = context['adx_smooth']
    if len(context['adx_list']) < m:
        return None
    return _mean_tail(context['adx_list'], m)


def _donchian(context):
    """Donchian 上下轨（前 dc_period 根，不含当前K线，对应 rolling().max().shift(1)）"""
    history = context['history']
    n = context['dc_period']
    if len(history) < n + 1:
        return None, None
    seg = history[-n - 1:-1]
    hh = max(b['high'] for b in seg)
    ll = min(b['low'] for b in seg)
    return hh, ll


def _boll(context):
    """布林带（中轨/上轨/下轨，样本标准差 ddof=1，与 pandas rolling().std() 一致）"""
    history = context['history']
    n = context['bb_period']
    if len(history) < n:
        return None, None, None
    seg = [b['close'] for b in history[-n:]]
    mid = sum(seg) / n
    var = 0.0
    for v in seg:
        var += (v - mid) * (v - mid)
    sd = (var / (n - 1)) ** 0.5
    m = context['bb_std']
    return mid, mid + m * sd, mid - m * sd


def _exec_pending(context, bar):
    """下一根K线开盘时执行上一根收盘确定的目标仓位"""
    pend = context['pend_pos']
    if pend is None:
        return
    context['pend_pos'] = None
    pos = context.get('position', 0)
    if pend == pos:
        return
    o = bar['open']
    if pend == 0:
        if pos == 1:
            context['_action'] = 'sell'
            context['_price'] = o
            context['_reason'] = '多/开盘平仓 %.1f' % o
        elif pos == -1:
            context['_action'] = 'cover'
            context['_price'] = o
            context['_reason'] = '空/开盘平仓 %.1f' % o
    elif pend == 1:
        if pos == -1:
            context['_action'] = 'flip_long'
            context['_price'] = o
            context['_reason'] = '开盘翻多 %.1f' % o
        elif pos == 0:
            context['_action'] = 'buy'
            context['_price'] = o
            context['_reason'] = '开盘做多 %.1f' % o
    elif pend == -1:
        if pos == 1:
            context['_action'] = 'flip_short'
            context['_price'] = o
            context['_reason'] = '开盘翻空 %.1f' % o
        elif pos == 0:
            context['_action'] = 'short'
            context['_price'] = o
            context['_reason'] = '开盘做空 %.1f' % o


# ---------------------------------------------------------------- main
def handle_bar(context, bar):
    # 1. 开盘先执行上一根收盘挂出的信号
    _exec_pending(context, bar)

    # 2. 记录当前K线并更新指标
    context['history'].append(bar)
    _update_adx(context, bar)

    r_adx = _regime_adx(context)
    if r_adx is None:
        return  # 指标未就绪，保持现状

    is_trend = r_adx > context['adx_thresh']
    hh, ll = _donchian(context)
    mid, upper, lower = _boll(context)
    if hh is None or mid is None:
        return

    c = bar['close']
    h_ = bar['high']
    l_ = bar['low']
    pos = context.get('position', 0)
    target = pos

    # 3. 持仓管理（先检查出场，逻辑与原策略逐bar循环一致）
    if pos == 1:  # 多头持仓
        if is_trend:
            if l_ < ll:
                target = 0
                tag = '趋势 多/反向突破'
        else:
            if c < mid:
                target = 0
                tag = '震荡 多/回归中轨'
    elif pos == -1:  # 空头持仓
        if is_trend:
            if h_ > hh:
                target = 0
                tag = '趋势 空/反向突破'
        else:
            if c > mid:
                target = 0
                tag = '震荡 空/回归中轨'

    # 4. 入场（空仓时；同根K线可先出后进）
    if target == 0:
        if is_trend:
            if h_ > hh:
                target = 1
                tag = '趋势 做多 DC突破'
            elif l_ < ll:
                target = -1
                tag = '趋势 做空 DC突破'
        else:
            if c > upper:
                target = 1
                tag = '震荡 做多 布林突破'
            elif c < lower:
                target = -1
                tag = '震荡 做空 布林突破'

    # 5. 收盘挂出目标仓位，下一根开盘执行
    if target != pos:
        context['pend_pos'] = target
        context['signal_tag'] = '%s ADX:%.0f' % (tag, r_adx)
