"""批量回测 eagle_ladder_k_adx：多品种 × 多周期，结果存 batch_results_adx.json"""
import json, sys, urllib.request

strategy = open('backend/strategies/eagle_ladder_k_adx.py', encoding='utf-8').read()

CONTRACTS = {
    'rb2610': 10,   # 螺纹钢
    'i2609': 100,   # 铁矿石
    'ma2609': 10,   # 甲醇
    'p2609': 10,    # 棕榈油
    'ag2608': 15,   # 白银
}
FREQS = sys.argv[1].split(',') if len(sys.argv) > 1 else ['1d', '1h', '30m']

def run(code, mult, freq):
    payload = {
        'strategy': strategy, 'contract_code': code, 'frequency': freq,
        'start_date': '2025-07-20', 'end_date': '2026-07-20',
        'initial_capital': 200000, 'commission': 0.0001,
        'margin_ratio': 0.1, 'source': 'akshare', 'multiplier': mult,
        'ema_fast': 24, 'ema_slow': 40,
    }
    req = urllib.request.Request(
        'http://localhost:8001/api/backtest',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())

results = []
try:
    results = json.load(open('batch_results_adx.json', encoding='utf-8'))
except Exception:
    pass

for code, mult in CONTRACTS.items():
    for freq in FREQS:
        key = f'{code}_{freq}'
        if any(r.get('key') == key for r in results):
            continue
        print(f'>>> {key} ...', flush=True)
        try:
            res = run(code, mult, freq)
            klines = len(res.get('klineData', []))
            results.append({
                'key': key, 'contract': code, 'freq': freq, 'bars': klines,
                'totalReturn': res.get('totalReturn'), 'winRate': res.get('winRate'),
                'tradeCount': res.get('tradeCount'), 'maxDrawdown': res.get('maxDrawdown'),
                'finalEquity': res.get('finalEquity'),
            })
            print('   ', json.dumps(results[-1], ensure_ascii=False), flush=True)
        except Exception as e:
            results.append({'key': key, 'contract': code, 'freq': freq, 'error': str(e)[:200]})
            print('    ERROR:', str(e)[:200], flush=True)
        json.dump(results, open('batch_results_adx.json', 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)

print('DONE', len(results))
