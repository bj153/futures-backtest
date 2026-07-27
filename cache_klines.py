"""缓存自选23合约 x 6周期的天勤K线到 data/klines/{code}_{freq}.csv
天勤免费版限制：单序列最多约 8000 根，短周期实际覆盖不足一年（脚本会输出实际范围）。
用法: python cache_klines.py            # 全部
      python cache_klines.py 15m 1h     # 只刷指定周期
"""
import os, sys, json, time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv('backend/.env')
OUT_DIR = Path('data/klines')
OUT_DIR.mkdir(parents=True, exist_ok=True)

CONTRACTS = json.load(open('watchlist_contracts.json', encoding='utf-8'))
# tqsdk 代码（郑商所大写3位，其他小写4位）—— watchlist_contracts.json 已存好
SYMS = {name: sym for name, sym in CONTRACTS.items()}

FREQS = {'1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '1d': 86400}
TARGET_START = '2025-07-20'

def main():
    only = set(sys.argv[1:]) or set(FREQS)
    from tqsdk import TqApi, TqAuth
    api = TqApi(auth=TqAuth(os.getenv('TQSDK_ACCOUNT', 'bj153'), os.getenv('TQSDK_PASSWORD', '')))

    tasks = [(name, sym, f) for name, sym in SYMS.items() for f in FREQS if f in only]
    todo = [t for t in tasks if not (OUT_DIR / f'{t[1].split(".")[1]}_{t[2]}.csv').exists()]
    print(f'total {len(tasks)}, cached {len(tasks)-len(todo)}, to fetch {len(todo)}', flush=True)

    series = {}
    for name, sym, freq in todo:
        series[(name, sym, freq)] = api.get_kline_serial(sym, FREQS[freq], data_length=8000)
    api.wait_update()

    stats = []
    for (name, sym, freq), kl in series.items():
        import pandas as pd
        df = pd.DataFrame(kl).dropna(subset=['close'])
        if df.empty:
            stats.append((name, sym, freq, 0, '-', '-'))
            continue
        df['time'] = (pd.to_datetime(df['datetime'], unit='ns', utc=True)
                      .dt.tz_convert('Asia/Shanghai').dt.tz_localize(None))
        # 郑商所3位代码10年会重复（如SR609=2016/2026），裁剪掉目标起始日之前的旧合约段
        df = df[df['time'] >= TARGET_START]
        if df.empty:
            stats.append((name, sym, freq, 0, '-', '-'))
            continue
        df = df[['time', 'open', 'high', 'low', 'close', 'volume', 'open_oi', 'close_oi']]
        code = sym.split('.')[1]
        df.to_csv(OUT_DIR / f'{code}_{freq}.csv', index=False)
        stats.append((name, sym, freq, len(df), str(df['time'].iloc[0])[:16], str(df['time'].iloc[-1])[:16]))
        print(f'{name} {sym} {freq}: {len(df)} bars [{stats[-1][4]} ~ {stats[-1][5]}]', flush=True)

    api.close()
    import pandas as pd
    rep = pd.DataFrame(stats, columns=['name', 'symbol', 'freq', 'bars', 'first', 'last'])
    rep.to_csv(OUT_DIR / '_cache_report.csv', index=False)
    print('DONE, report -> data/klines/_cache_report.csv', flush=True)

if __name__ == '__main__':
    main()
