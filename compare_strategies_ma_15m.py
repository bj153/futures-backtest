"""
对比 ma2609 @ 15m 全策略回测收益
直接调用本地后端 8001 /api/backtest
"""
import requests, json, os, sys, time
from pathlib import Path

API = "http://localhost:8001/api/backtest"
CONTRACT = "MA609"
FREQ = "15m"
INIT_CAPITAL = 10000
COMMISSION = 0.0003
MARGIN_RATIO = 0.1
MULTIPLIER = 10  # 甲醇

STRAT_DIR = Path(__file__).parent / "backend" / "strategies"

# 只跑能直接 exec 的策略（init/handle_bar 钩子）
strategies = sorted([f for f in STRAT_DIR.glob("*.py")])

print(f"合约: {CONTRACT}  周期: {FREQ}")
print(f"共 {len(strategies)} 个策略待测\n")

results = []
for sp in strategies:
    name = sp.stem
    try:
        code = sp.read_text(encoding="utf-8")
        payload = {
            "contract_code": CONTRACT,
            "frequency": FREQ,
            "start_date": "2025-09-12",
            "end_date": "2026-07-22",
            "strategy": code,
            "initial_capital": INIT_CAPITAL,
            "commission": COMMISSION,
            "margin_ratio": MARGIN_RATIO,
            "multiplier": MULTIPLIER,
            "source": "cache",
        }
        t0 = time.time()
        r = requests.post(API, json=payload, timeout=120)
        dt = time.time() - t0
        if r.status_code != 200:
            print(f"  ❌ {name}: HTTP {r.status_code} {r.text[:120]}")
            results.append((name, None, None, 0, f"HTTP {r.status_code}"))
            continue
        data = r.json()
        pnl = data.get("netPnl", data.get("pnl"))
        trades = data.get("tradeCount", len(data.get("trades", [])))
        win_rate = data.get("winRate")
        final_eq = data.get("finalEquity")
        max_dd = data.get("maxDrawdown")
        results.append((name, pnl, trades, win_rate, f"{dt:.1f}s", final_eq, max_dd))
        print(f"  ✅ {name}: PnL={pnl:.0f}  trades={trades}  win={win_rate}  final={final_eq:.0f}  ({dt:.1f}s)")
    except Exception as e:
        print(f"  ❌ {name}: {e}")
        results.append((name, None, None, 0, str(e)[:80], None, None))

# 汇总排名
print("\n" + "=" * 96)
print(f"{'策略':<28} {'净收益':>10} {'交易数':>8} {'胜率':>8} {'最终权益':>10} {'最大回撤':>10} {'耗时':>8}")
print("-" * 96)
valid = [r for r in results if r[1] is not None]
valid.sort(key=lambda x: x[1], reverse=True)
for name, pnl, trades, win, note, final_eq, max_dd in valid:
    print(f"{name:<28} {pnl:>10.0f} {trades:>8} {win:>8.1f} {final_eq:>10.0f} {max_dd:>10.0f} {note:>8}")

if len(valid) < len(results):
    print("\n失败策略:")
    for name, pnl, trades, win, note, final_eq, max_dd in results:
        if pnl is None:
            print(f"  {name}: {note}")

print("=" * 96)
if valid:
    best = valid[0]
    print(f"\n🏆 最高收益: {best[0]}  PnL={best[1]:.0f}  trades={best[2]}  win={best[3]}  final={best[5]:.0f}")

# 保存结果
out = Path(__file__).parent / "compare_strategies_MA609_15m_result.json"
with open(out, "w", encoding="utf-8") as f:
    json.dump([{"strategy": n, "pnl": p, "trades": t, "win_rate": w, "note": s, "final_equity": fe, "max_drawdown": md}
               for n, p, t, w, s, fe, md in results], f, ensure_ascii=False, indent=2)
print(f"\n结果已存: {out}")
