"""Grid search: stable_reversion + ladder_double_k on MA2609 all timeframes"""
import requests, json, time, itertools
from pathlib import Path
from datetime import datetime

API = "http://localhost:8001/api/backtest"
CONTRACT = "MA609"
START = "2025-09-12"
END = "2026-07-22"
CAPITAL = 100000
COMM = 0.0003
MARGIN = 0.1
MULT = 10
TIMEFRAMES = ["5m", "15m", "30m", "1h"]

strategies_dir = Path(__file__).parent / "backend" / "strategies"

TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = Path(__file__).parent / f"grid_results_{TAG}.json"
CSV = Path(__file__).parent / f"grid_results_{TAG}.csv"

# ========================================
# stable_reversion grids
# ========================================
# Fixed: rsi_len=2, short_rsi=90, vwap_dev=0, adx_period=14, atr_len=14
SR_ENTRY_GRID = {
    "long_rsi": [5, 8, 10, 12, 15],
    "ema_len": [100, 200, 300],
    "adx_max": [20, 25, 30],
}
SR_FIXED_EXIT = {"sl_atr": 2.0, "tp_atr": 3.0, "time_stop": 12}

SR_EXIT_GRID = {
    "sl_atr": [1.5, 2.0, 2.5],
    "tp_atr": [2.0, 3.0, 4.0],
    "time_stop": [8, 12, 20],
}

# ========================================
# ladder_double_k grid
# ========================================
LDK_GRID = {
    "ema_fast": [20, 30, 40, 50, 60, 80],
    "lookback": [15, 20, 30],
    "min_gap": [1, 2, 3],
}

# ---- helpers ----
def make_combos(grid):
    keys = list(grid.keys())
    for vals in itertools.product(*grid.values()):
        yield dict(zip(keys, vals))

def read_strategy(name):
    return (strategies_dir / name).read_text(encoding="utf-8")

def patch_ladder_double_k(code, params):
    """Inject lookback/min_gap as context params, these are currently hardcoded"""
    code = code.replace(
        "context['lookback'] = 20",
        f"context['lookback'] = context.get('lookback', {params.get('lookback', 20)})"
    )
    code = code.replace(
        "context['min_gap'] = 2",
        f"context['min_gap'] = context.get('min_gap', {params.get('min_gap', 2)})"
    )
    return code

def run_one(strategy_code, frequency, params):
    payload = {
        "contract_code": CONTRACT, "frequency": frequency,
        "start_date": START, "end_date": END,
        "strategy": strategy_code, "initial_capital": CAPITAL,
        "commission": COMM, "margin_ratio": MARGIN, "multiplier": MULT,
        "source": "cache",
        "strategy_params": params,
    }
    r = requests.post(API, json=payload, timeout=180)
    return r.json()

def extract_metrics(d, tag_prefix, params):
    return {
        "strategy": tag_prefix,
        "frequency": params.get("_freq", ""),
        **{k: v for k, v in params.items() if not k.startswith("_")},
        "netPnl": d.get("netPnl", 0),
        "tradeCount": d.get("tradeCount", 0),
        "winRate": d.get("winRate", 0),
        "maxDrawdown": d.get("maxDrawdown", 0),
        "sharpeRatio": d.get("sharpeRatio", 0),
        "profitLossRatio": d.get("profitLossRatio", 0),
    }


# ========================================
# MAIN
# ========================================
all_results = []
total_calls = 0
t_start = time.time()

sr_code = read_strategy("stable_reversion.py")
ldk_code_orig = read_strategy("ladder_double_k.py")

for freq in TIMEFRAMES:
    print(f"\n{'='*80}")
    print(f"  周期: {freq}")
    print(f"{'='*80}")

    # ---- stable_reversion Stage 1: entry params ----
    print(f"\n  [stable_reversion] Stage 1: 入场优化 ({len(list(make_combos(SR_ENTRY_GRID)))} combos)")
    sr_entry_results = []
    for combo in make_combos(SR_ENTRY_GRID):
        params = {**SR_FIXED_EXIT, **combo,
                  "rsi_len": 2, "short_rsi": 90, "vwap_dev": 0,
                  "adx_period": 14, "atr_len": 14,
                  "_freq": freq}
        try:
            d = run_one(sr_code, freq, params)
            m = extract_metrics(d, "sr_entry", params)
            sr_entry_results.append(m)
            total_calls += 1
            print(f"    [{total_calls:>4}] long_rsi={combo['long_rsi']:>3} ema={combo['ema_len']:>4} adx_max={combo['adx_max']:>3}  "
                  f"PnL={m['netPnl']:>10.2f}  trades={m['tradeCount']:>4}  win={m['winRate']:>5.1f}%  DD={m['maxDrawdown']:>5.1f}%")
        except Exception as e:
            print(f"    [{total_calls:>4}] ERROR: {e}")
            total_calls += 1

    if sr_entry_results:
        all_results.extend(sr_entry_results)
        # Pick top 3 by netPnl
        sr_entry_results.sort(key=lambda x: x["netPnl"], reverse=True)
        top_entry = sr_entry_results[0]
        print(f"\n  >>> 最佳入场: long_rsi={top_entry['long_rsi']} ema_len={top_entry['ema_len']} adx_max={top_entry['adx_max']}  "
              f"PnL={top_entry['netPnl']:.2f}")

        # ---- stable_reversion Stage 2: exit params ----
        print(f"\n  [stable_reversion] Stage 2: 出场优化 ({len(list(make_combos(SR_EXIT_GRID)))} combos)")
        for combo in make_combos(SR_EXIT_GRID):
            params = {"long_rsi": top_entry["long_rsi"], "ema_len": top_entry["ema_len"],
                      "adx_max": top_entry["adx_max"], **combo,
                      "rsi_len": 2, "short_rsi": 90, "vwap_dev": 0,
                      "adx_period": 14, "atr_len": 14,
                      "_freq": freq}
            try:
                d = run_one(sr_code, freq, params)
                m = extract_metrics(d, "sr_exit", params)
                all_results.append(m)
                total_calls += 1
                print(f"    [{total_calls:>4}] sl={combo['sl_atr']:.1f} tp={combo['tp_atr']:.1f} time={combo['time_stop']:>3}  "
                      f"PnL={m['netPnl']:>10.2f}  trades={m['tradeCount']:>4}  win={m['winRate']:>5.1f}%  DD={m['maxDrawdown']:>5.1f}%")
            except Exception as e:
                print(f"    [{total_calls:>4}] ERROR: {e}")
                total_calls += 1

    # ---- ladder_double_k ----
    print(f"\n  [ladder_double_k] Grid search ({len(list(make_combos(LDK_GRID)))} combos)")
    for combo in make_combos(LDK_GRID):
        patched = patch_ladder_double_k(ldk_code_orig, combo)
        params = {**combo, "_freq": freq}
        try:
            d = run_one(patched, freq, params)
            m = extract_metrics(d, "ldk", params)
            all_results.append(m)
            total_calls += 1
            print(f"    [{total_calls:>4}] sma={combo['ema_fast']:>3} lookback={combo['lookback']:>2} gap={combo['min_gap']}  "
                  f"PnL={m['netPnl']:>10.2f}  trades={m['tradeCount']:>4}  win={m['winRate']:>5.1f}%  DD={m['maxDrawdown']:>5.1f}%")
        except Exception as e:
            print(f"    [{total_calls:>4}] ERROR: {e}")
            total_calls += 1

# ========================================
# Summary
# ========================================
elapsed = time.time() - t_start
print(f"\n{'='*80}")
print(f"完成! {total_calls} 次调用, 耗时 {elapsed/60:.1f} 分钟")
print(f"结果: {OUT}")

# Save JSON
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)

# Save CSV
with open(CSV, "w", encoding="utf-8") as f:
    if all_results:
        keys = all_results[0].keys()
        f.write(",".join(keys) + "\n")
        for r in all_results:
            f.write(",".join(str(r.get(k, "")) for k in keys) + "\n")

# ---- Top results per strategy per timeframe ----
print(f"\n{'='*80}")
print("最佳参数汇总")
print(f"{'='*80}")

for freq in TIMEFRAMES:
    freq_results = [r for r in all_results if r.get("frequency") == freq]
    if not freq_results:
        continue

    freq_results.sort(key=lambda x: x["netPnl"], reverse=True)

    # Best sr
    sr_best = [r for r in freq_results if r["strategy"].startswith("sr_")]
    sr_best = sr_best[0] if sr_best else None

    # Best ldk
    ldk_best = [r for r in freq_results if r["strategy"] == "ldk"]
    ldk_best = ldk_best[0] if ldk_best else None

    print(f"\n--- {freq} ---")
    if sr_best:
        print(f"  stable_reversion: PnL={sr_best['netPnl']:>10.2f}  "
              f"trades={sr_best['tradeCount']:>4}  win={sr_best['winRate']:>5.1f}%  "
              f"DD={sr_best['maxDrawdown']:>5.1f}%  SR={sr_best['sharpeRatio']:>5.2f}")
        print(f"    参数: long_rsi={sr_best.get('long_rsi','?')} ema_len={sr_best.get('ema_len','?')} "
              f"adx_max={sr_best.get('adx_max','?')} sl={sr_best.get('sl_atr','?')} "
              f"tp={sr_best.get('tp_atr','?')} time={sr_best.get('time_stop','?')}")
    if ldk_best:
        print(f"  ladder_double_k:  PnL={ldk_best['netPnl']:>10.2f}  "
              f"trades={ldk_best['tradeCount']:>4}  win={ldk_best['winRate']:>5.1f}%  "
              f"DD={ldk_best['maxDrawdown']:>5.1f}%  SR={ldk_best['sharpeRatio']:>5.2f}")
        print(f"    参数: sma={ldk_best.get('ema_fast','?')} lookback={ldk_best.get('lookback','?')} "
              f"gap={ldk_best.get('min_gap','?')}")

print(f"\n{'='*80}")
print("详细数据:")
print(f"  JSON: {OUT}")
print(f"  CSV:  {CSV}")
