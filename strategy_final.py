#!/usr/bin/env python3
"""
RegimeAdaptive 策略 - 1小时线版
=================================
逻辑: ADX>25趋势模式(Donchian突破) / ADX<25震荡模式(布林带回归)
参数: DC=48 BB=24 ADX平滑=48
排除品种: jm2609 ao2609 i2609 sc2609 ec2608
2026年1-7月回测: 200笔 +39,198元 (每次1手)
"""

import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 配置
# ============================================================
DATA_DIR = "/tmp/klines/klines"
FREQ = "1h"

# 策略参数
DC_PERIOD = 48        # Donchian通道周期
BB_PERIOD = 24        # 布林带周期
BB_STD = 2.0          # 布林带标准差倍数
ADX_PERIOD = 14       # ADX计算周期
ADX_SMOOTH = 48       # ADX平滑周期(滚动均值)
ADX_THRESH = 25       # 趋势/震荡分界线

# 交易成本
COST_PCT = 0.0003     # 手续费+滑点 万分之3

# 排除品种(假突破率高/不适合趋势跟踪)
EXCLUDE = ['jm2609', 'ao2609', 'i2609', 'sc2609', 'ec2608']

# 合约乘数(每手对应的标的数量)
CONTRACT_MULT = {
    'CF609': 5, 'FG609': 20, 'MA609': 10, 'SA609': 20, 'SH609': 30,
    'SR609': 10, 'TA609': 5, 'bu2609': 10, 'c2609': 10, 'eg2609': 10,
    'fu2609': 10, 'm2609': 10, 'p2609': 10, 'pg2608': 20, 'rb2610': 10,
    'sp2609': 10, 'v2609': 5, 'y2609': 10,
}


# ============================================================
# 数据加载
# ============================================================
def load_kline(code, freq=FREQ):
    """加载K线数据"""
    path = os.path.join(DATA_DIR, f"{code}_{freq}.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    df['time'] = pd.to_datetime(df['time'])
    df = df.sort_values('time').reset_index(drop=True)
    for c in ['open', 'high', 'low', 'close', 'volume', 'open_oi', 'close_oi']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df


# ============================================================
# 技术指标
# ============================================================
def calc_atr(df, period=14):
    """ATR(平均真实波幅)"""
    hl = df['high'] - df['low']
    hc = (df['high'] - df['close'].shift(1)).abs()
    lc = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_adx(df, period=14):
    """ADX(平均趋向指数)"""
    hl = df['high'] - df['low']
    hc = (df['high'] - df['close'].shift(1)).abs()
    lc = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)

    plus_dm = df['high'].diff()
    minus_dm = -df['low'].diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    plus_dm[plus_dm <= minus_dm] = 0
    minus_dm[minus_dm <= plus_dm] = 0

    atr_val = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr_val)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr_val)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(period).mean()


# ============================================================
# 策略核心
# ============================================================
def strategy_regime_adaptive(df, dc=DC_PERIOD, bb=BB_PERIOD, bs=BB_STD,
                              adx_period=ADX_PERIOD, adx_smooth=ADX_SMOOTH,
                              adx_thresh=ADX_THRESH):
    """
    RegimeAdaptive 自适应策略

    市场状态判断:
      - regime_adx > 25 → 趋势模式: Donchian通道突破入场, 反向突破出场
      - regime_adx < 25 → 震荡模式: 布林带突破入场, 回归中轨出场

    入场信号:
      趋势模式:
        做多: high > 前DC周期最高价
        做空: low < 前DC周期最低价
      震荡模式:
        做多: close > 布林带上轨
        做空: close < 布林带下轨

    出场信号:
      趋势模式持仓:
        多头: low < 前DC周期最低价 → 平仓
        空头: high > 前DC周期最高价 → 平仓
      震荡模式持仓:
        多头: close < 布林带中轨 → 平仓
        空头: close > 布林带中轨 → 平仓

    信号在当根K线收盘时产生, 下一根K线开盘时执行。
    """
    sig = df.copy()

    # 计算指标
    sig['adx'] = calc_adx(sig, adx_period)
    sig['ma'] = sig['close'].rolling(bb).mean()
    sig['std'] = sig['close'].rolling(bb).std()
    sig['upper'] = sig['ma'] + bs * sig['std']    # 布林带上轨
    sig['lower'] = sig['ma'] - bs * sig['std']    # 布林带下轨
    sig['hh'] = sig['high'].rolling(dc).max().shift(1)  # Donchian上轨(前一日)
    sig['ll'] = sig['low'].rolling(dc).min().shift(1)   # Donchian下轨(前一日)
    sig['regime_adx'] = sig['adx'].rolling(adx_smooth).mean()  # ADX平滑值

    # 逐bar生成信号
    pos = 0
    signals = []
    for i in range(len(sig)):
        row = sig.iloc[i]

        # 指标未就绪, 保持空仓
        if pd.isna(row['regime_adx']):
            signals.append(pos)
            continue

        is_trend = row['regime_adx'] > adx_thresh

        # === 持仓管理(先检查出场) ===
        if pos == 1:  # 多头持仓
            if is_trend:
                # 趋势模式: 反向突破出场
                if row['low'] < row['ll']:
                    pos = 0
            else:
                # 震荡模式: 回归中轨出场
                if row['close'] < row['ma']:
                    pos = 0

        elif pos == -1:  # 空头持仓
            if is_trend:
                # 趋势模式: 反向突破出场
                if row['high'] > row['hh']:
                    pos = 0
            else:
                # 震荡模式: 回归中轨出场
                if row['close'] > row['ma']:
                    pos = 0

        # === 入场(空仓时) ===
        if pos == 0:
            if is_trend:
                # 趋势模式: Donchian突破
                if row['high'] > row['hh']:
                    pos = 1
                elif row['low'] < row['ll']:
                    pos = -1
            else:
                # 震荡模式: 布林带突破
                if row['close'] > row['upper']:
                    pos = 1
                elif row['close'] < row['lower']:
                    pos = -1

        signals.append(pos)

    # 信号延迟一根K线(次日开盘执行)
    sig['pos'] = signals
    sig['pos'] = sig['pos'].shift(1).fillna(0)
    return sig


# ============================================================
# 回测引擎(每次1手)
# ============================================================
def backtest_1lot(df, code, cost_pct=COST_PCT):
    """
    每次交易1手的回测
    盈亏 = (出场价 - 入场价) × 方向 × 合约乘数 - 手续费
    """
    mult = CONTRACT_MULT.get(code, 10)
    trades = []
    entry_idx = None
    entry_price = 0
    entry_dir = 0

    for i in range(1, len(df)):
        prev_pos = df.iloc[i - 1]['pos']
        curr_pos = df.iloc[i]['pos']

        if prev_pos != curr_pos:
            # 平仓
            if entry_idx is not None:
                exit_price = df.iloc[i]['open']
                pnl = (exit_price - entry_price) * entry_dir * mult
                cost = entry_price * mult * cost_pct + exit_price * mult * cost_pct
                pnl -= cost
                hold_bars = i - entry_idx
                trades.append({
                    'entry_date': df.iloc[entry_idx]['time'],
                    'exit_date': df.iloc[i]['time'],
                    'direction': entry_dir,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'hold_bars': hold_bars,
                    'hold_hours': hold_bars,  # 1h线: 1根=1小时
                })

            # 开仓
            if curr_pos != 0:
                entry_idx = i
                entry_price = df.iloc[i]['open']
                entry_dir = curr_pos
            else:
                entry_idx = None

    if not trades:
        return None

    df_trades = pd.DataFrame(trades)

    # 统计
    total_pnl = df_trades['pnl'].sum()
    n_trades = len(df_trades)
    wins = df_trades[df_trades['pnl'] > 0]
    losses = df_trades[df_trades['pnl'] <= 0]
    win_rate = len(wins) / n_trades * 100
    avg_win = wins['pnl'].mean() if len(wins) > 0 else 0
    avg_loss = abs(losses['pnl'].mean()) if len(losses) > 0 else 1
    profit_factor = avg_win / avg_loss if avg_loss > 0 else 0

    # 最大回撤
    cum = np.cumsum(df_trades['pnl'].values)
    peak = np.maximum.accumulate(cum)
    max_dd = (cum - peak).min()

    return {
        'code': code,
        'total_pnl': total_pnl,
        'n_trades': n_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'max_win': df_trades['pnl'].max(),
        'max_loss': df_trades['pnl'].min(),
        'max_dd': max_dd,
        'avg_hold_hours': df_trades['hold_hours'].mean(),
        'trades': df_trades,
    }


# ============================================================
# 主程序
# ============================================================
def main():
    codes = sorted([f.replace(f'_{FREQ}.csv', '')
                    for f in os.listdir(DATA_DIR) if f.endswith(f'_{FREQ}.csv')])
    tradeable = [c for c in codes if c not in EXCLUDE]

    print("=" * 90)
    print(f"RegimeAdaptive 策略 | {FREQ} | DC={DC_PERIOD} BB={BB_PERIOD} ADX平滑={ADX_SMOOTH}")
    print(f"排除品种: {', '.join(EXCLUDE)}")
    print("=" * 90)

    all_pnl = 0
    all_trades = 0
    results = []

    for code in tradeable:
        df = load_kline(code)
        if df is None or len(df) < 200:
            continue

        sig = strategy_regime_adaptive(df)
        r = backtest_1lot(sig, code)
        if r is None:
            continue

        results.append(r)
        all_pnl += r['total_pnl']
        all_trades += r['n_trades']

        mark = '✅' if r['total_pnl'] > 0 else '❌'
        print(f"{code:<8} 交易:{r['n_trades']:>3}笔  "
              f"胜率:{r['win_rate']:>5.1f}%  "
              f"盈亏比:{r['profit_factor']:>5.2f}  "
              f"盈亏:{r['total_pnl']:>+10,.0f}  "
              f"回撤:{r['max_dd']:>10,.0f}  "
              f"均持仓:{r['avg_hold_hours']:.0f}h  {mark}")

    winners = sum(1 for r in results if r['total_pnl'] > 0)
    print("-" * 90)
    print(f"合计: {all_trades}笔  总盈亏:{all_pnl:>+,.0f}  盈利品种:{winners}/{len(results)}")


if __name__ == '__main__':
    main()
