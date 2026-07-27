"""三策略 x 自选23合约 x 6周期 全量回测（本地缓存数据源）
结果增量存 batch_results_3strat_cache.json
用法: python batch_3strat_cache.py [max_seconds]  -- 断点续跑
"""
import json, sys, time, urllib.request
from pathlib import Path

STRATEGIES = ['ladder_double_k', 'eagle_ladder_k', 'eagle_ladder_k_adx']
STRAT_CODE = {s: open(f'backend/strategies/{s}.py', encoding='utf-8').read() for s in STRATEGIES}

CONTRACTS = {
    'ao2609': ('黑色', 20), 'jm2609': ('黑色', 60), 'i2609': ('黑色', 100),
    'rb2610': ('黑色', 10),
    'fg609': ('化工', 20), 'sa609': ('化工', 20), 'sh609': ('化工', 30),
    'ma609': ('化工', 10), 'eg2609': ('化工', 10), 'ta609': ('化工', 5),
    'v2609': ('化工', 5),
    'ec2608': ('能源', 50), 'sc2609': ('能源', 1000), 'fu2609': ('能源', 10),
    'bu2609': ('能源', 10), 'pg2608': ('能源', 20),
    'p2609': ('农产品', 10), 'y2609': ('农产品', 10), 'm2609': ('农产品', 10),
    'c2609': ('农产品', 10), 'sr609': ('农产品', 10), 'cf609': ('农产品', 5),
    'sp2609': ('农产品', 10),
}
FREQS = ['1m', '5m', '15m', '30m', '1h', '1d']
START, END = '2025-07-20', '2026-07-20'   # 实际数据范围以缓存为准（后端自动裁剪）
MAX_SEC = float(sys.argv[1]) if len(sys.argv) > 1 else 280
OUT = 'batch_results_3strat_cache.json'

def run(strat, code, mult, freq):
    payload = {
        'strategy': STRAT_CODE[strat], 'contract_code': code, 'frequency': freq,
        'start_date': START, 'end_date': END,
        'initial_capital': 200000, 'commission': 0.0001,
        'margin_ratio': 0.1, 'source': 'cache', 'multiplier': mult,
        'ema_fast': 24, 'ema_slow': 40,
    }
    req = urllib.request.Request(
        'http://localhost:8001/api/backtest',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=280) as r:
        return json.loads(r.read())

try:
    results = json.load(open(OUT, encoding='utf-8'))
except Exception:
    results = []

t0 = time.time()
done_keys = {r.get('key') for r in results}
total = len(STRATEGIES) * len(CONTRACTS) * len(FREQS)
for strat in STRATEGIES:
    for code, (sector, mult) in CONTRACTS.items():
        for freq in FREQS:
            key = f'{strat}|{code}|{freq}'
            if key in done_keys:
                continue
            if time.time() - t0 > MAX_SEC:
                print('TIME BUDGET REACHED, exit for resume', flush=True)
                json.dump(results, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                sys.exit(2)
            print(f'>>> {key} ({len(results)+1}/{total})', flush=True)
            err = None
            res = None
            for attempt in (1, 2):
                try:
                    res = run(strat, code, mult, freq)
                    err = None
                    break
                except Exception as e:
                    err = str(e)[:200]
                    print(f'    attempt{attempt} ERROR: {err}', flush=True)
                    time.sleep(3)
            if err is not None:
                results.append({'key': key, 'strategy': strat, 'contract': code,
                                'freq': freq, 'sector': sector, 'error': err})
            else:
                results.append({
                    'key': key, 'strategy': strat, 'contract': code, 'freq': freq,
                    'sector': sector, 'bars': len(res.get('klineData', [])),
                    'totalReturn': res.get('totalReturn'), 'winRate': res.get('winRate'),
                    'tradeCount': res.get('tradeCount'), 'maxDrawdown': res.get('maxDrawdown'),
                    'finalEquity': res.get('finalEquity'),
                })
            done_keys.add(key)
            r = results[-1]
            print('   ', json.dumps({k: v for k, v in r.items() if k != 'key'}, ensure_ascii=False)[:200], flush=True)
            json.dump(results, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

print('DONE', len(results), '/', total, flush=True)
