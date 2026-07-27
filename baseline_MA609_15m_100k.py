"""全策略基准回测：MA609 15m 10万本金"""
import requests, json, time
from pathlib import Path
from datetime import datetime

API = "http://localhost:8001/api/backtest"
CONTRACT = "MA609"
FREQ = "15m"
START = "2025-09-12"
END = "2026-07-22"
CAPITAL = 100000
COMM = 0.0003
MARGIN = 0.1
MULT = 10

strategies_dir = Path(__file__).parent / "backend" / "strategies"

results = {}
for fpath in sorted(strategies_dir.glob("*.py")):
    name = fpath.stem
    code = fpath.read_text(encoding="utf-8")
    t0 = time.time()
    try:
        r = requests.post(API, json={
            "contract_code": CONTRACT, "frequency": FREQ,
            "start_date": START, "end_date": END,
            "strategy": code, "initial_capital": CAPITAL,
            "commission": COMM, "margin_ratio": MARGIN, "multiplier": MULT,
            "source": "cache"
        }, timeout=180)
        dt = time.time() - t0
        d = r.json()
        # 收集所有指标
        info = {
            "netPnl": d.get("netPnl"),
            "finalEquity": d.get("finalEquity"),
            "tradeCount": d.get("tradeCount"),
            "winRate": d.get("winRate"),
            "maxDrawdown": d.get("maxDrawdown"),
            "sharpeRatio": d.get("sharpeRatio"),
            "profitLossRatio": d.get("profitLossRatio"),
            "avgProfit": d.get("avgProfit"),
            "avgLoss": d.get("avgLoss"),
            "totalReturn": d.get("totalReturn"),
            "annualizedReturn": d.get("annualizedReturn"),
            "totalCommission": d.get("totalCommission"),
            "peakEquity": d.get("peakEquity"),
            "time": round(dt, 1),
        }
        # 收集逐笔交易
        trades_raw = d.get("trades", [])
        trades_detail = []
        for t in trades_raw:
            trades_detail.append({
                "entryTime": t.get("entryTime"),
                "exitTime": t.get("exitTime"),
                "pnl": t.get("pnl"),
                "entryPrice": t.get("entryPrice"),
                "exitPrice": t.get("exitPrice"),
                "direction": t.get("direction"),
            })
        info["trades"] = trades_detail

        # 月度分析
        monthly = {}
        for t in trades_detail:
            if t["entryTime"]:
                m = t["entryTime"][:7]  # YYYY-MM
                monthly[m] = monthly.get(m, 0) + (t["pnl"] or 0)
        info["monthly"] = monthly

        # 盈利/亏损交易分类
        wins = [t["pnl"] for t in trades_detail if t["pnl"] and t["pnl"] > 0]
        losses = [t["pnl"] for t in trades_detail if t["pnl"] and t["pnl"] < 0]

        # 连续亏损分析
        max_consec_losses = 0
        cur_losses = 0
        for t in trades_detail:
            p = t["pnl"] or 0
            if p < 0:
                cur_losses += 1
                max_consec_losses = max(max_consec_losses, cur_losses)
            else:
                cur_losses = 0
        info["maxConsecLosses"] = max_consec_losses

        # 盈利分布
        info["winCount"] = len(wins)
        info["lossCount"] = len(losses)
        info["avgWin"] = round(sum(wins) / len(wins), 2) if wins else 0
        info["avgLoss2"] = round(sum(losses) / len(losses), 2) if losses else 0

        results[name] = info
        print(f"  ✅ {name:<30} PnL={info['netPnl']:>10.2f}  trades={info['tradeCount']:>4}  "
              f"win={info['winRate']:>5.1f}%  DD={info['maxDrawdown']:>5.1f}%  "
              f"SR={info['sharpeRatio']:>5.2f}  ({dt:.1f}s)")
    except Exception as e:
        results[name] = {"error": str(e)[:200]}
        print(f"  ❌ {name}: {e}")

# ---- 排序输出 ----
print("\n" + "=" * 100)
valid = [(k, v) for k, v in results.items() if "netPnl" in v]
valid.sort(key=lambda x: x[1]["netPnl"], reverse=True)

print(f"{'策略':<30} {'净收益':>10} {'交易数':>6} {'胜率':>7} {'最大回撤':>8} {'夏普':>6} {'盈亏比':>7} {'月均':>8}")
print("-" * 100)
for name, info in valid:
    months = len(info.get("monthly", {}))
    monthly_avg = info["netPnl"] / max(months, 1)
    print(f"{name:<30} {info['netPnl']:>10.2f} {info['tradeCount']:>6} "
          f"{info['winRate']:>6.1f}% {info['maxDrawdown']:>7.1f}% "
          f"{info['sharpeRatio']:>6.2f} {info['profitLossRatio']:>7.2f} {monthly_avg:>8.0f}")

# 失败策略
failed = [(k, v) for k, v in results.items() if "error" in v]
if failed:
    print(f"\n失败 {len(failed)} 个:")
    for name, info in failed:
        print(f"  {name}: {info['error']}")

# 保存完整结果
out = Path(__file__).parent / "baseline_MA609_15m_100k.json"
with open(out, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print(f"\n结果已保存: {out}")

# 输出月度明细
print("\n" + "=" * 100)
print("月度收益明细 (top 6):")
months_all = set()
for name, info in valid[:6]:
    for m in info.get("monthly", {}):
        months_all.add(m)
months_all = sorted(months_all)
header = f"{'月份':<10}"
for name, _ in valid[:6]:
    header += f" {name[:12]:>12}"
print(header)
for m in months_all:
    row = f"{m:<10}"
    for name, info in valid[:6]:
        v = info["monthly"].get(m, 0)
        row += f" {v:>12.0f}"
    print(row)
