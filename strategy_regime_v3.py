#!/usr/bin/env python3
"""
RegimeAdaptive V3 - 趋势/震荡自适应策略
ADX>25: Donchian20突破  |  ADX<25: 布林带20,2回归
排除品种: jm2609(焦煤) ao2609(氧化铝) i2609(铁矿)
"""
import pandas as pd, numpy as np, os, warnings
warnings.filterwarnings('ignore')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "klines")

def load_kline(code, freq='1d'):
    path = os.path.join(DATA_DIR, f"{code}_{freq}.csv")
    if not os.path.exists(path): return None
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    df['time'] = pd.to_datetime(df['time'])
    df = df.sort_values('time').reset_index(drop=True)
    for c in ['open','high','low','close','volume','open_oi','close_oi']:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce')
    return df

def atr(df, period=14):
    hl=df['high']-df['low']
    hc=(df['high']-df['close'].shift(1)).abs()
    lc=(df['low']-df['close'].shift(1)).abs()
    return pd.concat([hl,hc,lc],axis=1).max(axis=1).rolling(period).mean()

def adx(df, period=14):
    hl=df['high']-df['low']
    hc=(df['high']-df['close'].shift(1)).abs()
    lc=(df['low']-df['close'].shift(1)).abs()
    tr=pd.concat([hl,hc,lc],axis=1).max(axis=1)
    plus_dm=df['high'].diff()
    minus_dm=-df['low'].diff()
    plus_dm[plus_dm<0]=0
    minus_dm[minus_dm<0]=0
    plus_dm[(plus_dm<=minus_dm)]=0
    minus_dm[(minus_dm<=plus_dm)]=0
    atr_val=tr.rolling(period).mean()
    plus_di=100*(plus_dm.rolling(period).mean()/atr_val)
    minus_di=100*(minus_dm.rolling(period).mean()/atr_val)
    dx=100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,np.nan)
    return dx.rolling(period).mean()

def backtest(df, cost_per_trade=3.0, slippage=1.0):
    bt = df.copy()
    bt['ret'] = bt['close'].pct_change()
    bt['strategy_ret'] = bt['pos'] * bt['ret']
    bt['pos_change'] = bt['pos'].diff().abs()
    bt['cost'] = bt['pos_change'] * (cost_per_trade + slippage) / bt['close']
    bt['strategy_ret'] = bt['strategy_ret'] - bt['cost']
    bt['equity'] = (1 + bt['strategy_ret']).cumprod()
    bt['buy_hold'] = (1 + bt['ret']).cumprod()
    trades = max(bt['pos_change'].sum() / 2, 1)
    total_ret = bt['equity'].iloc[-1] - 1
    bh_ret = bt['buy_hold'].iloc[-1] - 1
    n = len(bt)
    ann_ret = (1+total_ret)**(252/n)-1 if n > 0 else 0
    roll_max = bt['equity'].cummax()
    max_dd = ((bt['equity']-roll_max)/roll_max).min()
    dr = bt['strategy_ret'].dropna()
    sharpe = dr.mean()/dr.std()*np.sqrt(252) if dr.std() > 0 else 0
    tr_rets = bt.loc[bt['pos_change']>0, 'strategy_ret']
    win_rate = (tr_rets>0).sum()/len(tr_rets)*100 if len(tr_rets) > 0 else 0
    w = tr_rets[tr_rets>0]; l = tr_rets[tr_rets<0]
    avg_win = w.mean() if len(w) > 0 else 0
    avg_loss = abs(l.mean()) if len(l) > 0 else 1
    pf = avg_win/avg_loss if avg_loss > 0 else 0
    cal = ann_ret/abs(max_dd) if max_dd != 0 else 0
    return {
        'total_ret': total_ret*100, 'bh_ret': bh_ret*100, 'ann_ret': ann_ret*100,
        'max_dd': max_dd*100, 'sharpe': sharpe, 'trades': int(trades),
        'win_rate': win_rate, 'profit_factor': pf, 'calmar': cal,
    }

def strategy_v3(df):
    """RegimeAdaptive: ADX>25趋势模式(Donchian20) / ADX<25震荡模式(布林带20,2)"""
    sig = df.copy()
    sig['atr_pct'] = atr(sig, 14) / sig['close']
    sig['adx'] = adx(sig, 14)
    sig['ma'] = sig['close'].rolling(20).mean()
    sig['std'] = sig['close'].rolling(20).std()
    sig['upper'] = sig['ma'] + 2 * sig['std']
    sig['lower'] = sig['ma'] - 2 * sig['std']
    sig['hh'] = sig['high'].rolling(20).max().shift(1)
    sig['ll'] = sig['low'].rolling(20).min().shift(1)
    sig['regime_adx'] = sig['adx'].rolling(50).mean()

    pos = 0
    signals = []
    for i in range(len(sig)):
        row = sig.iloc[i]
        if pd.isna(row['regime_adx']):
            signals.append(pos)
            continue
        is_trend = row['regime_adx'] > 25

        if pos == 0:
            if is_trend:
                # 趋势模式: Donchian20突破
                if row['high'] > row['hh']:
                    pos = 1
                elif row['low'] < row['ll']:
                    pos = -1
            else:
                # 震荡模式: 布林带回归
                if row['close'] > row['upper']:
                    pos = 1
                elif row['close'] < row['lower']:
                    pos = -1
        elif pos == 1:
            if is_trend:
                if row['low'] < row['ll']:
                    pos = 0
            else:
                if row['close'] < row['ma']:
                    pos = 0
        elif pos == -1:
            if is_trend:
                if row['high'] > row['hh']:
                    pos = 0
            else:
                if row['close'] > row['ma']:
                    pos = 0
        signals.append(pos)

    sig['pos'] = signals
    sig['pos'] = sig['pos'].shift(1).fillna(0)  # 次日开盘执行
    return sig

# ============ 运行 ============
EXCLUDE = ['jm2609', 'ao2609', 'i2609']  # 毒品种: 假突破率高

codes = sorted([f.replace('_1d.csv','') for f in os.listdir(DATA_DIR) if f.endswith('_1d.csv')])
tradeable = [c for c in codes if c not in EXCLUDE]

for code in tradeable:
    df = load_kline(code, '1d')
    if df is None or len(df) < 50:
        continue
    sig = strategy_v3(df)
    r = backtest(sig)
    print(f"{code:<10} 收益:{r['total_ret']:>+8.1f}%  回撤:{r['max_dd']:>6.1f}%  "
          f"夏普:{r['sharpe']:>5.2f}  交易:{r['trades']:>3}笔  "
          f"胜率:{r['win_rate']:>5.1f}%  盈亏比:{r['profit_factor']:>5.2f}")
