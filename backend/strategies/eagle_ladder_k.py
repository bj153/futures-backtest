# ========== 极地之鹰 · 阶梯双K交易法则（原著忠实版） ==========
# 出处：《交易的真相：从1000到1.83亿》（极地之鹰）第9章「阶梯双K交易法则」
#
# 规则要点（OCR 整理版）：
#
# 【趋势判定】两点同时满足才算有趋势
#   上涨趋势：① 价格在 SMA24 之上；② 未形成"有效的下跌结构"。
#   下跌趋势：① 价格在 SMA24 之下；② 未形成"有效的上涨结构"。
#   结构定义（以做多为例）：上升趋势中，价格触发进场条件后若未能突破前高、
#   反而向下跌破触发K线的低点，则"下跌结构"成立，此后不再做多；直到该
#   下跌结构运行期间形成的最后一个道氏高点被向上突破，才恢复做多。
#   做空镜像对称。
#
# 【进场】
#   做多：上涨趋势中，收盘价向上突破前两根K线最高价 → buy
#   做空：下跌趋势中，收盘价向下跌破前两根K线最低价 → short
#   若止损距离过大（风险过远），放弃本次进场：以 max_risk_ratio × 近N根
#   ATR 为上限（书中为人工判断，此处参数化，默认放宽）。
#
# 【止损 / 止盈】
#   多单止损 = 最近道氏低点 - 1 tick；空单止损 = 最近道氏高点 + 1 tick
#   止盈 = 1:1 盈亏比（可外加 tp_extra_ticks 覆盖成本）
#
# 【再进场限制】
#   有持仓时不再加仓（引擎层面 position!=0 时 buy/short 亦不生效，双保险）。
#   平仓后须经"回调确认"：平仓后价格反向运行（对多单而言是向下）至少
#   reentry_bars 根K线，才允许同方向再次进场。
#
# 【道氏点定义】（原著简化版）
#   两个同向极点之间的反向极值点，中间K线数 >= dow_gap（原著为1，传统为3）
#
# 接口（与 BacktestEngine 完全兼容）：
#   init(context)        初始化，所有参数集中于此
#   handle_bar(ctx, bar) 每根K线调用
#   下单：context['_action'] = 'buy|sell|short|cover'
#         context['_price'] / context['_reason']
#   内置函数：sma, ema, rsi, calc_verts（引擎注入）
#   注意：引擎 __builtins__ 受限，仅可用 len/range/min/max/abs/sum/int/
#         float/list/dict/all/any/sorted/round/str/enumerate/zip/Exception
# =========================================================================

def init(context):
    # ---- 趋势判定 ----
    context['sma_period'] = context.get('ema_fast', 24)   # SMA 周期（原著 24）
    context['use_structure_filter'] = context.get('use_structure_filter', 1)  # 1=启用下跌/上涨结构过滤

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

    if i < max(context['sma_period'], context['dow_lookback']) + context['atr_n'] + 5:
        return

    c = bar['close']
    h_ = bar['high']
    l_ = bar['low']
    tick = context['tick']

    closes = [b['close'] for b in history]
    sma_val = sma(closes, context['sma_period'])[-1]

    valley, peak = _dow_points(context)

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
    # 1. 持仓止损 / 止盈
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
                context['_reason'] = '鹰·阶梯双K 多止损 %.1f' % sl
                hit = True
            elif h_ >= tp:
                context['_action'] = 'sell'
                context['_price'] = tp
                context['_reason'] = '鹰·阶梯双K 多止盈 %.1f' % tp
                hit = True
            if hit:
                context['cool_dir'] = 1   # 平多后须向下回调
                context['cool_count'] = 0
        else:
            if h_ >= sl:
                context['_action'] = 'cover'
                context['_price'] = sl
                context['_reason'] = '鹰·阶梯双K 空止损 %.1f' % sl
                hit = True
            elif l_ <= tp:
                context['_action'] = 'cover'
                context['_price'] = tp
                context['_reason'] = '鹰·阶梯双K 空止盈 %.1f' % tp
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
    # 4. 趋势判定（SMA + 结构过滤）
    # ================================================================
    uptrend = c > sma_val
    downtrend = c < sma_val
    if context['use_structure_filter']:
        if context['bear_struct']:
            uptrend = False
        if context['bull_struct']:
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
                context['_reason'] = '鹰·阶梯双K 做多 %.1f SMA:%.0f 损:%.1f 盈:%.1f' % (c, sma_val, sl_price, tp_price)
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
                context['_reason'] = '鹰·阶梯双K 做空 %.1f SMA:%.0f 损:%.1f 盈:%.1f' % (c, sma_val, sl_price, tp_price)
                context['trig_short_idx'] = i - 1
                context['trig_short_high'] = h_
                context['trig_short_prev_low'] = prev2_low
                return
