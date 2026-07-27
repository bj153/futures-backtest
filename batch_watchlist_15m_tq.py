"""批量回测 eagle_ladder_k_adx：自选23品种 x 15分钟周期（天勤数据源，约9个月）
结果增量存 batch_results_watchlist_15m_tq.json
用法: python batch_watchlist_15m_tq.py [max_seconds]  -- 到时间自动退出，可反复调用断点续跑
"""
import json, sys, time, urllib.request

strategy = open('backend/strategies/eagle_ladder_k_adx.py', encoding='utf-8').read()

# 品种: (板块, 合约乘数)  —— 合约代码为天勤当前主力（2026-07-22 解析）
CONTRACTS = {
    'ao2609': ('黑色', 20),    # 氧化铝 20吨/手
    'jm2609': ('黑色', 60),    # 焦煤
    'i2609':  ('黑色', 100),   # 铁矿石
    'rb2610': ('黑色', 10),    # 螺纹钢
    'fg609':  ('化工', 20),    # 玻璃
    'sa609':  ('化工', 20),    # 纯碱
    'sh609':  ('化工', 30),    # 烧碱 30吨/手
    'ma609':  ('化工', 10),    # 甲醇
    'eg2609': ('化工', 10),    # 乙二醇
    'ta609':  ('化工', 5),     # PTA
    'v2609':  ('化工', 5),     # PVC
    'ec2608': ('能源', 50),    # 集运欧线 50元/点
    'sc2609': ('能源', 1000),  # 原油
    'fu2609': ('能源', 10),    # 燃料油
    'bu2609': ('能源', 10),    # 沥青
    'pg2608': ('能源', 20),    # 液化气
    'p2609':  ('农产品', 10),  # 棕榈油
    'y2609':  ('农产品', 10),  # 豆油
    'm2609':  ('农产品', 10),  # 豆粕
    'c2609':  ('农产品', 10),  # 玉米
    'sr609':  ('农产品', 10),  # 白糖
    'cf609':  ('农产品', 5),   # 棉花
    'sp2609': ('农产品', 10),  # 纸浆
}
FREQ = '15m'
START, END = '2025-10-15', '2026-07-20'   # 天勤免费版实际可取范围
MAX_SEC = float(sys.argv[1]) if len(sys.argv) > 1 else 280
OUT = 'batch_results_watchlist_15m_tq.json'

def run(code, mult):
    payload = {
        'strategy': strategy, 'contract_code': code, 'frequency': FREQ,
        'start_date': START, 'end_date': END,
        'initial_capital': 200000, 'commission': 0.0001,
        'margin_ratio': 0.1, 'source': 'tqsdk', 'multiplier': mult,
        'ema_fast': 24, 'ema_slow': 40,
    }
    req = urllib.request.Request(
        'http://localhost:8001/api/backtest',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=150) as r:
        return json.loads(r.read())

try:
    results = json.load(open(OUT, encoding='utf-8'))
except Exception:
    results = []

t0 = time.time()
done_keys = {r.get('key') for r in results}
for code, (sector, mult) in CONTRACTS.items():
    key = f'{code}_{FREQ}'
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
            res = run(code, mult)
            err = None
            break
        except Exception as e:
            err = str(e)[:200]
            print(f'    attempt{attempt} ERROR: {err}', flush=True)
            time.sleep(3)
    if err is not None:
        results.append({'key': key, 'contract': code, 'freq': FREQ,
                        'sector': sector, 'error': err})
    else:
        results.append({
            'key': key, 'contract': code, 'freq': FREQ, 'sector': sector,
            'bars': len(res.get('klineData', [])),
            'totalReturn': res.get('totalReturn'), 'winRate': res.get('winRate'),
            'tradeCount': res.get('tradeCount'), 'maxDrawdown': res.get('maxDrawdown'),
            'finalEquity': res.get('finalEquity'),
        })
    done_keys.add(key)
    print('   ', json.dumps(results[-1], ensure_ascii=False), flush=True)
    json.dump(results, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

print('DONE', len(results), '/', len(CONTRACTS), flush=True)
