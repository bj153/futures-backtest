"""Deep analysis of optimal StableReversion strategy"""
import requests, json

code = open("backend/strategies/stable_reversion.py", encoding="utf-8").read()

r = requests.post('http://localhost:8001/api/backtest', json={
    'contract_code':'MA609','frequency':'15m',
    'start_date':'2025-09-12','end_date':'2026-07-22',
    'strategy':code,'initial_capital':100000,'commission':0.0003,
    'margin_ratio':0.1,'multiplier':10,'source':'cache'
}, timeout=180)
d = r.json()
trades = d.get('trades', [])
pnls = [t['pnl'] for t in trades if t['pnl'] is not None]

print(f"{'='*80}")
print(f"净收益: {d['netPnl']:.0f}  |  最终权益: {d['finalEquity']:.0f}  |  收益率: {d['totalReturn']:.2f}%")
print(f"交易数: {d['tradeCount']}  |  胜率: {d['winRate']:.1f}%  |  最大回撤: {d['maxDrawdown']:.2f}%")
print(f"夏普: {d['sharpeRatio']:.2f}  |  盈亏比: {d['profitLossRatio']:.2f}  |  佣金: {d['totalCommission']:.0f}")

monthly = {}
for t in trades:
    if t.get('entryTime'):
        m = t['entryTime'][:7]
        monthly[m] = monthly.get(m, 0) + (t.get('pnl') or 0)

print(f"\n{'月度收益':<10} {'净收益':>10}  {'交易数':>6}  累计")
cum = 0
for m in sorted(monthly):
    cnt = sum(1 for t in trades if t.get('entryTime','')[:7] == m)
    cum += monthly[m]
    bar = chr(9608) * max(1, int(abs(monthly[m])/200))
    sym = '+' if monthly[m] > 0 else ' '
    print(f"  {m:<8} {sym}{monthly[m]:>9.0f}  {cnt:>6}  {cum:>8.0f} {bar}")

pos_months = sum(1 for v in monthly.values() if v > 0)
print(f"\n盈利月: {pos_months}/{len(monthly)}")

wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p < 0]
print(f"\n盈利: {len(wins)}笔  avg={sum(wins)/len(wins):.0f}  max={max(wins):.0f}  min={min(wins):.0f}")
print(f"亏损: {len(losses)}笔  avg={sum(losses)/len(losses):.0f}  max={max(losses):.0f}  min={min(losses):.0f}")

max_cl = cur = 0
for p in pnls:
    if p < 0: cur += 1; max_cl = max(max_cl, cur)
    else: cur = 0
print(f"最大连续亏损: {max_cl}笔")

reasons = {}
for t in trades:
    r = t.get('reason', '?')
    if '止损' in r: reasons['SL'] = reasons.get('SL', 0) + 1
    elif '止盈' in r: reasons['TP'] = reasons.get('TP', 0) + 1
    elif '时间' in r: reasons['Time'] = reasons.get('Time', 0) + 1
    elif '强平' in r: reasons['Force'] = reasons.get('Force', 0) + 1
    else: reasons['Other'] = reasons.get('Other', 0) + 1
print(f"\n出场原因: {reasons}")

# 多空分布
long_trades = [t for t in trades if t.get('direction') == 1]
short_trades = [t for t in trades if t.get('direction') == -1]
lp = sum(t['pnl'] for t in long_trades if t['pnl'])
sp = sum(t['pnl'] for t in short_trades if t['pnl'])
print(f"多头: {len(long_trades)}笔 PnL={lp:.0f}  |  空头: {len(short_trades)}笔 PnL={sp:.0f}")

print(f"\n{'='*80}")
print(f"vs 原版策略 (MA609 15m 100k):")
print(f"{'策略':<25} {'净收益':>8} {'交易':>4} {'胜率':>6} {'回撤':>6} {'夏普':>5} {'盈亏比':>6}")
print(f"{'-'*65}")
baseline = {
    'ladder_double_k': (6877, 247, 25.5, 5.9, 0.26, 3.72),
    'vwap_revert': (1333, 164, 25.0, 2.2, 0.12, 3.58),
    'rsi2_revert': (962, 206, 35.9, 1.9, 0.14, 2.10),
    'regime_adaptive_final': (76, 133, 18.1, 4.6, 0.01, 4.56),
}
for name, (pnl, n, w, dd_v, sr_s, pl) in baseline.items():
    print(f"  {name:<23} {pnl:>8.0f} {n:>4} {w:>5.1f}% {dd_v:>5.1f}% {sr_s:>5.2f} {pl:>6.2f}")
print(f"  {'>>> StableReversion':<23} {d['netPnl']:>8.0f} {d['tradeCount']:>4} {d['winRate']:>5.1f}% {d['maxDrawdown']:>5.1f}% {d['sharpeRatio']:>5.2f} {d['profitLossRatio']:>6.2f}")
