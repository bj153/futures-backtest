#!/usr/bin/env python3
"""
RegimeAdaptive V3 - 2026年(年初至今)各周期回测
信号在全历史数据上计算(保证指标预热), 只统计2026-01-01之后的收益
"""
import pandas as pd, numpy as np, os, json, warnings
warnings.filterwarnings('ignore')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "klines")
START_2026 = pd.Timestamp('2026-01-01')
FREQS = ['1d', '1h', '30m', '15m', '5m', '1m']
EXCLUDE = ['jm2609', 'ao2609', 'i2609']

def load_kline(code, freq):
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

def strategy_v3(df):
    sig = df.copy()
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
                if row['high'] > row['hh']: pos = 1
                elif row['low'] < row['ll']: pos = -1
            else:
                if row['close'] > row['upper']: pos = 1
                elif row['close'] < row['lower']: pos = -1
        elif pos == 1:
            if is_trend:
                if row['low'] < row['ll']: pos = 0
            else:
                if row['close'] < row['ma']: pos = 0
        elif pos == -1:
            if is_trend:
                if row['high'] > row['hh']: pos = 0
            else:
                if row['close'] > row['ma']: pos = 0
        signals.append(pos)

    sig['pos'] = signals
    sig['pos'] = sig['pos'].shift(1).fillna(0)
    return sig

def backtest_2026(sig, cost_per_trade=3.0, slippage=1.0):
    """在切片(2026至今)上评估: 收益/回撤/夏普/交易笔数"""
    bt = sig.copy()
    bt['ret'] = bt['close'].pct_change()
    bt['strategy_ret'] = bt['pos'] * bt['ret']
    bt['pos_change'] = bt['pos'].diff().abs().fillna(0)
    bt['cost'] = bt['pos_change'] * (cost_per_trade + slippage) / bt['close']
    bt['strategy_ret'] = bt['strategy_ret'] - bt['cost']

    bt = bt[bt['time'] >= START_2026].reset_index(drop=True)
    if len(bt) < 5: return None
    bt['equity'] = (1 + bt['strategy_ret']).cumprod()
    trades = bt['pos_change'].sum() / 2
    total_ret = bt['equity'].iloc[-1] - 1
    roll_max = bt['equity'].cummax()
    max_dd = ((bt['equity']-roll_max)/roll_max).min()
    dr = bt['strategy_ret'].dropna()
    days = max((bt['time'].iloc[-1] - bt['time'].iloc[0]).days, 1)
    bars_per_year = len(bt) / days * 365
    sharpe = dr.mean()/dr.std()*np.sqrt(bars_per_year) if dr.std() > 0 else 0
    return {
        'total_ret': round(total_ret*100, 1),
        'max_dd': round(max_dd*100, 1),
        'sharpe': round(sharpe, 2),
        'trades': int(trades),
        'bars': len(bt),
    }

results = {}
for freq in FREQS:
    codes = sorted([f.replace(f'_{freq}.csv','') for f in os.listdir(DATA_DIR) if f.endswith(f'_{freq}.csv')])
    tradeable = [c for c in codes if c not in EXCLUDE]
    rows = []
    for code in tradeable:
        df = load_kline(code, freq)
        if df is None or len(df) < 70: continue
        sig = strategy_v3(df)
        r = backtest_2026(sig)
        if r is None: continue
        r['code'] = code
        rows.append(r)
    results[freq] = rows
    d = pd.DataFrame(rows)
    print(f"\n===== 周期 {freq} ({len(d)} 品种) =====")
    for _, r in d.iterrows():
        print(f"{r['code']:<10} 收益:{r['total_ret']:>+8.1f}%  回撤:{r['max_dd']:>6.1f}%  "
              f"夏普:{r['sharpe']:>6.2f}  交易:{r['trades']:>4}笔")
    if len(d) > 0:
        print(f"{'[汇总]':<10} 平均:{d['total_ret'].mean():>+8.1f}%  平均回撤:{d['max_dd'].mean():>6.1f}%  "
              f"盈利:{(d['total_ret']>0).sum()}/{len(d)}  总交易:{d['trades'].sum():.0f}笔")

with open('batch_results_regime_v3_2026.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("\n已保存: batch_results_regime_v3_2026.json")
