"""
ladder_double_k 在 m2609 15m 上的全面分析
"""
import requests, json, math, sys
from datetime import datetime
from collections import defaultdict

API = "http://localhost:8001/api"
CONTRACT = "m2609"
FREQ = "15m"
START = "2025-09-12"
END = "2026-07-22"
INIT_CAPITAL = 10000
COMMISSION = 0.0003
MARGIN_RATIO = 0.1
MULTIPLIER = 10

code = open("backend/strategies/ladder_double_k.py", encoding="utf-8").read()

print("=" * 70)
print(f"  ladder_double_k 全面分析: {CONTRACT} {FREQ}")
print(f"  时间范围: {START} ~ {END}")
print(f"  初始资金: {INIT_CAPITAL}  手续费: {COMMISSION*10000}%%  保证金: {MARGIN_RATIO*100}%")
print("=" * 70)

# ====== 1. 基础回测 ======
print("\n>>> 1. 基础回测结果")
r = requests.post(f"{API}/backtest", json={
    "contract_code": CONTRACT, "frequency": FREQ,
    "start_date": START, "end_date": END,
    "strategy": code, "initial_capital": INIT_CAPITAL,
    "commission": COMMISSION, "margin_ratio": MARGIN_RATIO,
    "multiplier": MULTIPLIER, "source": "cache"
}, timeout=120)

if r.status_code != 200:
    print(f"ERR: {r.status_code} {r.text[:500]}")
    sys.exit(1)

d = r.json()
trades = d.get("trades", [])
eq_curve = d.get("equityCurve", [])
klines = d.get("klines", [])

net_pnl = d.get("netPnl", 0)
final_eq = d.get("finalEquity", 0)
total_ret = d.get("totalReturn", 0)
win_rate = d.get("winRate", 0)
max_dd = d.get("maxDrawdown", 0)
sharpe = d.get("sharpeRatio", 0)
pl_ratio = d.get("profitLossRatio", 0)
trade_count = d.get("tradeCount", 0)
total_comm = d.get("totalCommission", 0)

print(f"  净收益: {net_pnl:.0f} 元  |  总收益: {total_ret:.1f}%")
print(f"  最终权益: {final_eq:.0f}  |  最大回撤: {max_dd:.1f}%")
print(f"  交易数: {trade_count}  |  胜率: {win_rate:.1f}%")
print(f"  盈亏比: {pl_ratio:.1f}  |  夏普: {sharpe:.1f}")
print(f"  手续费: {total_comm:.0f}")

if not trades:
    print("  没有交易记录，无法深入分析")
    sys.exit(0)

# ====== 2. 交易盈亏分布 ======
print(f"\n>>> 2. 交易盈亏分布 (共 {len(trades)} 笔)")

wins = [t for t in trades if t.get("pnl", 0) > 0]
losses = [t for t in trades if t.get("pnl", 0) <= 0]

win_pnls = [t["pnl"] for t in wins]
loss_pnls = [t["pnl"] for t in losses]

print(f"  盈利交易: {len(wins)} 笔 ({(len(wins)/len(trades)*100):.1f}%)")
print(f"    - 平均盈利: {sum(win_pnls)/len(win_pnls):.0f}" if win_pnls else "    - 无盈利交易")
print(f"    - 最大单笔盈利: {max(win_pnls):.0f}" if win_pnls else "")
print(f"    - 盈利总额: {sum(win_pnls):.0f}" if win_pnls else "")

print(f"  亏损交易: {len(losses)} 笔 ({(len(losses)/len(trades)*100):.1f}%)")
print(f"    - 平均亏损: {sum(loss_pnls)/len(loss_pnls):.0f}" if loss_pnls else "    - 无亏损交易")
print(f"    - 最大单笔亏损: {min(loss_pnls):.0f}" if loss_pnls else "")
print(f"    - 亏损总额: {sum(loss_pnls):.0f}" if loss_pnls else "")

# 盈亏分布区间
pnl_bins = defaultdict(int)
for t in trades:
    p = t.get("pnl", 0)
    if p >= 200: pnl_bins[">=200"] += 1
    elif p >= 100: pnl_bins["100~200"] += 1
    elif p >= 50: pnl_bins["50~100"] += 1
    elif p >= 0: pnl_bins["0~50"] += 1
    elif p >= -50: pnl_bins["-50~0"] += 1
    elif p >= -100: pnl_bins["-100~-50"] += 1
    elif p >= -200: pnl_bins["-200~-100"] += 1
    else: pnl_bins["<-200"] += 1

print("  盈亏区间分布:")
for k in [">=200", "100~200", "50~100", "0~50", "-50~0", "-100~-50", "-200~-100", "<-200"]:
    bar = "█" * pnl_bins[k]
    print(f"    {k:>10}: {pnl_bins[k]:>3} 笔  {bar}")

# ====== 3. 多空方向分析 ======
print(f"\n>>> 3. 多空方向分析")

long_trades = [t for t in trades if t.get("direction") == "long" or t.get("side") == "buy"]
short_trades = [t for t in trades if t.get("direction") == "short" or t.get("side") == "short"]

# 尝试从 reason 字段判断
long_from_reason = [t for t in trades if "做多" in str(t.get("reason", ""))]
short_from_reason = [t for t in trades if "做空" in str(t.get("reason", ""))]

if long_from_reason or short_from_reason:
    print(f"  做多: {len(long_from_reason)} 笔  PnL={sum(t['pnl'] for t in long_from_reason):.0f}")
    if long_from_reason:
        print(f"    胜率: {sum(1 for t in long_from_reason if t['pnl']>0)/len(long_from_reason)*100:.0f}%")
    print(f"  做空: {len(short_from_reason)} 笔  PnL={sum(t['pnl'] for t in short_from_reason):.0f}")
    if short_from_reason:
        print(f"    胜率: {sum(1 for t in short_from_reason if t['pnl']>0)/len(short_from_reason)*100:.0f}%")

# ====== 4. 连续亏损分析 ======
print(f"\n>>> 4. 连续亏损/盈利分析")

streaks = []
current_streak = 0
current_sign = None
for t in trades:
    sign = 1 if t["pnl"] > 0 else -1
    if sign == current_sign:
        current_streak += sign
    else:
        if current_streak != 0:
            streaks.append(current_streak)
        current_streak = sign
        current_sign = sign
if current_streak != 0:
    streaks.append(current_streak)

win_streaks = [s for s in streaks if s > 0]
loss_streaks = [abs(s) for s in streaks if s < 0]

print(f"  最大连赢: {max(win_streaks) if win_streaks else 0} 笔")
print(f"  最大连亏: {max(loss_streaks) if loss_streaks else 0} 笔")
print(f"  连亏≥5笔的次数: {sum(1 for s in loss_streaks if s >= 5)}")

# ====== 5. 月度收益分解 ======
print(f"\n>>> 5. 月度收益分解")

monthly = defaultdict(float)
monthly_trades = defaultdict(int)
for t in trades:
    ts = t.get("time", "") or t.get("entry_time", "") or t.get("close_time", "")
    try:
        if ts:
            dt = ts[:7]  # YYYY-MM
            monthly[dt] += t["pnl"]
            monthly_trades[dt] += 1
    except:
        pass

for m in sorted(monthly.keys()):
    bar_len = max(int(abs(monthly[m]) / 50), 1)
    bar = "█" * bar_len if monthly[m] > 0 else "░" * bar_len
    sign = "+" if monthly[m] >= 0 else ""
    print(f"  {m}: {sign}{monthly[m]:.0f}  ({monthly_trades[m]}笔) {bar}")

# ====== 6. 资金曲线分析 ======
print(f"\n>>> 6. 资金曲线分析")

if eq_curve:
    eq_values = [p.get("equity", p.get("value", 0)) for p in eq_curve]
    if eq_values:
        peak = eq_values[0]
        trough = eq_values[0]
        peak_dt = eq_curve[0].get("time", "")
        trough_dt = ""
        max_dd_val = 0
        max_dd_start = ""
        max_dd_end = ""
        
        for i, p in enumerate(eq_curve):
            v = p.get("equity", p.get("value", 0))
            t = p.get("time", "")
            if v > peak:
                peak = v
                peak_dt = t
                trough = v
            if v < trough:
                trough = v
                trough_dt = t
            dd = (peak - v) / peak * 100
            if dd > max_dd_val:
                max_dd_val = dd
                max_dd_start = peak_dt
                max_dd_end = t
        
        print(f"  最高权益: {peak:.0f} (发生: {peak_dt})")
        print(f"  最大回撤: {max_dd_val:.1f}%")
        print(f"    回撤起点: {max_dd_start}")
        print(f"    回撤终点: {max_dd_end}")
        print(f"  起始权益: {eq_values[0]:.0f}")
        print(f"  结束权益: {eq_values[-1]:.0f}")

# ====== 7. 出场方式分析 ======
print(f"\n>>> 7. 出场方式分析")
stop_out = [t for t in trades if "止损" in str(t.get("reason", ""))]
tp_out = [t for t in trades if "止盈" in str(t.get("reason", ""))]
print(f"  止损出场: {len(stop_out)} 笔  PnL={sum(t['pnl'] for t in stop_out):.0f}")
print(f"  止盈出场: {len(tp_out)} 笔  PnL={sum(t['pnl'] for t in tp_out):.0f}")

# ====== 8. ADX/波动率环境分析 ======
print(f"\n>>> 8. 市场环境与交易表现")

# 从 K 线数据计算每日波动率，看看高波动时表现如何
if klines:
    trade_times = set()
    for t in trades:
        ts = t.get("time", "") or t.get("entry_time", "") or t.get("close_time", "")
        if ts:
            trade_times.add(ts[:19] if len(ts) > 16 else ts)
    
    # 按日期分组K线
    daily_ranges = defaultdict(list)
    for bar in klines:
        t = bar.get("time", "")
        if t:
            day = t[:10]
            tr = abs(bar["high"] - bar["low"])
            daily_ranges[day].append(tr)
    
    daily_vol = {d: sum(v)/len(v) for d, v in daily_ranges.items()}
    if daily_vol:
        avg_vol = sum(daily_vol.values()) / len(daily_vol)
        print(f"  平均日波动: {avg_vol:.1f} 跳")
        
        # 把交易按当天波动分类
        high_vol_trades = []
        low_vol_trades = []
        for t in trades:
            ts = t.get("time", "") or t.get("entry_time", "") or t.get("close_time", "")
            day = ts[:10] if ts else ""
            vol = daily_vol.get(day, avg_vol)
            if vol > avg_vol * 1.2:
                high_vol_trades.append(t)
            elif vol < avg_vol * 0.8:
                low_vol_trades.append(t)
        
        if high_vol_trades:
            print(f"  高波动日(>1.2x均值): {len(high_vol_trades)}笔  PnL={sum(t['pnl'] for t in high_vol_trades):.0f}")
        if low_vol_trades:
            print(f"  低波动日(<0.8x均值): {len(low_vol_trades)}笔  PnL={sum(t['pnl'] for t in low_vol_trades):.0f}")

# ====== 9. SMA 参数敏感性测试 ======
print(f"\n>>> 9. SMA 周期参数敏感性测试")
print(f"  (默认 SMA={code.count('ema_fast')} ，测试不同值)")

sma_results = []
for sma_val in [12, 18, 24, 30, 40, 50, 60, 72, 90]:
    # 替换 SMA 默认值
    modified_code = code
    # 第一处：init 里的默认值
    modified_code = modified_code.replace(
        "context['sma_period'] = context.get('ema_fast', 24)",
        f"context['sma_period'] = {sma_val}",
        1
    )
    
    r2 = requests.post(f"{API}/backtest", json={
        "contract_code": CONTRACT, "frequency": FREQ,
        "start_date": START, "end_date": END,
        "strategy": modified_code, "initial_capital": INIT_CAPITAL,
        "commission": COMMISSION, "margin_ratio": MARGIN_RATIO,
        "multiplier": MULTIPLIER, "source": "cache"
    }, timeout=120)
    
    if r2.status_code == 200:
        d2 = r2.json()
        pnl = d2.get("netPnl", 0)
        trades_n = d2.get("tradeCount", 0)
        wr = d2.get("winRate", 0)
        dd_pct = d2.get("maxDrawdown", 0)
        sma_results.append((sma_val, pnl, trades_n, wr, dd_pct))
        sign = "+" if pnl >= 0 else ""
        print(f"  SMA={sma_val:>3}: PnL={sign}{pnl:>8.0f}  trades={trades_n:>4}  win={wr:>5.1f}%  DD={dd_pct:>5.1f}%")
    else:
        print(f"  SMA={sma_val:>3}: ERROR {r2.status_code}")

# ====== 10. 综合结论 ======
print(f"\n{'=' * 70}")
print(f"  综合结论")
print(f"{'=' * 70}")

reasons = []

# 判断盈亏比
if pl_ratio < 1:
    reasons.append(f"盈亏比仅 {pl_ratio:.1f}，远低于健康的 ≥1.5 标准")

# 判断胜率
if win_rate < 30:
    reasons.append(f"胜率 {win_rate:.0f}% 偏低，策略入场择时不够精准")

# 连亏
if loss_streaks:
    max_ls = max(loss_streaks)
    if max_ls >= 8:
        reasons.append(f"最大连亏 {max_ls} 笔，对心态是极大考验")

# 手续费占比
if total_comm > 0 and abs(net_pnl) > 0:
    comm_ratio = total_comm / abs(net_pnl + total_comm) * 100
    reasons.append(f"手续费 {total_comm:.0f} 元，占交易成本较高")

# 月度
neg_months = sum(1 for v in monthly.values() if v < 0)
total_months = len(monthly)
if total_months > 0 and neg_months > total_months * 0.6:
    reasons.append(f"{neg_months}/{total_months} 个月亏损，大部分月份不赚钱")

# 多空不平衡
if long_from_reason and short_from_reason:
    long_pnl = sum(t["pnl"] for t in long_from_reason)
    short_pnl = sum(t["pnl"] for t in short_from_reason)
    if abs(long_pnl) > abs(short_pnl) * 3:
        reasons.append(f"多空收益极度不对称：多做 {long_pnl:.0f} vs 空做 {short_pnl:.0f}")

# 回撤
if max_dd > 30:
    reasons.append(f"最大回撤 {max_dd:.0f}%，超出可接受范围")

for i, r in enumerate(reasons, 1):
    print(f"  {i}. {r}")

if net_pnl > 0:
    print(f"\n  ✅ 策略整体盈利 {net_pnl:.0f}，但以上问题仍需关注")
else:
    print(f"\n  ❌ 策略整体亏损 {net_pnl:.0f}，不建议在 m2609 15m 直接使用")
    
    # 推荐优化方向
    print(f"\n  可尝试的优化方向:")
    print(f"  1. 延长SMA周期过滤假突破（当前24，试试50-60）")
    print(f"  2. 增加ADX趋势过滤（仅ADX>20才交易）")
    print(f"  3. 改用1h周期（15m噪音太大）")
    print(f"  4. 增加交易时间过滤（避开开盘/收盘噪音）")
    print(f"  5. 修改止损为ATR动态止损代替固定道氏点")

# 保存 JSON
out = {
    "contract": CONTRACT, "frequency": FREQ,
    "strategy": "ladder_double_k",
    "summary": {
        "netPnl": net_pnl, "finalEquity": final_eq, "totalReturn": total_ret,
        "winRate": win_rate, "maxDrawdown": max_dd, "tradeCount": trade_count,
        "sharpeRatio": sharpe, "profitLossRatio": pl_ratio,
        "totalCommission": total_comm
    },
    "monthly": {m: float(v) for m, v in monthly.items()},
    "sma_sensitivity": [{"sma": s, "pnl": p, "trades": t, "winRate": w, "maxDrawdown": d} 
                        for s, p, t, w, d in sma_results],
    "diagnosis": reasons
}

with open("analyze_ladder_m2609_15m.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(f"\n详细数据已存: analyze_ladder_m2609_15m.json")
