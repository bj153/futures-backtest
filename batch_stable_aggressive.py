"""扫 StableReversion 激进参数 — 提高交易频率、提升收益"""
import requests, json, time, sys

API = 'http://localhost:8001/api/backtest'
strategy_tpl = open('backend/strategies/stable_reversion.py', encoding='utf-8').read()

# 测试合约
contracts = ['MA609', 'jm2609', 'eg2609', 'fu2609']

combos = [
    # (long_rsi, short_rsi, adx_max, sl_atr, tp_atr, label)
    # 原版基准
    (10, 90, 25, 2.0, 3.0, "基准 R10/A25"),
    # 去掉ADX过滤
    (10, 90, 99, 2.0, 3.0, "去ADX R10"),
    # 放宽RSI + 去ADX
    (15, 85, 99, 2.0, 3.0, "R15 无ADX"),
    (20, 80, 99, 2.0, 3.0, "R20 无ADX"),
    (25, 75, 99, 2.0, 3.0, "R25 无ADX"),
    # 放宽止损
    (15, 85, 99, 2.5, 3.5, "R15 SL2.5"),
    (20, 80, 99, 2.5, 3.5, "R20 SL2.5"),
    # 激进：放开止损止盈比
    (20, 80, 99, 1.5, 4.0, "R20 SL1.5/TP4"),
    (25, 75, 99, 1.5, 4.0, "R25 SL1.5/TP4"),
]

def patch_params(src, **kw):
    for k, v in kw.items():
        src = src.replace(
            f"context.get('{k}', ",
            f"context.get('{k}', {v})  # patched"
        )
    return src

all_results = []
for combo in combos:
    long_rsi, short_rsi, adx_max, sl_atr, tp_atr, label = combo
    strategy = strategy_tpl
    strategy = patch_params(strategy, 
        long_rsi=long_rsi, short_rsi=short_rsi,
        adx_max=adx_max, sl_atr=sl_atr, tp_atr=tp_atr)
    
    total_pnl = 0
    total_trs = 0
    line = f"{label:<20}"
    for ct in contracts:
        try:
            r = requests.post(API, json={
                'contract_code': ct, 'frequency': '15m',
                'start_date': '2025-09-12', 'end_date': '2026-07-22',
                'strategy': strategy, 'initial_capital': 100000, 'commission': 0.0003,
                'margin_ratio': 0.1, 'multiplier': 10, 'source': 'cache'
            }, timeout=180)
            d = r.json()
            pnl = d.get('netPnl', 0)
            trs = d.get('tradeCount', 0)
            total_pnl += pnl
            total_trs += trs
            dd = d.get('maxDrawdown', 0)
            sr = d.get('sharpeRatio', 0)
            line += f"  {ct}:{pnl:>6.0f}/{trs:>2}笔"
        except Exception as e:
            line += f"  {ct}:ERR"
    line += f"  => 合计:{total_pnl:>7.0f}/{total_trs:>3}笔"
    print(line)
    all_results.append((total_pnl, total_trs, label))

all_results.sort(key=lambda x: x[0], reverse=True)
print()
print("=== 排名 ===")
for pnl, trs, label in all_results:
    print(f"  {label:<20} {pnl:>8.0f} / {trs:>3}笔")
