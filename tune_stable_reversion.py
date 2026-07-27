"""stable_reversion 参数扫描"""
import requests, json, time

API = "http://localhost:8001/api/backtest"

strategy_template = '''# ========== 稳定均值回归（StableReversion）==========
def init(context):
    context['rsi_len'] = context.get('rsi_len', 2)
    context['long_rsi'] = context.get('long_rsi', {long_rsi})
    context['short_rsi'] = context.get('short_rsi', {short_rsi})
    context['ema_len'] = context.get('ema_len', 200)
    context['adx_period'] = context.get('adx_period', 14)
    context['adx_max'] = context.get('adx_max', {adx_max})
    context['vwap_dev'] = context.get('vwap_dev', {vwap_dev})
    context['atr_len'] = context.get('atr_len', 14)
    context['sl_atr'] = context.get('sl_atr', {sl_atr})
    context['tp_atr'] = context.get('tp_atr', {tp_atr})
    context['time_stop'] = context.get('time_stop', 12)
    context['history'] = []
    context['stop'] = None
    context['take_profit'] = None
    context['entry_bar'] = None
    context['tr_list'] = []
    context['pdm_list'] = []
    context['mdm_list'] = []
    context['dx_list'] = []
    context['adx_list'] = []
    context['sess_key'] = None
    context['cum_pv'] = 0.0
    context['cum_v'] = 0.0

def _atr(context):
    h = context['history']
    n = context['atr_len']
    if len(h) < n + 1: return None
    total = 0.0
    for k in range(len(h)-n, len(h)):
        cur = h[k]; pc = h[k-1]['close']
        total += max(cur['high']-cur['low'], abs(cur['high']-pc), abs(cur['low']-pc))
    return total/n

def _sess_key(ts, pk):
    d=ts[:10]; h=int(ts[11:13])
    if pk is None: return d+('N' if h>=20 else 'D')
    pd=pk[:10]; pt=pk[10:]
    if h>=20:
        if pt=='D' and pd==d: return d+'N'
        if pd!=d: return d+'N'
        return pk
    else:
        return d+'D' if pd!=d else pk

def _update_adx(context):
    h=context['history']
    if len(h)<2: return
    c=h[-1]; p=h[-2]
    tr=max(c['high']-c['low'],abs(c['high']-p['close']),abs(c['low']-p['close']))
    um=c['high']-p['high']; dm=p['low']-c['low']
    pdm=um if(um>dm and um>0)else 0.0
    mdm=dm if(dm>um and dm>0)else 0.0
    context['tr_list'].append(tr); context['pdm_list'].append(pdm); context['mdm_list'].append(mdm)
    n=context['adx_period']
    if len(context['tr_list'])<n: return
    ts=ps=ms=0.0
    for k in range(-n,0): ts+=context['tr_list'][k]; ps+=context['pdm_list'][k]; ms+=context['mdm_list'][k]
    if ts<=0: return
    pdi=100*ps/ts; mdi=100*ms/ts; ds=pdi+mdi
    dx=100*abs(pdi-mdi)/ds if ds>0 else 0
    context['dx_list'].append(dx)
    if len(context['dx_list'])<n: return
    dxs=0.0
    for k in range(-n,0): dxs+=context['dx_list'][k]
    context['adx_list'].append(dxs/n)

def handle_bar(context, bar):
    h=context['history']; h.append(bar); i=len(h)
    _update_adx(context)
    c=bar['close']; hi=bar['high']; lo=bar['low']; v=bar.get('volume',0)
    ts=bar.get('time',''); hm=ts[11:16] if len(ts)>=16 else ''
    pos=context.get('position',0)
    k=_sess_key(ts,context['sess_key'])
    if k!=context['sess_key']: context['sess_key']=k; context['cum_pv']=0.0; context['cum_v']=0.0
    tp=(hi+lo+c)/3.0; context['cum_pv']+=tp*v; context['cum_v']+=v
    vwap=context['cum_pv']/context['cum_v'] if context['cum_v']>0 else c
    if i<context['ema_len']+context['atr_len']+20: return
    atr=_atr(context)
    if atr is None or atr<=0: return
    cl=[b['close'] for b in h]
    rv=rsi(cl,context['rsi_len'])[-1]; ev=ema(cl,context['ema_len'])[-1]
    if len(context['adx_list'])<1: return
    av=context['adx_list'][-1]
    if av>=context['adx_max']: return
    force=(hm>='14:55' and hm<='15:05')or(hm>='22:55' and hm<='23:00')
    if pos!=0 and force:
        context['_action']='sell' if pos==1 else 'cover'; context['_price']=c
        context['_reason']='强平 %.1f'%c; context['stop']=None; context['take_profit']=None; context['entry_bar']=None
        return
    if pos!=0 and context['stop'] is not None:
        hit=False
        if pos==1:
            if lo<=context['stop']: context['_action']='sell'; context['_price']=context['stop']; context['_reason']='多/止损'; hit=True
            elif hi>=context['take_profit']: context['_action']='sell'; context['_price']=context['take_profit']; context['_reason']='多/止盈'; hit=True
        else:
            if hi>=context['stop']: context['_action']='cover'; context['_price']=context['stop']; context['_reason']='空/止损'; hit=True
            elif lo<=context['take_profit']: context['_action']='cover'; context['_price']=context['take_profit']; context['_reason']='空/止盈'; hit=True
        if not hit and context['entry_bar'] is not None:
            if i-context['entry_bar']>=context['time_stop']:
                context['_action']='sell' if pos==1 else 'cover'; context['_price']=c; context['_reason']='时间离场'; hit=True
        if hit: context['stop']=None; context['take_profit']=None; context['entry_bar']=None; return
        return
    ld=c>ev; sd=c<ev
    dev=context['vwap_dev']*atr
    ldev=c<vwap-dev if context['vwap_dev']>0 else True
    sdev=c>vwap+dev if context['vwap_dev']>0 else True
    if (hm>='14:40' and hm<='15:05')or(hm>='22:40' and hm<='23:00'): return
    if rv<context['long_rsi'] and ld and ldev:
        context['_action']='buy'; context['_price']=c
        context['stop']=c-context['sl_atr']*atr; context['take_profit']=c+context['tp_atr']*atr
        context['entry_bar']=i; context['_reason']='多 %.1f'%c
        return
    if rv>context['short_rsi'] and sd and sdev:
        context['_action']='short'; context['_price']=c
        context['stop']=c+context['sl_atr']*atr; context['take_profit']=c-context['tp_atr']*atr
        context['entry_bar']=i; context['_reason']='空 %.1f'%c
        return
'''

# 参数网格 - 精选组合（关键维度交叉）
grid = [
    # (long_rsi, short_rsi, adx_max, vwap_dev, sl_atr, tp_atr, label)
    (5, 95, 25, 0, 2.0, 2.5,  "RSI:5/95 ADX<25 无VWAP SL2.0 TP2.5"),
    (5, 95, 28, 0, 2.0, 2.5,  "RSI:5/95 ADX<28 无VWAP SL2.0 TP2.5"),
    (8, 92, 25, 0, 2.0, 2.5,  "RSI:8/92 ADX<25 无VWAP SL2.0 TP2.5"),
    (8, 92, 28, 0, 2.0, 2.5,  "RSI:8/92 ADX<28 无VWAP SL2.0 TP2.5"),
    (8, 92, 25, 0, 2.0, 3.0,  "RSI:8/92 ADX<25 无VWAP SL2.0 TP3.0"),
    (10, 90, 22, 0, 2.0, 2.5, "RSI:10/90 ADX<22 无VWAP SL2.0 TP2.5"),
    (10, 90, 25, 0, 2.0, 2.5, "RSI:10/90 ADX<25 无VWAP SL2.0 TP2.5"),
    (10, 90, 25, 0, 2.0, 3.0, "RSI:10/90 ADX<25 无VWAP SL2.0 TP3.0"),
    (10, 90, 28, 0, 2.0, 2.5, "RSI:10/90 ADX<28 无VWAP SL2.0 TP2.5"),
    (10, 90, 28, 0, 2.0, 3.0, "RSI:10/90 ADX<28 无VWAP SL2.0 TP3.0"),
    (12, 88, 25, 0, 2.0, 2.5, "RSI:12/88 ADX<25 无VWAP SL2.0 TP2.5"),
    (12, 88, 28, 0, 2.0, 3.0, "RSI:12/88 ADX<28 无VWAP SL2.0 TP3.0"),
    (15, 85, 25, 0, 2.0, 2.5, "RSI:15/85 ADX<25 无VWAP SL2.0 TP2.5"),
    (15, 85, 28, 0, 2.0, 3.0, "RSI:15/85 ADX<28 无VWAP SL2.0 TP3.0"),
    # 带VWAP的组合
    (10, 90, 25, 1.0, 2.0, 3.0, "RSI:10/90 ADX<25 VWAP1.0 SL2.0 TP3.0"),
    (12, 88, 25, 1.0, 2.0, 3.0, "RSI:12/88 ADX<25 VWAP1.0 SL2.0 TP3.0"),
    (12, 88, 28, 1.0, 2.0, 3.0, "RSI:12/88 ADX<28 VWAP1.0 SL2.0 TP3.0"),
    # 紧止损
    (10, 90, 25, 0, 1.5, 2.5, "RSI:10/90 ADX<25 无VWAP SL1.5 TP2.5"),
    (10, 90, 28, 0, 1.5, 3.0, "RSI:10/90 ADX<28 无VWAP SL1.5 TP3.0"),
    (12, 88, 25, 0, 1.5, 2.5, "RSI:12/88 ADX<25 无VWAP SL1.5 TP2.5"),
]

results = []
total = len(grid)
for idx, (lr, sr, adx, vd, sl, tp, label) in enumerate(grid):
    code = strategy_template.format(long_rsi=lr, short_rsi=sr, adx_max=adx,
                                     vwap_dev=vd, sl_atr=sl, tp_atr=tp)
    t0 = time.time()
    try:
        r = requests.post(API, json={
            "contract_code": "MA609", "frequency": "15m",
            "start_date": "2025-09-12", "end_date": "2026-07-22",
            "strategy": code, "initial_capital": 100000, "commission": 0.0003,
            "margin_ratio": 0.1, "multiplier": 10, "source": "cache"
        }, timeout=180)
        d = r.json()
        pnl = d.get("netPnl", 0)
        trs = d.get("tradeCount", 0)
        w = d.get("winRate", 0)
        dd_v = d.get("maxDrawdown", 0)
        srs = d.get("sharpeRatio", 0)
        results.append((pnl, trs, w, dd_v, srs, label))
        print(f"  [{idx+1}/{total}] {label:<55} PnL={pnl:>8.0f}  N={trs:>3}  W={w:>4.1f}%  DD={dd_v:>4.1f}%  SR={srs:.2f}")
    except Exception as e:
        print(f"  [{idx+1}/{total}] {label}: ERROR {e}")

results.sort(key=lambda x: x[0], reverse=True)
print("\n" + "=" * 105)
print(f"{'排名':<4} {'参数':<55} {'净收益':>8} {'交易':>4} {'胜率':>6} {'回撤':>6} {'夏普':>5}")
print("-" * 105)
for rank, (pnl, n, w, dd_v, srs, label) in enumerate(results[:20], 1):
    print(f"{rank:<4} {label:<55} {pnl:>8.0f} {n:>4} {w:>5.1f}% {dd_v:>5.1f}% {srs:>5.2f}")
