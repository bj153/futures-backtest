# -*- coding: utf-8 -*-
import json
from collections import defaultdict

d = json.load(open('batch_results_3strat_cache.json', encoding='utf-8'))
ok = [r for r in d if 'error' not in r]
bad = [r for r in d if 'error' in r]
strategies = ['ladder_double_k', 'eagle_ladder_k', 'eagle_ladder_k_adx']
freqs = ['1m', '5m', '15m', '30m', '1h', '1d']

def agg(rows):
    n = len(rows)
    if n == 0: return None
    return dict(
        n=n,
        ret=sum(r['totalReturn'] for r in rows)/n,
        pos=sum(1 for r in rows if r['totalReturn'] > 0)/n*100,
        win=sum(r['winRate'] for r in rows)/n,
        dd=sum(r['maxDrawdown'] for r in rows)/n,
        tc=sum(r['tradeCount'] for r in rows)/n,
    )

cells = {}
for s in strategies:
    for f in freqs:
        cells[(s,f)] = agg([r for r in ok if r['strategy']==s and r['freq']==f])

L = []
w = L.append
w('# 三策略全量回测汇总（本地缓存数据源）\n')
w(f'- 数据文件：`batch_results_3strat_cache.json`')
w(f'- 总组数：**{len(d)}**（3 策略 × 23 合约 × 6 周期）')
w(f'- 成功：**{len(ok)}**，失败：**{len(bad)}**\n')

w('## 1. 失败清单\n')
if bad:
    w('| key | error |')
    w('|---|---|')
    for r in bad:
        w(f"| {r.get('key','?')} | {str(r['error'])[:150]} |")
else:
    w('无失败组。')
w('')

metric_defs = [('ret','平均收益率 (%)'), ('pos','盈利合约占比 (%)'), ('win','平均胜率 (%)'), ('dd','平均最大回撤 (%)'), ('tc','平均交易笔数')]
w('## 2. 策略 × 周期 透视表\n')
for m, title in metric_defs:
    w(f'### {title}\n')
    w('| 策略 \ 周期 | ' + ' | '.join(freqs) + ' |')
    w('|---|' + '---|'*len(freqs))
    for s in strategies:
        row = [s]
        for f in freqs:
            c = cells[(s,f)]
            row.append(f"{c[m]:.2f}" if c else '—')
        w('| ' + ' | '.join(row) + ' |')
    w('')

w('## 3. 每个策略 × 周期的 Top3 / Bottom3 合约（按收益率）\n')
for s in strategies:
    for f in freqs:
        rows = sorted([r for r in ok if r['strategy']==s and r['freq']==f], key=lambda r: -r['totalReturn'])
        if not rows: continue
        t3 = rows[:3]; b3 = rows[-3:]
        fmt = lambda rs: '；'.join(f"{r['contract']} {r['totalReturn']:+.2f}%" for r in rs)
        w(f"- **{s} @ {f}** — Top3: {fmt(t3)} | Bottom3: {fmt(b3)}")
w('')

w('## 4. 全场 Top10 / Bottom10（strategy|contract|freq）\n')
allr = sorted(ok, key=lambda r: -r['totalReturn'])
w('### Top10\n')
w('| # | 组合 | 收益率% | 胜率% | 最大回撤% | 笔数 |')
w('|---|---|---|---|---|---|')
for i, r in enumerate(allr[:10], 1):
    w(f"| {i} | {r['key']} | {r['totalReturn']:+.2f} | {r['winRate']:.1f} | {r['maxDrawdown']:.2f} | {r['tradeCount']} |")
w('\n### Bottom10\n')
w('| # | 组合 | 收益率% | 胜率% | 最大回撤% | 笔数 |')
w('|---|---|---|---|---|---|')
for i, r in enumerate(allr[-10:], 1):
    w(f"| {i} | {r['key']} | {r['totalReturn']:+.2f} | {r['winRate']:.1f} | {r['maxDrawdown']:.2f} | {r['tradeCount']} |")
w('')

# commentary
best = max(((c['ret'], s, f) for (s,f),c in cells.items() if c), )
w('## 5. 简评\n')
w(f"- 全场平均收益最高的策略×周期组合：**{best[1]} @ {best[2]}**（平均收益率 {best[0]:.2f}%）。")
for s in strategies:
    rs = [cells[(s,f)]['ret'] for f in freqs if cells[(s,f)]]
    bf = freqs[[cells[(s,f)]['ret'] for f in freqs].index(max(rs))]
    w(f"- {s}：最佳周期 **{bf}**（{max(rs):.2f}%），最差周期 {freqs[[cells[(s,f)]['ret'] for f in freqs].index(min(rs))]}（{min(rs):.2f}%）。")
avg_win = sum(r['winRate'] for r in ok)/len(ok)
pos_share = sum(1 for r in ok if r['totalReturn']>0)/len(ok)*100
w(f"- 全部成功组平均胜率仅 {avg_win:.1f}%，盈利组占比 {pos_share:.1f}%——胜率普遍在 20–30%，符合趋势/突破类策略「低胜率、靠少数大行情赚钱」的典型特征。")
w('- 短周期（1m/5m）交易笔数多、单笔盈亏被手续费与滑点侵蚀，整体偏弱；具体见透视表。')
w('')
w('> 说明：回测期间未修改任何策略文件；脚本 `batch_3strat_cache.py` 未做修改。1 组（eagle_ladder_k|sc2609|1h）因后端 HTTP 500 记录为 error。')

open('batch_results_3strat_cache_summary.md','w',encoding='utf-8').write('\n'.join(L))
print('written', len(L), 'lines')
print('ok', len(ok), 'bad', len(bad))
print('--- pivot ret ---')
for s in strategies:
    print(s, ['%.2f'%cells[(s,f)]['ret'] for f in freqs])
print('--- pivot win ---')
for s in strategies:
    print(s, ['%.1f'%cells[(s,f)]['win'] for f in freqs])
