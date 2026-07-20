# ========== 极地之鹰 · 阶梯双K交易法则（ADX 趋势强度过滤版） ==========
# 出处：《交易的真相：从1000到1.83亿》（极地之鹰）
#   第9章「阶梯双K交易法则」+ 第4章「ADX 20 以下市场无趋势」
#
# 与 eagle_ladder_k.py 的差异（其余逻辑完全一致）：
#   1. 新增 ADX 趋势强度开关：仅当 ADX(adx_period) > adx_threshold 时
#      才允许开仓，用于过滤小周期上的假突破（书中思路：ADX<20 无趋势）。
#      - ADX 采用标准 Wilder 算法手写实现（TR / +DM / -DM Wilder 平滑 →
#        +DI / -DI → DX → ADX 平滑），取值范围 0~100。
#      - use_adx_filter=0 时完全退化为原策略（ADX 不参与任何判断）。
#   2. 平仓/止损/止盈默认不受 ADX 影响（持仓中 ADX 走弱不强平）；
#      可选参数 exit_on_weak_adx=1 时，持仓中 ADX 跌破阈值则市价平仓。
#
# 规则要点（继承自原著第9章，OCR 整理版）：
#   【趋势判定】价格在 SMA24 同侧 + 未形成有效的反向结构（下跌结构禁多，
#     直到其最后一个道氏高点被向上突破才恢复；做空镜像）。
#   【进场】突破前两根K线最高/最低价；止损距离超过 max_risk_ratio×ATR 放弃。
#   【止损/止盈】道氏低点-1tick / 道氏高点+1tick；1:1 盈亏比 + 成本点。
#   【再进场】有持仓不加仓；平仓后反向运行 reentry_bars 根K线才允许同向再进场。
#   【道氏点】两个同向极点之间的反向极值点，中间K线数 >= dow_gap（原著=1）。
#
# 接口（与 BacktestEngine 完全兼容）：
#   init(context) / handle_bar(ctx, bar)
#   下单：context['_action'] = 'buy|sell|short|cover'，_price，_reason
#   注意：引擎 __builtins__ 受限，仅可用 len/range/min/max/abs/sum/int/
#         float/list/dict/all/any/sorted/round/str/enumerate/zip/Exception
# =========================================================================

def init(context):
    # ---- 趋势判定 ----
    context['sma_period'] = context.get('ema_fast', 24)   # SMA 周期（原著 24）
    context['use_structure_filter'] = context.get('use_structure_filter', 1)  # 1=启用下跌/上涨结构过滤

    # ---- ADX 趋势强度过滤（本版新增） ----
    context['use_adx_filter'] = context.get('use_adx_filter', 1)   # 1=启用；0=完全退化为原策略
    context['adx_period'] = context.get('adx_period', 14)          # Wilder 平滑周期
    context['adx_threshold'] = context.get('adx_threshold', 20.0)  # 开仓阈值（书中：20 以下无趋势）
    context['exit_on_weak_adx'] = context.get('exit_on_weak_adx', 0)  # 1=持仓中 ADX 跌破阈值则平仓

    # ---- 道氏点 ----
    context['dow_gap'] = context.get('dow_gap', 1)        # 极点间最少间隔K线数（原著简化=1）
    context['dow_lookback'] = context.get('dow_lookback', 40)  # 道氏点搜索窗口

    # ---- 止损止盈 ----
    context['tick'] = context.get('tick', 1.0)            # 最小变动价位
    context['rr_ratio'] = context.get('rr_ratio', 1.0)    # 盈亏比（原著 1:1）
    context['tp_extra_ticks'] = context.get('tp_extra_ticks', 1)  # 止盈外加 tick 数覆盖成本

    # ---- 进场风险过滤（书中人工判断 → 参数化） ----
    context['atr_n'] = context.get('atr_n', 14)           # ATR 窗口
    context['max_risk_ratio'] = context.get('max_risk_ratio', 5.0)  # 止损距离 <= 该倍数×ATR，否则放弃；0=不过滤

    # ---- 再进场限制 ----
    context['reentry_bars'] = context.get('reentry_bars', 2)  # 平仓后反向运行至少 N 根K线才允许再次进场

    # ---- 内部状态 ----
    context['history'] = []
    context['stop_loss'] = None
    context['take_profit'] = None

    # ADX Wilder 平滑状态
    context['adx_tr_s'] = None    # TR 平滑值
    context['adx_pdm_s'] = None   # +DM 平滑值
    context['adx_mdm_s'] = None   # -DM 平滑值
    context['adx_val'] = None     # 当前 ADX
    context['adx_dx_buf'] = []    # DX 缓冲（首个 ADX = 前 adx_period 个 DX 均值）
    context['adx_raw_n'] = 0      # 已累积的 TR/DM 样本数

    # 结构状态：'none' | 'down'（下跌结构成立，禁多） | 'up'（上涨结构成立，禁空）
    context['bear_struct'] = 0            # 1 = 有效下跌结构形成中（禁做多）
    context['bear_last_dow_high'] = None  # 下跌结构期间最后一个道氏高点（突破它恢复做多）
    context['bull_struct'] = 0            # 1 = 有效上涨结构形成中（禁做空）
    context['bull_last_dow_low'] = None   # 上涨结构期间最后一个道氏低点（跌破它恢复做空）

    # 触发监视（用于判定结构）：记录最近一次进场信号触发K线
    context['trig_long_idx'] = None       # 多头触发K线索引（未过前高前跌破其低点 → 下跌结构）
    context['trig_long_low'] = None
    context['trig_long_prev_high'] = None # 触发前的前高（须先被突破，否则触发失败）
    context['trig_short_idx'] = None
    context['trig_short_high'] = None
    context['trig_short_prev_low'] = None

    # 平仓后的回调确认
    context['cool_dir'] = 0      # 刚平掉的方向：1=平多 需向下回调，-1=平空 需向上反弹
    context['cool_count'] = 0    # 已反向运行的K线数


# ---------------------------------------------------------------- helpers
def _atr(context):
    """近 atr_n 根简单 ATR（用 history 尾部计算）"""
    h = context['history']
    n = context['atr_n']
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
    """标准 Wilder ADX 增量更新（每根K线调用一次，history 已含当前K线）。
    TR / +DM / -DM 先以 adx_period 个样本求和初始化，之后 Wilder 平滑；
    DX = 100*|+DI - -DI| / (+DI + -DI)；ADX 同样先均值初始化再平滑。
    结果写入 context['adx_val']（未成熟时保持 None）。"""
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
        # 累积阶段：攒够 n 个样本后求和初始化
        if context['adx_raw_n'] < n:
            context['adx_dx_buf'].append((tr, pdm, mdm))  # 暂存原始值
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
            return  # 初始化当根不产生 DX（从下一根开始有平滑值）
    else:
        # Wilder 平滑：S = S - S/n + x
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


def _dow_points(context):
    """在 dow_lookback 窗口内按原著简化定义找最近的道氏低点/高点。
    返回 (valley_price, peak_price)，未找到为 None。
    道氏低点：左右各 dow_gap 根K线的最低点；道氏高点镜像。"""
    h = context['history']
    gap = context['dow_gap']
    look = context['dow_lookback']
    i = len(h)
    start = max(0, i - look - 1)
    seg = h[start:i - 1]  # 不含当前K线
    valley = None
    peak = None
    m = len(seg)
    # 从最近往前找
    j = m - gap - 1
    while j >= gap:
        lv = seg[j]['low']
        ok = True
        for k in range(j - gap, j + gap + 1):
            if k != j and seg[k]['low'] < lv:
                ok = False
                break
        if ok and valley is None:
            valley = lv
        hv = seg[j]['high']
        ok2 = True
        for k in range(j - gap, j + gap + 1):
            if k != j and seg[k]['high'] > hv:
                ok2 = False
                break
        if ok2 and peak is None:
            peak = hv
        if valley is not None and peak is not None:
            break
        j -= 1
    return valley, peak


def handle_bar(context, bar):
    history = context['history']
    history.append(bar)
    i = len(history)

    # ADX 逐根更新（warmup 期也照常累积，保证开关打开即用）
    _update_adx(context)

    if i < max(context['sma_period'], context['dow_lookback']) + context['atr_n'] + 5:
        return

    c = bar['close']
    h_ = bar['high']
    l_ = bar['low']
    tick = context['tick']

    closes = [b['close'] for b in history]
    sma_val = sma(closes, context['sma_period'])[-1]

    valley, peak = _dow_points(context)

    # ADX 状态：未成熟（None）时，启用过滤则视为不满足开仓条件
    adx_val = context['adx_val']
    if context['use_adx_filter']:
        adx_ok = (adx_val is not None) and (adx_val > context['adx_threshold'])
    else:
        adx_ok = True

    # ================================================================
    # 0. 结构状态维护（原著"有效结构"规则）
    # ================================================================
    if context['use_structure_filter']:
        # ---- 监视多头触发：未过前高却跌破触发K线低点 → 下跌结构成立 ----
        if context['trig_long_idx'] is not None:
            if h_ > context['trig_long_prev_high']:
                # 先突破前高：触发成功，取消监视
                context['trig_long_idx'] = None
            elif l_ < context['trig_long_low']:
                # 未过前高反跌破触发K线低点 → 有效下跌结构形成
                context['bear_struct'] = 1
                context['bear_last_dow_high'] = peak
                context['trig_long_idx'] = None

        # ---- 监视空头触发：未破前低却升破触发K线高点 → 上涨结构成立 ----
        if context['trig_short_idx'] is not None:
            if l_ < context['trig_short_prev_low']:
                context['trig_short_idx'] = None
            elif h_ > context['trig_short_high']:
                context['bull_struct'] = 1
                context['bull_last_dow_low'] = valley
                context['trig_short_idx'] = None

        # ---- 下跌结构延续：更新最后一个道氏高点；被向上突破则恢复做多 ----
        if context['bear_struct']:
            if peak is not None:
                if context['bear_last_dow_high'] is None or peak > context['bear_last_dow_high']:
                    # 结构运行中只跟踪，不主动上移恢复门槛（以最后形成的道氏高点为准）
                    context['bear_last_dow_high'] = peak
            if context['bear_last_dow_high'] is not None and c > context['bear_last_dow_high']:
                context['bear_struct'] = 0
                context['bear_last_dow_high'] = None

        # ---- 上涨结构延续：镜像 ----
        if context['bull_struct']:
            if valley is not None:
                if context['bull_last_dow_low'] is None or valley < context['bull_last_dow_low']:
                    context['bull_last_dow_low'] = valley
            if context['bull_last_dow_low'] is not None and c < context['bull_last_dow_low']:
                context['bull_struct'] = 0
                context['bull_last_dow_low'] = None

    # ================================================================
    # 1. 持仓止损 / 止盈（不受 ADX 影响，除非 exit_on_weak_adx=1）
    # ================================================================
    pos = context.get('position', 0)
    sl = context.get('stop_loss')
    tp = context.get('take_profit')

    if pos != 0 and sl is not None and tp is not None:
        hit = False
        if pos == 1:
            if l_ <= sl:
                context['_action'] = 'sell'
                context['_price'] = sl
                context['_reason'] = '鹰·阶梯双K(ADX) 多止损 %.1f' % sl
                hit = True
            elif h_ >= tp:
                context['_action'] = 'sell'
                context['_price'] = tp
                context['_reason'] = '鹰·阶梯双K(ADX) 多止盈 %.1f' % tp
                hit = True
            elif (context['exit_on_weak_adx'] and context['use_adx_filter']
                  and adx_val is not None and adx_val <= context['adx_threshold']):
                context['_action'] = 'sell'
                context['_price'] = c
                context['_reason'] = '鹰·阶梯双K(ADX) 多离场 ADX走弱 %.1f' % adx_val
                hit = True
            if hit:
                context['cool_dir'] = 1   # 平多后须向下回调
                context['cool_count'] = 0
        else:
            if h_ >= sl:
                context['_action'] = 'cover'
                context['_price'] = sl
                context['_reason'] = '鹰·阶梯双K(ADX) 空止损 %.1f' % sl
                hit = True
            elif l_ <= tp:
                context['_action'] = 'cover'
                context['_price'] = tp
                context['_reason'] = '鹰·阶梯双K(ADX) 空止盈 %.1f' % tp
                hit = True
            elif (context['exit_on_weak_adx'] and context['use_adx_filter']
                  and adx_val is not None and adx_val <= context['adx_threshold']):
                context['_action'] = 'cover'
                context['_price'] = c
                context['_reason'] = '鹰·阶梯双K(ADX) 空离场 ADX走弱 %.1f' % adx_val
                hit = True
            if hit:
                context['cool_dir'] = -1  # 平空后须向上反弹
                context['cool_count'] = 0

        if hit:
            context['stop_loss'] = None
            context['take_profit'] = None
            return

    # ================================================================
    # 2. 有持仓不加仓（原著规则）
    # ================================================================
    if pos != 0:
        return

    # ================================================================
    # 3. 平仓后的回调确认（反向运行 reentry_bars 根K线）
    # ================================================================
    if context['cool_dir'] == 1:
        # 平多后要求向下运行：出现更低的低点记一根
        if len(history) >= 2 and l_ < history[-2]['low']:
            context['cool_count'] += 1
        if context['cool_count'] >= context['reentry_bars']:
            context['cool_dir'] = 0
            context['cool_count'] = 0
        else:
            # 尚未完成回调确认，禁止做多（做空不受此方向限制）
            pass
    elif context['cool_dir'] == -1:
        if len(history) >= 2 and h_ > history[-2]['high']:
            context['cool_count'] += 1
        if context['cool_count'] >= context['reentry_bars']:
            context['cool_dir'] = 0
            context['cool_count'] = 0

    # ================================================================
    # 4. 趋势判定（SMA + 结构过滤 + ADX 强度过滤）
    # ================================================================
    uptrend = c > sma_val
    downtrend = c < sma_val
    if context['use_structure_filter']:
        if context['bear_struct']:
            uptrend = False
        if context['bull_struct']:
            downtrend = False
    if not adx_ok:
        uptrend = False
        downtrend = False

    # 前两根K线的高低点
    prev2_high = max(history[-2]['high'], history[-3]['high'])
    prev2_low = min(history[-2]['low'], history[-3]['low'])

    atr = _atr(context)

    # ================================================================
    # 5. 做多进场
    # ================================================================
    if uptrend and c >= prev2_high and valley is not None and c > valley:
        if context['cool_dir'] != 1:  # 平多后回调确认未完成前不再做多
            sl_price = valley - tick
            risk = c - sl_price
            ok = True
            if context['max_risk_ratio'] > 0 and atr is not None:
                if risk > context['max_risk_ratio'] * atr:
                    ok = False  # 区间过大，放弃本次进场
            if ok and risk > 0:
                context['_action'] = 'buy'
                context['_price'] = c
                tp_price = c + risk * context['rr_ratio'] + context['tp_extra_ticks'] * tick
                context['stop_loss'] = sl_price
                context['take_profit'] = tp_price
                context['_reason'] = '鹰·阶梯双K(ADX) 做多 %.1f SMA:%.0f ADX:%.0f 损:%.1f 盈:%.1f' % (
                    c, sma_val, adx_val if adx_val is not None else -1, sl_price, tp_price)
                # 登记触发监视（结构判定用）
                context['trig_long_idx'] = i - 1
                context['trig_long_low'] = l_
                context['trig_long_prev_high'] = prev2_high
                return

    # ================================================================
    # 6. 做空进场（镜像）
    # ================================================================
    if downtrend and c <= prev2_low and peak is not None and c < peak:
        if context['cool_dir'] != -1:
            sl_price = peak + tick
            risk = sl_price - c
            ok = True
            if context['max_risk_ratio'] > 0 and atr is not None:
                if risk > context['max_risk_ratio'] * atr:
                    ok = False
            if ok and risk > 0:
                context['_action'] = 'short'
                context['_price'] = c
                tp_price = c - risk * context['rr_ratio'] - context['tp_extra_ticks'] * tick
                context['stop_loss'] = sl_price
                context['take_profit'] = tp_price
                context['_reason'] = '鹰·阶梯双K(ADX) 做空 %.1f SMA:%.0f ADX:%.0f 损:%.1f 盈:%.1f' % (
                    c, sma_val, adx_val if adx_val is not None else -1, sl_price, tp_price)
                context['trig_short_idx'] = i - 1
                context['trig_short_high'] = h_
                context['trig_short_prev_low'] = prev2_low
                return
