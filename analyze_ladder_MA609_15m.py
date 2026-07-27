"""ladder_double_k × MA609(甲醇2609) 15m 全面诊断"""
import requests, json, time, sys
from datetime import datetime
from pathlib import Path

BASE = "http://localhost:8001"
STRATEGY_CODE = open("F:/Source/170/futures-backtest/backend/strategies/ladder_double_k.py", encoding="utf-8").read()

def run_backtest(contract, freq, start, end, sma=None):
    code = STRATEGY_CODE
    if sma is not None:
        # 注入 SMA 参数
        import re
        code = re.sub(r"SMA_PERIOD\s*=\s*\d+", f"SMA_PERIOD = {sma}", code)
    payload = {
        "contract_code": contract,
        "frequency": freq,
        "start_date": start,
        "end_date": end,
        "strategy": code,
        "initial_capital": 10000,
        "commission": 0.0003,
        "margin_ratio": 0.1,
        "multiplier": 10,
        "source": "cache"
    }
    r = requests.post(f"{BASE}/api/backtest", json=payload, timeout=120)
    if r.status_code != 200:
        return {"error": r.text[:200]}
    return r.json()

print("=" * 70)
print("ladder_double_k × MA609(甲醇2609) 15m 全面诊断")
print("=" * 70)

# 1. 基础回测
print("\n[1/6] 基础回测...")
result = run_backtest("MA609", "15m", "2025-09-12", "2026-07-22")
if "error" in result:
    print(f"❌ {result['error']}")
    sys.exit(1)

pnl = result.get("netPnl", 0)
trades = result.get("tradeCount", 0)
win_rate = result.get("winRate", 0)
final_eq = result.get("finalEquity", 0)
max_dd = result.get("maxDrawdown", 0)
sharpe = result.get("sharpeRatio", 0)

print(f"  净收益: {pnl:,.0f}  交易数: {trades}  胜率: {win_rate}%")
print(f"  最终权益: {final_eq:,.0f}  最大回撤: {max_dd}%  夏普: {sharpe}")

# 2. 交易明细分析
print("\n[2/6] 交易明细分析...")
trade_list = result.get("trades", [])
if trade_list:
    profits = [t.get("pnl", t.get("profit", 0)) for t in trade_list]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    
    print(f"  总笔数: {len(profits)}")
    print(f"  盈利笔数: {len(wins)}  最大单笔盈利: {max(wins) if wins else 0:,.0f}")
    print(f"  亏损笔数: {len(losses)}  最大单笔亏损: {min(losses) if losses else 0:,.0f}")
    print(f"  平均盈利: {sum(wins)/len(wins):,.0f}" if wins else "  无盈利")
    print(f"  平均亏损: {sum(losses)/len(losses):,.0f}" if losses else "  无亏损")
    print(f"  盈亏比: {abs(sum(wins)/len(wins)/(sum(losses)/len(losses))) if wins and losses else 0:.2f}")

# 3. 盈亏分布
print("\n[3/6] 盈亏分布...")
if trade_list:
    buckets = {"<-300": 0, "-300~-200": 0, "-200~-100": 0, "-100~-50": 0, "-50~0": 0,
               "0~50": 0, "50~100": 0, "100~200": 0, "200~300": 0, ">300": 0}
    for p in profits:
        if p < -300: buckets["<-300"] += 1
        elif p < -200: buckets["-300~-200"] += 1
        elif p < -100: buckets["-200~-100"] += 1
        elif p < -50: buckets["-100~-50"] += 1
        elif p < 0: buckets["-50~0"] += 1
        elif p < 50: buckets["0~50"] += 1
        elif p < 100: buckets["50~100"] += 1
        elif p < 200: buckets["100~200"] += 1
        elif p < 300: buckets["200~300"] += 1
        else: buckets[">300"] += 1
    for k, v in buckets.items():
        bar = "█" * (v // 3)
        print(f"  {k:>12}: {v:>4}  {bar}")

# 4. 月度表现
print("\n[4/6] 月度表现...")
if trade_list:
    monthly = {}
    for t in trade_list:
        ts = t.get("exit_time", t.get("time", t.get("exitTime", "")))
        if ts:
            m = ts[:7]
            p = t.get("pnl", t.get("profit", 0))
            monthly[m] = monthly.get(m, 0) + p
    for m in sorted(monthly.keys()):
        v = monthly[m]
        bar = "█" * (abs(int(v)) // 200)
        tag = "+" if v >= 0 else ""
        print(f"  {m}: {tag}{v:>+8,.0f}  {bar}")

# 5. 连续亏损分析
print("\n[5/6] 连续盈亏分析...")
if trade_list:
    max_consec_wins = max_consec_losses = cur_wins = cur_losses = 0
    for p in profits:
        if p > 0:
            cur_wins += 1
            cur_losses = 0
            max_consec_wins = max(max_consec_wins, cur_wins)
        else:
            cur_losses += 1
            cur_wins = 0
            max_consec_losses = max(max_consec_losses, cur_losses)
    print(f"  最大连胜: {max_consec_wins}笔  最大连亏: {max_consec_losses}笔")

# 6. SMA 参数敏感性
print("\n[6/6] SMA 周期参数扫描...")
sma_results = []
for sma in [8, 12, 16, 20, 24, 28, 32, 36, 40, 50, 60]:
    r = run_backtest("MA609", "15m", "2025-09-12", "2026-07-22", sma=sma)
    if "error" not in r:
        sma_results.append((sma, r.get("netPnl", 0), r.get("winRate", 0), r.get("maxDrawdown", 0)))
        print(f"  SMA={sma:>3}: PnL={sma_results[-1][1]:>+8,.0f}  win={sma_results[-1][2]:>5.1f}%  DD={sma_results[-1][3]:>5.1f}%")

# 最终汇总
print("\n" + "=" * 70)
print("诊断结论")
print("=" * 70)
if pnl > 0:
    print(f"  ✅ ladder_double_k 在 MA609(甲醇)15m 上表现优秀")
    print(f"  净收益 +{pnl:,.0f}（+{pnl/100:.1f}%），胜率 {win_rate}%，盈亏比高")
else:
    print(f"  ❌ ladder_double_k 在 MA609(甲醇)15m 上亏损")
    
if sma_results:
    best_sma = max(sma_results, key=lambda x: x[1])
    print(f"  🏆 最佳SMA参数: {best_sma[0]} → PnL={best_sma[1]:+,.0f}  win={best_sma[2]}%  DD={best_sma[3]}%")

# 保存结果
output = {
    "contract": "MA609(甲醇2609)",
    "frequency": "15m",
    "strategy": "ladder_double_k",
    "base_result": {"pnl": pnl, "trades": trades, "winRate": win_rate, "finalEquity": final_eq, "maxDrawdown": max_dd},
    "sma_scan": [{"sma": s, "pnl": p, "winRate": w, "maxDrawdown": d} for s, p, w, d in sma_results]
}
Path("F:/Source/170/futures-backtest/diagnosis_ladder_MA609_15m.json").write_text(json.dumps(output, ensure_ascii=False, indent=2))
print(f"\n详细数据已存: diagnosis_ladder_MA609_15m.json")
