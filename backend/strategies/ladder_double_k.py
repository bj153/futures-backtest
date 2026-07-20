# ========== 阶梯双K交易系统 ==========
# 《交易的真相：从1000到1.83亿》极地之鹰
#
# 核心思路：
#   1. SMA方向过滤（仅顺着大方向开仓）
#   2. 道氏点作为止损位（波谷/波峰）
#   3. 突破前两K高低点入场
#   4. 固定1:1盈亏比出场
#
# 配置参数（可在前端Settings中调整）：
#   ema_fast = SMA周期（默认24，甲醇推荐60）
#
# 使用方式：
#   init(context)        - 初始化
#   handle_bar(ctx, bar) - 每根K线执行
#
# 下单方法：
#   context['_action'] = 'buy|sell|short|cover|flip_short|flip_long'
#   context['_price']  = 成交价格
#   context['_reason'] = 备注
#
# 内置函数：sma, ema, rsi, calc_verts

def init(context):
    # SMA周期：前端Settings中的ema_fast参数控制
    context['sma_period'] = context.get('ema_fast', 24)
    context['lookback'] = 20        # 道氏点搜索范围(K线数)
    context['min_gap'] = 2          # 道氏点最小间隔
    context['history'] = []         # 已处理的K线缓存
    
    # 记录每个仓位的止损止盈位
    context['stop_loss'] = None
    context['take_profit'] = None
    context['exit_reason'] = None

def handle_bar(context, bar):
    history = context['history']
    history.append(bar)
    
    i = len(history)
    if i < context['lookback'] + 20:
        return
    
    sma_period = context['sma_period']
    lookback = context['lookback']
    min_gap = context['min_gap']
    
    # 提取收盘价序列计算SMA
    closes = [b['close'] for b in history]
    sma_vals = sma(closes, sma_period)
    current_sma = sma_vals[-1]
    
    pos = context.get('position', 0)
    c = bar['close']
    h = bar['high']
    l = bar['low']
    
    # ====== 检查持仓止损止盈 ======
    sl = context.get('stop_loss')
    tp = context.get('take_profit')
    
    if pos != 0 and sl is not None and tp is not None:
        hit = False
        if pos == 1:  # 多头
            if l <= sl:
                context['_action'] = 'sell'
                context['_price'] = sl
                context['_reason'] = f'阶梯双K止损 多 {c:.1f}→{sl:.1f}'
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
                context['_reason'] = f'阶梯双K止损 空 {c:.1f}→{sl:.1f}'
                hit = True
            elif l <= tp:
                context['_action'] = 'cover'
                context['_price'] = tp
                context['_reason'] = f'阶梯双K止盈 空 {c:.1f}→{tp:.1f}'
                hit = True
        
        if hit:
            context['stop_loss'] = None
            context['take_profit'] = None
            return
    
    # ====== 如果有持仓不再开仓 ======
    if pos != 0:
        return
    
    # ====== 检查SMA方向 ======
    uptrend = c > current_sma
    downtrend = c < current_sma
    
    # ====== 前两K高低点 ======
    prev2_high = max(history[-2]['high'], history[-3]['high'])
    prev2_low = min(history[-2]['low'], history[-3]['low'])
    
    # ====== 找道氏点 ======
    # 搜索范围：当前K线往前lookback根
    search_start = max(0, i - lookback - 1)
    seg = history[search_start:i-1]
    
    found_valley = None  # (index, price)
    found_peak = None
    
    for j in range(len(seg) - min_gap - 1, min_gap, -1):
        # 波谷：左右各min_gap根K线的低点都高于它
        left_lows = [seg[k]['low'] for k in range(j-min_gap, j)]
        right_lows = [seg[k]['low'] for k in range(j+1, j+min_gap+1)]
        if seg[j]['low'] <= min(left_lows) and seg[j]['low'] <= min(right_lows):
            if found_valley is None:
                found_valley = (search_start + j, seg[j]['low'])
        
        # 波峰：左右各min_gap根K线的高点都低于它
        left_highs = [seg[k]['high'] for k in range(j-min_gap, j)]
        right_highs = [seg[k]['high'] for k in range(j+1, j+min_gap+1)]
        if seg[j]['high'] >= max(left_highs) and seg[j]['high'] >= max(right_highs):
            if found_peak is None:
                found_peak = (search_start + j, seg[j]['high'])
        
        if found_valley is not None and found_peak is not None:
            break
    
    # ====== 做多逻辑 ======
    # 条件：SMA上方 + 突破前两K高点 + 找到道氏低点
    if uptrend and c >= prev2_high and found_valley is not None:
        valley_price = found_valley[1]
        if c > valley_price:
            context['_action'] = 'buy'
            context['_price'] = c
            sl_price = valley_price - 0.5
            tp_price = c + (c - sl_price)
            context['stop_loss'] = sl_price
            context['take_profit'] = tp_price
            context['_reason'] = f'阶梯双K做多 {c:.1f} SMA:{current_sma:.0f} 损:{sl_price:.1f} 盈:{tp_price:.1f}'
            return
    
    # ====== 做空逻辑 ======
    # 条件：SMA下方 + 跌破前两K低点 + 找到道氏高点
    if downtrend and c <= prev2_low and found_peak is not None:
        peak_price = found_peak[1]
        if c < peak_price:
            context['_action'] = 'short'
            context['_price'] = c
            sl_price = peak_price + 0.5
            tp_price = c - (sl_price - c)
            context['stop_loss'] = sl_price
            context['take_profit'] = tp_price
            context['_reason'] = f'阶梯双K做空 {c:.1f} SMA:{current_sma:.0f} 损:{sl_price:.1f} 盈:{tp_price:.1f}'
            return