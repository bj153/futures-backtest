"""批量回测：mean_revert（BOLL均值回归）@ 23合约（缓存数据源）
用法:
    python batch_mean_revert.py --freq 15m --tag base [--params '{"adx_max":20}']
结果追加到 batch_results_regime.json，断点续跑。
"""
import argparse, json, re, sys, time, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument('--freq', default='15m')
ap.add_argument('--tag', default='base')
ap.add_argument('--file', default='backend/strategies/regime_adaptive.py')
ap.add_argument('--params', default='{}')
ap.add_argument('--max-sec', type=float, default=280)
ap.add_argument('--exclude', default='', help='逗号分隔的排除合约，如 sc2609,ec2608')
args = ap.parse_args()
EXCLUDE = set(x for x in args.exclude.split(',') if x)

strat_name = args.file.replace('\\', '/').split('/')[-1].replace('.py', '')
strategy = open(args.file, encoding='utf-8').read()
overrides = json.loads(args.params)
for k, v in overrides.items():
    lit = repr(v) if isinstance(v, str) else str(v)
    pat = re.compile(r"(context\.get\('%s',\s*)('[^']*'|[-0-9.]+)(\))" % re.escape(k))
    strategy, cnt = pat.subn(lambda m: m.group(1) + lit + m.group(3), strategy)
    if cnt != 1:
        print(f'WARN: param {k} replaced {cnt} times', flush=True)

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
OUT = 'batch_results_regime.json'

def run(code, mult):
    payload = {
        'strategy': strategy, 'contract_code': code, 'frequency': args.freq,
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
    if code in EXCLUDE:
        continue
    key = f'{strat_name}|{args.tag}|{code}|{args.freq}'
    if key in done:
        continue
    if time.time() - t0 > args.max_sec:
        json.dump(results, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        sys.exit(2)
    print(f'>>> {key}', flush=True)
    err, res = None, None
    for attempt in (1, 2, 3):
        try:
            res = run(code, mult)
            err = None
            break
        except Exception as e:
            err = str(e)[:200]
            print(f'    attempt{attempt} ERROR: {err}', flush=True)
            time.sleep(3)
    if err:
        results.append({'key': key, 'strategy': strat_name, 'tag': args.tag,
                        'freq': args.freq, 'contract': code, 'sector': sector, 'error': err})
    else:
        results.append({
            'key': key, 'strategy': strat_name, 'tag': args.tag,
            'freq': args.freq, 'contract': code, 'sector': sector,
            'params': overrides,
            'bars': len(res.get('klineData', [])),
            'totalReturn': res.get('totalReturn'), 'winRate': res.get('winRate'),
            'tradeCount': res.get('tradeCount'), 'maxDrawdown': res.get('maxDrawdown'),
            'finalEquity': res.get('finalEquity'),
        })
    print('   ', json.dumps({k: v for k, v in results[-1].items() if k != 'key'}, ensure_ascii=False), flush=True)
    json.dump(results, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

print('DONE', len(results), '/', len(CONTRACTS), flush=True)
