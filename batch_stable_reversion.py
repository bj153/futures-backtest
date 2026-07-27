"""stable_reversion 回测 - 默认参数 MA609 15m"""
import requests, json, time

API = "http://localhost:8001/api/backtest"
strategy = open('backend/strategies/stable_reversion.py', encoding='utf-8').read()

contracts = ["MA609"]
freqs = ["15m"]

results = {}
total = len(contracts) * len(freqs)
idx = 0

for ct in contracts:
    for freq in freqs:
        idx += 1
        label = f"{ct} {freq}"
        t0 = time.time()
        try:
            r = requests.post(API, json={
                "contract_code": ct, "frequency": freq,
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
            results[label] = {"pnl": pnl, "trades": trs, "winRate": w, "maxDD": dd_v, "sharpe": srs}
            print(f"  [{idx}/{total}] {label:<15} PnL={pnl:>8.0f}  N={trs:>3}  W={w:>5.1f}%  DD={dd_v:>5.1f}%  SR={srs:.2f}  ({time.time()-t0:.1f}s)")
        except Exception as e:
            print(f"  [{idx}/{total}] {label}: ERROR {e}")

# Save
with open("batch_results_stable_reversion.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\n结果已保存到 batch_results_stable_reversion.json")
print(f"{'合约':<15} {'净收益':>8} {'交易':>4} {'胜率':>6} {'回撤':>6} {'夏普':>5}")
print("-" * 55)
for label, r in sorted(results.items(), key=lambda x: x[1]["pnl"], reverse=True):
    print(f"{label:<15} {r['pnl']:>8.0f} {r['trades']:>4} {r['winRate']:>5.1f}% {r['maxDD']:>5.1f}% {r['sharpe']:>5.2f}")
