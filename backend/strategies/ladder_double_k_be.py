# ========== 阶梯双K交易系统 · 保本止损版 ==========
# 基于 ladder_double_k 的改进：
#   浮盈达到 +0.5R 后，止损上移到入场价（保本）
#   预期效果：大量"差点止盈又被打回"的 -1R 变为 0，胜率上升、回撤下降
#
# 其余逻辑与原版一致：SMA方向过滤 + 道氏点止损 + 突破前两K入场 + 固定1:1

def init(context):
    context['sma_period'] = context.get('ema_fast', 24)
    context['lookback'] = 20
    context['min_gap'] = 2
    context['history'] = []

    context['stop_loss'] = None
    context['take_profit'] = None
    context['exit_reason'] = None
    # 保本机制状态
    context['entry_price'] = None      # 入场价
    context['risk_r'] = None           # 1R 距离
    context['be_trigger'] = 0.5        # 浮盈达到 0.5R 触发保本
    context['be_done'] = False         # 保本是否已执行

def handle_bar(context, bar):
    history = context['history']
    history.append(bar)

    i = len(history)
    if i < context['lookback'] + 20:
        return

    sma_period = context['sma_period']
    lookback = context['lookback']
    min_gap = context['min_gap']

    closes = [b['close'] for b in history]
    sma_vals = sma(closes, sma_period)
    current_sma = sma_vals[-1]

    pos = context.get('position', 0)
    c = bar['close']
    h = bar['high']
    l = bar['low']

    sl = context.get('stop_loss')
    tp = context.get('take_profit')

    if pos != 0 and sl is not None and tp is not None:
        entry = context.get('entry_price')
        r = context.get('risk_r')

        # ====== 保本止损：浮盈 >= 0.5R 且未保过本 → 止损移到入场价 ======
        if not context.get('be_done') and entry is not None and r:
            if pos == 1 and h >= entry + context['be_trigger'] * r:
                sl = entry
                context['stop_loss'] = entry
                context['be_done'] = True
            elif pos == -1 and l <= entry - context['be_trigger'] * r:
                sl = entry
                context['stop_loss'] = entry
                context['be_done'] = True

        hit = False
        if pos == 1:  # 多头
            if l <= sl:
                context['_action'] = 'sell'
                context['_price'] = sl
                reason = '保本出场' if context.get('be_done') and sl == entry else '阶梯双K止损'
                context['_reason'] = f'{reason} 多 {c:.1f}→{sl:.1f}'
                hit = True
            elif h >= tp:
                context['_action'] = 'sell'
                context['_price'] = tp
                context['_reason'] = f'阶梯双K止盈 多 {c:.1f}→{tp:.1f}'
                hit = True
        else:  # 空头
            if h >= sl:
                context['_action'] = 'cover'
                context['_price'] = sl
                reason = '保本出场' if context.get('be_done') and sl == entry else '阶梯双K止损'
                context['_reason'] = f'{reason} 空 {c:.1f}→{sl:.1f}'
                hit = True
            elif l <= tp:
                context['_action'] = 'cover'
                context['_price'] = tp
                context['_reason'] = f'阶梯双K止盈 空 {c:.1f}→{tp:.1f}'
                hit = True

        if hit:
            context['stop_loss'] = None
            context['take_profit'] = None
            context['entry_price'] = None
            context['risk_r'] = None
            context['be_done'] = False
            return

    if pos != 0:
        return

    uptrend = c > current_sma
    downtrend = c < current_sma

    prev2_high = max(history[-2]['high'], history[-3]['high'])
    prev2_low = min(history[-2]['low'], history[-3]['low'])

    search_start = max(0, i - lookback - 1)
    seg = history[search_start:i-1]

    found_valley = None
    found_peak = None

    for j in range(len(seg) - min_gap - 1, min_gap, -1):
        left_lows = [seg[k]['low'] for k in range(j-min_gap, j)]
        right_lows = [seg[k]['low'] for k in range(j+1, j+min_gap+1)]
        if seg[j]['low'] <= min(left_lows) and seg[j]['low'] <= min(right_lows):
            if found_valley is None:
                found_valley = (search_start + j, seg[j]['low'])

        left_highs = [seg[k]['high'] for k in range(j-min_gap, j)]
        right_highs = [seg[k]['high'] for k in range(j+1, j+min_gap+1)]
        if seg[j]['high'] >= max(left_highs) and seg[j]['high'] >= max(right_highs):
            if found_peak is None:
                found_peak = (search_start + j, seg[j]['high'])

        if found_valley is not None and found_peak is not None:
            break

    # ====== 做多 ======
    if uptrend and c >= prev2_high and found_valley is not None:
        valley_price = found_valley[1]
        if c > valley_price:
            context['_action'] = 'buy'
            context['_price'] = c
            sl_price = valley_price - 0.5
            tp_price = c + (c - sl_price)
            context['stop_loss'] = sl_price
            context['take_profit'] = tp_price
            context['entry_price'] = c
            context['risk_r'] = c - sl_price
            context['be_done'] = False
            context['_reason'] = f'阶梯双K做多(BE) {c:.1f} SMA:{current_sma:.0f} 损:{sl_price:.1f} 盈:{tp_price:.1f}'
            return

    # ====== 做空 ======
    if downtrend and c <= prev2_low and found_peak is not None:
        peak_price = found_peak[1]
        if c < peak_price:
            context['_action'] = 'short'
            context['_price'] = c
            sl_price = peak_price + 0.5
            tp_price = c - (sl_price - c)
            context['stop_loss'] = sl_price
            context['take_profit'] = tp_price
            context['entry_price'] = c
            context['risk_r'] = sl_price - c
            context['be_done'] = False
            context['_reason'] = f'阶梯双K做空(BE) {c:.1f} SMA:{current_sma:.0f} 损:{sl_price:.1f} 盈:{tp_price:.1f}'
            return
