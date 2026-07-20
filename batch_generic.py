"""通用批量回测（参数化策略/输出）：四大板块主力 x (1d,1h)，结果增量存 batch_results_adx_all.json
用法: python batch_adx_all.py [max_seconds]  -- 到时间自动退出，可反复调用断点续跑
"""
import json, re, sys, time, urllib.request

STRATEGY_FILE = sys.argv[2]
OUT = sys.argv[3]
strategy = open(STRATEGY_FILE, encoding='utf-8').read()

SECTOR = {
    # 黑色
    'rb2610': ('黑色', 10), 'hc2610': ('黑色', 10), 'i2609': ('黑色', 100),
    'j2609': ('黑色', 100), 'jm2609': ('黑色', 60), 'fg2609': ('黑色', 20),
    'sf2609': ('黑色', 5), 'sm2609': ('黑色', 5), 'ss2609': ('黑色', 5),
    'wr2609': ('黑色', 10),  # 线材 10吨/手（未在用户清单，按上期所标准）
    # 化工
    'ma2609': ('化工', 10), 'pp2609': ('化工', 5), 'v2609': ('化工', 5),
    'ta2609': ('化工', 5), 'eg2609': ('化工', 10), 'ru2609': ('化工', 10),
    'bu2609': ('化工', 10), 'pf2609': ('化工', 5), 'sa2609': ('化工', 20),
    'ur2609': ('化工', 20), 'eb2608': ('化工', 10), 'br2609': ('化工', 5),
    'px2609': ('化工', 5), 'sh2609': ('化工', 5),
    'nr2609': ('化工', 10),  # 20号胶 10吨/手
    'pr2609': ('化工', 15),  # 瓶片 15吨/手（不确定，报告标注）
    'bz2608': ('化工', 30),  # 纯苯 30吨/手（不确定，报告标注）
    # 能源
    'sc2609': ('能源', 1000), 'fu2609': ('能源', 10), 'pg2608': ('能源', 20),
    # 农产品
    'm2609': ('农产品', 10), 'y2609': ('农产品', 10), 'p2609': ('农产品', 10),
    'a2609': ('农产品', 10), 'c2609': ('农产品', 10), 'cs2609': ('农产品', 10),
    'rm2609': ('农产品', 10), 'oi2609': ('农产品', 10), 'cf2609': ('农产品', 5),
    'sr2609': ('农产品', 10), 'ap2610': ('农产品', 10), 'jd2609': ('农产品', 10),
    'b2609': ('农产品', 10), 'ad2609': ('农产品', 10),
    'cj2609': ('农产品', 5),   # 红枣 5吨/手
    'cy2609': ('农产品', 5),   # 棉纱 5吨/手
    'pk2611': ('农产品', 5),   # 花生 5吨/手
    'pm2609': ('农产品', 50),  # 普麦 50吨/手
    'jr2609': ('农产品', 20),  # 粳稻 20吨/手
    'ri2609': ('农产品', 20),  # 早籼稻 20吨/手
    'rr2608': ('农产品', 10),  # 粳米 10吨/手
    'rs2609': ('农产品', 10),  # 菜籽 10吨/手
    'wh2609': ('农产品', 20),  # 强麦 20吨/手
}
FREQS = ['1d', '1h']
MAX_SEC = float(sys.argv[1]) if len(sys.argv) > 1 else 280

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
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())

try:
    results = json.load(open(OUT, encoding='utf-8'))
except Exception:
    results = []

t0 = time.time()
done_keys = {r.get('key') for r in results}
for code, (sector, mult) in SECTOR.items():
    for freq in FREQS:
        key = f'{code}_{freq}'
        if key in done_keys:
            continue
        if time.time() - t0 > MAX_SEC:
            print('TIME BUDGET REACHED, exit for resume', flush=True)
            json.dump(results, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            sys.exit(2)
        print(f'>>> {key} (x{mult}) ...', flush=True)
        err = None
        res = None
        for attempt in (1, 2):
            try:
                res = run(code, mult, freq)
                err = None
                break
            except Exception as e:
                err = str(e)[:200]
                print(f'    attempt{attempt} ERROR: {err}', flush=True)
                time.sleep(3)
        if err is not None:
            results.append({'key': key, 'contract': code, 'freq': freq,
                            'sector': sector, 'error': err})
        else:
            results.append({
                'key': key, 'contract': code, 'freq': freq, 'sector': sector,
                'bars': len(res.get('klineData', [])),
                'totalReturn': res.get('totalReturn'), 'winRate': res.get('winRate'),
                'tradeCount': res.get('tradeCount'), 'maxDrawdown': res.get('maxDrawdown'),
                'finalEquity': res.get('finalEquity'),
            })
        done_keys.add(key)
        print('   ', json.dumps(results[-1], ensure_ascii=False), flush=True)
        json.dump(results, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

total = len(SECTOR) * len(FREQS)
print('DONE', len(results), '/', total, flush=True)
