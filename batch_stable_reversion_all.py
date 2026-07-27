"""stable_reversion 四大板块全品种回测 - 最优参数"""
import requests, json, time

API = "http://localhost:8001/api/backtest"
strategy = open('backend/strategies/stable_reversion.py', encoding='utf-8').read()

# 四大板块主力合约（2025-09 ~ 2026-07活跃的）
contracts = [
    # 黑色（7）
    "rb610", "hc610", "i2509", "jm2509", "j2509", "sm609", "sf609",
    # 化工（7）
    "ma609", "ta609", "fg609", "sa609", "ur609", "bu2509", "l2509",
    # 农产品（10）
    "m2509", "rm609", "oi609", "p2509", "y2509", "a2509", "b2509",
    "cf609", "sr609", "c2509",
    # 有色/贵金属（5）
    "cu2509", "al2509", "zn2509", "au2508", "ag2508",
]

results = []
total = len(contracts)

for idx, ct in enumerate(contracts, 1):
    t0 = time.time()
    try:
        r = requests.post(API, json={
            "contract_code": ct, "frequency": "15m",
            "start_date": "2025-09-12", "end_date": "2026-07-22",
            "strategy": strategy, "initial_capital": 100000, "commission": 0.0003,
            "margin_ratio": 0.1, "multiplier": 10, "source": "cache"
        }, timeout=180)
        d = r.json()
        pnl = d.get("netPnl", 0)
        trs = d.get("tradeCount", 0)
        w = d.get("winRate", 0)
        dd_v = d.get("maxDrawdown", 0)
        srs = d.get("sharpeRatio", 0)
        eq = d.get("finalEquity", 0)
        results.append((pnl, trs, w, dd_v, srs, eq, ct))
        print(f"  [{idx:>2}/{total}] {ct:<8} PnL={pnl:>8.0f}  N={trs:>3}  W={w:>5.1f}%  DD={dd_v:>5.1f}%  SR={srs:.2f}  ({time.time()-t0:.1f}s)")
    except Exception as e:
        print(f"  [{idx:>2}/{total}] {ct:<8} ERROR: {e}")

results.sort(key=lambda x: x[0], reverse=True)

# Summary
print(f"\n{'='*80}")
print(f"  stable_reversion 全品种回测结果 (RSI10/90 ADX<25 SL2.0 TP3.0 15m)")
print(f"  {'合约':<8} {'净收益':>8} {'交易':>4} {'胜率':>6} {'回撤':>6} {'夏普':>5} {'终值':>8}")
print(f"  {'-'*60}")
total_pnl = 0; total_trades = 0; positive = 0
for pnl, trs, w, dd_v, srs, eq, ct in results:
    total_pnl += pnl; total_trades += trs
    if pnl > 0: positive += 1
    print(f"  {ct:<8} {pnl:>8.0f} {trs:>4} {w:>5.1f}% {dd_v:>5.1f}% {srs:>5.2f} {eq:>8.0f}")
print(f"  {'-'*60}")
print(f"  {'合计':<8} {total_pnl:>8.0f} {total_trades:>4}   {'盈利':>2}/{len(results)}")

# Save
with open("batch_results_stable_reversion_all.json", "w", encoding="utf-8") as f:
    json.dump([{"code": ct, "pnl": pnl, "trades": trs, "winRate": w, "maxDD": dd_v, "sharpe": srs, "equity": eq}
               for pnl, trs, w, dd_v, srs, eq, ct in results], f, ensure_ascii=False, indent=2)
print(f"\n  结果已保存到 batch_results_stable_reversion_all.json")
