"""对比回测：ladder_double_k_be（保本版）@ 1h x 自选23合约（缓存数据源）
结果存 batch_results_be_1h.json，断点续跑
"""
import json, sys, time, urllib.request

strategy = open('backend/strategies/ladder_double_k_be.py', encoding='utf-8').read()

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
MAX_SEC = float(sys.argv[1]) if len(sys.argv) > 1 else 280
OUT = 'batch_results_be_1h.json'

def run(code, mult):
    payload = {
        'strategy': strategy, 'contract_code': code, 'frequency': '1h',
        'start_date': '2025-07-20', 'end_date': '2026-07-20',
        'initial_capital': 200000, 'commission': 0.0001,
        'margin_ratio': 0.1, 'source': 'cache', 'multiplier': mult,
        'ema_fast': 24, 'ema_slow': 40,
    }
    req = urllib.request.Request(
        'http://localhost:8001/api/backtest',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())

try:
    results = json.load(open(OUT, encoding='utf-8'))
except Exception:
    results = []

t0 = time.time()
done = {r['key'] for r in results}
for code, (sector, mult) in CONTRACTS.items():
    key = f'be|{code}|1h'
    if key in done:
        continue
    if time.time() - t0 > MAX_SEC:
        json.dump(results, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        sys.exit(2)
    print(f'>>> {key}', flush=True)
    err, res = None, None
    for attempt in (1, 2):
        try:
            res = run(code, mult)
            break
        except Exception as e:
            err = str(e)[:200]
            print(f'    attempt{attempt} ERROR: {err}', flush=True)
            time.sleep(3)
    if err:
        results.append({'key': key, 'contract': code, 'sector': sector, 'error': err})
    else:
        results.append({
            'key': key, 'contract': code, 'sector': sector,
            'bars': len(res.get('klineData', [])),
            'totalReturn': res.get('totalReturn'), 'winRate': res.get('winRate'),
            'tradeCount': res.get('tradeCount'), 'maxDrawdown': res.get('maxDrawdown'),
            'finalEquity': res.get('finalEquity'),
        })
    print('   ', json.dumps({k: v for k, v in results[-1].items() if k != 'key'}, ensure_ascii=False), flush=True)
    json.dump(results, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

print('DONE', len(results), '/', len(CONTRACTS), flush=True)
