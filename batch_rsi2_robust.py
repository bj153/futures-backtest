"""rsi2 参数稳健性：5 合约 × 7 配置 @15m，结果存 batch_results_rsi2_robust.json"""
import json, re, sys, time, urllib.request

base_code = open('backend/strategies/rsi2_revert.py', encoding='utf-8').read()

CONTRACTS = {'pg2608': ('能源', 20), 'sh609': ('化工', 30), 'jm2609': ('黑色', 60),
             'i2609': ('黑色', 100), 'eg2609': ('化工', 10)}

VARIANTS = [
    ('base', {}),
    ('rsi_3_97', {'long_rsi': 3, 'short_rsi': 97}),
    ('rsi_10_90', {'long_rsi': 10, 'short_rsi': 90}),
    ('rsi_len3', {'rsi_len': 3}),
    ('tp_atr1', {'tp_mode': 'atr', 'tp_atr': 1.0}),
    ('sl_2atr', {'sl_atr': 2.0}),
    ('no_ema', {'use_ema': 0}),
]
OUT = 'batch_results_rsi2_robust.json'

def build(overrides):
    code = base_code
    for k, v in overrides.items():
        lit = repr(v) if isinstance(v, str) else str(v)
        pat = re.compile(r"(context\.get\('%s',\s*)('[^']*'|[-0-9.]+)(\))" % re.escape(k))
        code, cnt = pat.subn(lambda m: m.group(1) + lit + m.group(3), code)
        if cnt != 1:
            print(f'WARN: {k} replaced {cnt}x', flush=True)
    return code

def run(code, contract, mult):
    payload = {
        'strategy': code, 'contract_code': contract, 'frequency': '15m',
        'start_date': '2025-07-20', 'end_date': '2026-07-20',
        'initial_capital': 200000, 'commission': 0.0001,
        'margin_ratio': 0.1, 'source': 'cache', 'multiplier': mult,
        'ema_fast': 24, 'ema_slow': 40,
    }
    req = urllib.request.Request('http://localhost:8001/api/backtest',
        data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())

try:
    results = json.load(open(OUT, encoding='utf-8'))
except Exception:
    results = []

t0 = time.time()
done = {r['key'] for r in results}
for vname, ov in VARIANTS:
    code = build(ov)
    for contract, (sector, mult) in CONTRACTS.items():
        key = f'rsi2|{vname}|{contract}|15m'
        if key in done:
            continue
        if time.time() - t0 > 270:
            json.dump(results, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            sys.exit(2)
        print(f'>>> {key}', flush=True)
        err, res = None, None
        for attempt in (1, 2, 3):
            try:
                res = run(code, contract, mult)
                err = None
                break
            except Exception as e:
                err = str(e)[:200]
                print(f'    attempt{attempt} ERROR: {err}', flush=True)
                time.sleep(3)
        if err:
            results.append({'key': key, 'variant': vname, 'contract': contract, 'sector': sector, 'error': err})
        else:
            results.append({'key': key, 'strategy': 'rsi2_revert', 'variant': vname,
                'freq': '15m', 'contract': contract, 'sector': sector, 'params': ov,
                'totalReturn': res.get('totalReturn'), 'winRate': res.get('winRate'),
                'tradeCount': res.get('tradeCount'), 'maxDrawdown': res.get('maxDrawdown')})
        print('   ', json.dumps({k: v for k, v in results[-1].items() if k != 'key'}, ensure_ascii=False), flush=True)
        json.dump(results, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

print('DONE', len(results), flush=True)
