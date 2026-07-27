<template>
  <div class="app-layout">
    <!-- 顶栏 -->
    <TopBar
      :show-editor="showEditor"
      :updating-contracts="updatingContracts"
      @toggle-editor="showEditor = !showEditor"
      @update-contracts="updateContracts"
    />

    <!-- 编辑器视图 -->
    <EditorView v-if="showEditor" @back="showEditor = false" />

    <!-- 主界面 -->
    <div v-else class="main-area">
      <!-- 移动端遮罩 -->
      <div class="sidebar-overlay" :class="{ open: mobileSidebarOpen }" @click="mobileSidebarOpen = false"></div>
      <!-- 左侧控制面板 -->
      <aside class="sidebar" :class="{ open: mobileSidebarOpen }">
        <ContractPanel ref="contractPanelRef" v-model:selected-contract="selectedContract" />
        <SettingsPanel
          :contract="selectedContract"
          :frequency="frequency"
          :data-source="dataSource"
          :start-date="startDate"
          :end-date="endDate"
          :initial-capital="initialCapital"
          :commission-rate="commissionRate"
          :draw-threshold="drawThreshold"
          :use-full-position="useFullPosition"
          :max-risk-pct="maxRiskPct"
          :loading="loading"
          :running="running"
          @update:frequency="frequency = $event"
          @update:data-source="dataSource = $event"
          @update:start-date="startDate = $event"
          @update:end-date="endDate = $event"
          @update:initial-capital="initialCapital = $event"
          @update:commission-rate="commissionRate = $event"
          @update:draw-threshold="drawThreshold = $event"
          @update:use-full-position="useFullPosition = $event"
          @update:max-risk-pct="maxRiskPct = $event"
          @load-data="loadData"
          @run-backtest="runBacktest"
          @draw-polyline="chartTabRef?.drawPolyline()"
        />
      <!-- 移动端浮动菜单按钮 -->
      </aside>
      <div class="mobile-menu-btn" @click="mobileSidebarOpen = !mobileSidebarOpen">
        <span v-if="!mobileSidebarOpen">☰</span>
        <span v-else>✕</span>
      </div>

      <!-- 右侧主内容 -->
      <main class="content">


        <!-- 右侧Tab切换 -->
        <div class="content-tabs">
          <span
            class="content-tab"
            :class="{ active: activeTab === 'chart' }"
            @click="activeTab = 'chart'"
          >图表</span>
          <span
            class="content-tab"
            :class="{ active: activeTab === 'data' }"
            @click="activeTab = 'data'"
          >行情数据</span>
          <span
            class="content-tab"
            :class="{ active: activeTab === 'trades' }"
            @click="activeTab = 'trades'"
          >交易记录</span>
          <span
            class="content-tab"
            :class="{ active: activeTab === 'strategy' }"
            @click="activeTab = 'strategy'"
          >策略</span>
          <span
            class="content-tab"
            :class="{ active: activeTab === 'api' }"
            @click="activeTab = 'api'"
          >API 参考</span>
          <span
            class="content-tab"
            :class="{ active: activeTab === 'ml' }"
            @click="activeTab = 'ml'"
          >ML 预测</span>
          <span
            class="content-tab"
            :class="{ active: activeTab === 'factor' }"
            @click="activeTab = 'factor'"
          >因子模型</span>
        </div>

        <!-- Tab: 图表 -->
        <template v-if="activeTab === 'chart'">
          <ChartTab
            ref="chartTabRef"
            :chart-data="chartData"
            :loading="loading"
            :selected-contract="selectedContract"
            :backtest-result="backtestResult"
            :frequency-label="frequencyLabel"
            :data-source-label="dataSourceLabel"
            :start-date="startDate"
            :end-date="endDate"
            :initial-capital="initialCapital"
            :commission-rate="commissionRate"
            :draw-threshold="drawThreshold"
          />
        </template>

        <!-- Tab: 策略 -->
        <template v-if="activeTab === 'strategy'">
          <StrategyTab
            v-model="strategyCode"
            :strategy-params="strategyParams"
            :selected-file="selectedStrategyFile"
            :running="running"
            :backtest-result="backtestResult"
            @update:strategy-params="strategyParams = $event"
            @update:selected-file="selectedStrategyFile = $event"
            @run-backtest="runBacktest"
            @reset="resetStrategy"
          />
        </template>

        <!-- Tab: API 参考 -->
        <template v-if="activeTab === 'api'">
          <ApiReference />
        </template>

        <!-- Tab: ML 预测 -->
        <template v-if="activeTab === 'ml'">
        <MLPrediction
          :chart-data="chartData"
          :contract="selectedContract"
          :freq-label="frequencyLabel"
          :backtest-result="backtestResult"
          @update:backtest-result="onMLBacktestResult"
        />
        </template>
        <!-- Tab: 因子模型 -->
        <template v-if="activeTab === 'factor'">
        <FactorModel
          :chart-data="chartData"
          :contract="selectedContract"
          :freq-label="frequencyLabel"
          @update:backtest-result="onMLBacktestResult"
        />
        </template>
        <template v-if="activeTab === 'data'">
          <DataTab :chart-data="chartData" />
        </template>

        <!-- Tab: 交易记录 -->
        <template v-if="activeTab === 'trades'">
          <TradesTab :backtest-result="backtestResult" />
        </template>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Message } from 'view-ui-plus'
import TopBar from './components/TopBar.vue'
import ChartTab from './components/ChartTab.vue'
import StrategyTab from './components/StrategyTab.vue'
import DataTab from './components/DataTab.vue'
import TradesTab from './components/TradesTab.vue'
import EditorView from './views/EditorView.vue'
import ApiReference from './components/ApiReference.vue'
import ContractPanel from './components/ContractPanel.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import MLPrediction from './components/MLPrediction.vue'
import FactorModel from './components/FactorModel.vue'

// ---- 编辑器切换 ----
const activeTab = ref('chart')
const showEditor = ref(false)
const mobileSidebarOpen = ref(false)
const contractPanelRef = ref()
const chartTabRef = ref<any>(null)
const updatingContracts = ref(false)

async function updateContracts() {
  updatingContracts.value = true
  try {
    const res = await fetch('/api/contracts/update', { method: 'POST' })
    const result = await res.json()
    if (result.success) {
      await contractPanelRef.value?.loadContracts()
      Message.success(result.message)
    } else {
      Message.error('更新失败: ' + result.message)
    }
  } catch {
    Message.error('更新合约失败')
  } finally {
    updatingContracts.value = false
  }
}

// ---- 参数 ----
const frequencies = [
  { value: '1d', label: '日线' },
  { value: '1h', label: '小时线' },
  { value: '30m', label: '30分钟' },
  { value: '15m', label: '15分钟' },
  { value: '10m', label: '10分钟' },
  { value: '5m', label: '5分钟' },
  { value: '1m', label: '1分钟' },
]
const dataSources = [
  { value: 'akshare', label: 'AKShare' },
  { value: 'tushare', label: 'Tushare' },
  { value: 'tqsdk', label: '天勤' },
]
const selectedContract = ref('ma2609')
const frequency = ref('15m')
const dataSource = ref('akshare')
const initialCapital = ref(100000)
const commissionRate = ref(0.0001)
const emaFast = ref(10)
const emaSlow = ref(40)
const drawThreshold = ref(5)  // 默认5（实际值，表示回撤50元）

// ---- 策略参数（统一对象，由StrategyTab管理）----
const strategyParams = ref<Record<string, any>>({
  rsi_len: 2, long_rsi: 10, short_rsi: 90,
  sl_atr: 2.0, tp_atr: 3.0, time_stop: 12,
  use_ema: true, ema_len: 200,
  adx_period: 14, adx_max: 25,
  vwap_dev: 0, atr_len: 14,
})
const selectedStrategyFile = ref('stable_reversion.py')

// ---- 满仓模式 ----
const useFullPosition = ref(true)    // 满仓模式：按可用资金自动算手数（默认开启）
const maxRiskPct = ref(3)            // 满仓下单笔最大亏损%

const frequencyLabel = computed(() => frequencies.find(f => f.value === frequency.value)?.label || '')
const dataSourceLabel = computed(() => dataSources.find(f => f.value === dataSource.value)?.label || '')

function todayDate() {
  return new Date()
}
function defaultStartDate() {
  const now = new Date()
  // 默认从4月1日开始
  return new Date(now.getFullYear(), 3, 1)
}
const startDate = ref(defaultStartDate())
const endDate = ref(todayDate())
const loading = ref(false)
const running = ref(false)
const chartData = ref<any[]>([])

// ---- 策略 ----
const defaultStrategyCode = `# ========== 稳定均值回归（StableReversion）==========
# 综合 rsi2_revert + mean_revert + regime_adaptive 的最优基因
#
# 核心逻辑:
#   【市场过滤】ADX(14) < 25 → 只做震荡市
#   【方向过滤】收盘 > EMA(200) → 只做多；收盘 < EMA(200) → 只做空
#   【时机信号】RSI(2) < 10（超卖）/ > 90（超买）→ 均值回归入场
#   【风控出场】ATR(14) 2x止损 + 3x止盈 + 12K线时间止损
#
# 最优参数 (20组扫描，MA609 15m 2025-09~2026-07):
#   RSI<10/>90  ADX<25  SL=2.0xATR  TP=3.0xATR  无VWAP
#   MA609: +4,530 / 95笔 / 34.7%胜率 / 0.6%回撤 / 夏普0.66
# =================================================================

def init(context):
    context['rsi_len'] = context.get('rsi_len', 2)
    context['long_rsi'] = context.get('long_rsi', 10.0)
    context['short_rsi'] = context.get('short_rsi', 90.0)
    context['ema_len'] = context.get('ema_len', 200)
    context['adx_period'] = context.get('adx_period', 14)
    context['adx_max'] = context.get('adx_max', 25.0)
    context['atr_len'] = context.get('atr_len', 14)
    context['vwap_dev'] = context.get('vwap_dev', 0.0)
    context['sl_atr'] = context.get('sl_atr', 2.0)
    context['tp_atr'] = context.get('tp_atr', 3.0)
    context['time_stop'] = context.get('time_stop', 12)
    context['history'] = []
    context['stop'] = None
    context['take_profit'] = None
    context['entry_bar'] = None
    # ADX 内部状态
    context['tr_list'] = []
    context['pdm_list'] = []
    context['mdm_list'] = []
    context['dx_list'] = []
    context['adx_list'] = []
    # VWAP 内部状态
    context['sess_key'] = None
    context['cum_pv'] = 0.0
    context['cum_v'] = 0.0

# -------- helpers --------
def _atr(context):
    h = context['history']
    n = context['atr_len']
    if len(h) < n + 1:
        return None
    total = 0.0
    for k in range(len(h) - n, len(h)):
        cur = h[k]
        prev_close = h[k - 1]['close']
        tr = max(cur['high'] - cur['low'],
                 abs(cur['high'] - prev_close),
                 abs(cur['low'] - prev_close))
        total += tr
    return total / n

def _sess_key(timestr, prev_key):
    date = timestr[:10]
    hm = timestr[11:16]
    hour = int(hm[:2])
    if prev_key is None:
        return date + ('N' if hour >= 20 else 'D')
    prev_date = prev_key[:10]
    prev_tag = prev_key[10:]
    if hour >= 20:
        if prev_tag == 'D' and prev_date == date:
            return date + 'N'
        if prev_date != date:
            return date + 'N'
        return prev_key
    else:
        if prev_date != date:
            return date + 'D'
        return prev_key

def _update_adx(context):
    history = context['history']
    if len(history) < 2:
        return
    cur = history[-1]
    prev = history[-2]
    tr = max(cur['high'] - cur['low'],
             abs(cur['high'] - prev['close']),
             abs(cur['low'] - prev['close']))
    up_move = cur['high'] - prev['high']
    dn_move = prev['low'] - cur['low']
    pdm = up_move if (up_move > dn_move and up_move > 0) else 0.0
    mdm = dn_move if (dn_move > up_move and dn_move > 0) else 0.0
    context['tr_list'].append(tr)
    context['pdm_list'].append(pdm)
    context['mdm_list'].append(mdm)
    n = context['adx_period']
    if len(context['tr_list']) < n:
        return
    tr_s = pdm_s = mdm_s = 0.0
    for k in range(-n, 0):
        tr_s += context['tr_list'][k]
        pdm_s += context['pdm_list'][k]
        mdm_s += context['mdm_list'][k]
    if tr_s <= 0:
        return
    pdi = 100.0 * pdm_s / tr_s
    mdi = 100.0 * mdm_s / tr_s
    di_sum = pdi + mdi
    dx = 100.0 * abs(pdi - mdi) / di_sum if di_sum > 0 else 0.0
    context['dx_list'].append(dx)
    if len(context['dx_list']) < n:
        return
    dx_s = sum(context['dx_list'][-n:])
    adx = dx_s / n
    context['adx_list'].append(adx)

# -------- main --------
def handle_bar(context, bar):
    history = context['history']
    history.append(bar)
    i = len(history)
    _update_adx(context)
    c = bar['close']
    h_ = bar['high']
    l_ = bar['low']
    v = bar.get('volume', 0)
    tstr = bar.get('time', '')
    hm = tstr[11:16] if len(tstr) >= 16 else ''
    pos = context.get('position', 0)

    # ---- VWAP 累计 ----
    key = _sess_key(tstr, context['sess_key'])
    if key != context['sess_key']:
        context['sess_key'] = key
        context['cum_pv'] = 0.0
        context['cum_v'] = 0.0
    tp = (h_ + l_ + c) / 3.0
    context['cum_pv'] += tp * v
    context['cum_v'] += v
    vwap = context['cum_pv'] / context['cum_v'] if context['cum_v'] > 0 else c

    warmup = context['ema_len'] + context['atr_len'] + 20
    if i < warmup:
        return

    # ---- 指标 ----
    atr = _atr(context)
    if atr is None or atr <= 0:
        return
    closes = [b['close'] for b in history]
    rsi_val = rsi(closes, context['rsi_len'])[-1]
    ema_val = ema(closes, context['ema_len'])[-1]

    # ADX 震荡过滤
    if len(context['adx_list']) < 1:
        return
    adx_val = context['adx_list'][-1]
    if adx_val >= context['adx_max']:
        return

    # ---- 日内强平 ----
    force = (hm >= '14:55' and hm <= '15:05') or (hm >= '22:55' and hm <= '23:00')
    if pos != 0 and force:
        context['_action'] = 'sell' if pos > 0 else 'cover'
        context['_price'] = c
        context['_reason'] = '强平 %.1f' % c
        context['stop'] = None
        context['take_profit'] = None
        context['entry_bar'] = None
        return

    # ---- 持仓管理 ----
    if pos != 0 and context['stop'] is not None:
        hit = False
        if pos > 0:
            if l_ <= context['stop']:
                context['_action'] = 'sell'
                context['_price'] = context['stop']
                context['_reason'] = '多/止损 %.1f' % context['stop']
                hit = True
            elif h_ >= context['take_profit']:
                context['_action'] = 'sell'
                context['_price'] = context['take_profit']
                context['_reason'] = '多/止盈 %.1f' % context['take_profit']
                hit = True
        else:
            if h_ >= context['stop']:
                context['_action'] = 'cover'
                context['_price'] = context['stop']
                context['_reason'] = '空/止损 %.1f' % context['stop']
                hit = True
            elif l_ <= context['take_profit']:
                context['_action'] = 'cover'
                context['_price'] = context['take_profit']
                context['_reason'] = '空/止盈 %.1f' % context['take_profit']
                hit = True
        if not hit and context['entry_bar'] is not None:
            if i - context['entry_bar'] >= context['time_stop']:
                context['_action'] = 'sell' if pos > 0 else 'cover'
                context['_price'] = c
                context['_reason'] = '时间离场 %.1f' % c
                hit = True
        if hit:
            context['stop'] = None
            context['take_profit'] = None
            context['entry_bar'] = None
            return
        return

    # ---- 入场信号（三重确认）----
    long_dir = c > ema_val
    short_dir = c < ema_val
    dev = context['vwap_dev'] * atr
    if context['vwap_dev'] > 0:
        long_deviated = c < vwap - dev
        short_deviated = c > vwap + dev
    else:
        long_deviated = True
        short_deviated = True
    long_signal = (rsi_val < context['long_rsi'] and long_dir and long_deviated)
    short_signal = (rsi_val > context['short_rsi'] and short_dir and short_deviated)

    # 临近强平不开新仓
    if (hm >= '14:40' and hm <= '15:05') or (hm >= '22:40' and hm <= '23:00'):
        return

    if long_signal:
        context['_action'] = 'buy'
        context['_price'] = c
        context['stop'] = c - context['sl_atr'] * atr
        context['take_profit'] = c + context['tp_atr'] * atr
        context['entry_bar'] = i
        context['_reason'] = ('做多 %.1f RSI:%.0f ADX:%.0f V:%.1f 损:%.1f 盈:%.1f' %
                              (c, rsi_val, adx_val, vwap, context['stop'], context['take_profit']))
        return
    if short_signal:
        context['_action'] = 'short'
        context['_price'] = c
        context['stop'] = c + context['sl_atr'] * atr
        context['take_profit'] = c - context['tp_atr'] * atr
        context['entry_bar'] = i
        context['_reason'] = ('做空 %.1f RSI:%.0f ADX:%.0f V:%.1f 损:%.1f 盈:%.1f' %
                              (c, rsi_val, adx_val, vwap, context['stop'], context['take_profit']))
        return
`

const strategyCode = ref(defaultStrategyCode)
function resetStrategy() { strategyCode.value = defaultStrategyCode }

// ---- 回测结果 ----

function onMLBacktestResult(val: any) {
  backtestResult.value = val
}
const backtestResult = ref<{
  initialEquity: number; finalEquity: number; pnl: number; netPnl: number
  totalCommission: number; totalReturn: number; annualizedReturn: number
  winRate: number; tradeCount: number; maxDrawdown: number
  sharpeRatio: number; profitLossRatio: number
  equityCurve: { time: string; value: number }[]
  trades: { time: string; action: string; price: number; quantity: number; equity: number; pnl: number }[]
  channels?: any
} | null>(null)

// ---- 数据加载 ----
function localDateStr(d: any) {
  if (typeof d === 'string') return d.slice(0, 10)
  const y = d.getFullYear()
  const m = (d.getMonth() + 1).toString().padStart(2, '0')
  const day = d.getDate().toString().padStart(2, '0')
  return `${y}-${m}-${day}`
}

async function loadData() {
  const s = localDateStr(startDate.value)
  const e = localDateStr(endDate.value)
  if (!selectedContract.value || !s || !e) return Message.warning('请选择合约和时间段')
  backtestResult.value = null

  loading.value = true
  try {
    const res = await fetch(`/api/kline/${selectedContract.value}?frequency=${frequency.value}&start_date=${s}&end_date=${e}&source=${dataSource.value}`)
    if (!res.ok) throw new Error('Failed')
    chartData.value = await res.json()
  } catch {
    Message.error('加载数据失败')
  } finally {
    loading.value = false
  }
}

async function runBacktest() {
  if (chartData.value.length === 0) {
    Message.warning('请先加载数据')
    return
  }
  running.value = true
  try {
    const res = await fetch('/api/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contract_code: selectedContract.value,
        frequency: frequency.value,
        start_date: localDateStr(startDate.value),
        end_date: localDateStr(endDate.value),
        source: dataSource.value,
        strategy: strategyCode.value,
        initial_capital: initialCapital.value,
        commission: commissionRate.value,
        margin_ratio: 0.1,
        threshold: drawThreshold.value,
        ema_fast: emaFast.value,
        ema_slow: emaSlow.value,
        strategy_params: strategyParams.value,
        use_full_position: useFullPosition.value,
        max_risk_pct: maxRiskPct.value / 100,  // 前端填百分比，后端要小数
      }),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    const result = await res.json()
    backtestResult.value = result
    activeTab.value = 'chart'
    Message.success('回测完成')
  } catch (e: any) {
    Message.error('回测失败: ' + (e.message || '未知错误'))
  } finally {
    running.value = false
  }
}
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #app { height: 100%; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
body { background: #f0f2f5; color: #333; overflow: hidden; }
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.12); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: rgba(0,0,0,0.2); }
</style>
<style scoped>
.app-layout { display: flex; flex-direction: column; height: 100vh; background: #f0f2f5; }

/* ---- 主区域 ---- */
.main-area { display: flex; flex: 1; overflow: hidden; }

/* ---- 侧边栏 ---- */
/* ---- 移动端遮罩 ---- */
.sidebar-overlay {
  display: none;
  position: fixed; inset: 0; z-index: 99;
  background: rgba(0,0,0,0.35);
}

.sidebar {
  width: 300px; min-width: 300px; background: #fff; border-right: 1px solid #e8e8e8;
  display: flex; flex-direction: column; overflow-y: auto;
}
.sidebar-section { padding: 12px 14px; border-bottom: 1px solid #f0f0f0; }
.sidebar-section:last-child { border-bottom: none; }
.section-label { display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 600; color: #333; margin-bottom: 8px; }

/* ---- 右侧内容 ---- */
.content { flex: 1; display: flex; flex-direction: column; overflow-y: auto; padding: 12px 16px; background: #fff; overflow-x: hidden; position: relative; }

/* 内容区 Tab */
.content-tabs { display: flex; gap: 2px; margin-bottom: 12px; border-bottom: 1px solid #f0f0f0; }
.content-tab {
  padding: 6px 18px; font-size: 15px; cursor: pointer; color: #666;
  border-bottom: 2px solid transparent; margin-bottom: -1px; transition: all 0.2s;
}
.content-tab:hover { color: #1890ff; }
.content-tab.active { color: #1890ff; border-bottom-color: #1890ff; font-weight: 600; }

/* ---- 移动端浮动菜单按钮 ---- */
.mobile-menu-btn {
  display: none;
  position: fixed; bottom: 20px; left: 20px; z-index: 100;
  width: 44px; height: 44px; border-radius: 50%;
  background: #1890ff; color: #fff; font-size: 22px;
  align-items: center; justify-content: center;
  box-shadow: 0 2px 10px rgba(24,144,255,0.4);
  cursor: pointer; user-select: none;
}

/* ====================
   手机竖屏适配 (≤768px)
   ==================== */
@media (max-width: 768px) {
  .app-layout { height: 100dvh; overflow: hidden; }

  /* 侧边栏 → 从左侧滑入 */
  .sidebar {
    position: fixed; top: 0; left: 0; bottom: 0; z-index: 100;
    width: 85vw; max-width: 340px; min-width: unset;
    transform: translateX(-105%); transition: transform 0.3s ease;
  }
  .sidebar.open { transform: translateX(0); }
  .sidebar-overlay.open { display: block; }

  /* 主内容区全宽 */
  .main-area { flex-direction: column; -webkit-overflow-scrolling: touch; }
  .content { padding: 8px 10px; overflow-y: auto; -webkit-overflow-scrolling: touch; min-height: 0; }

  /* 内容Tab */
  .content-tab { font-size: 14px; padding: 4px 12px; }

  /* 浮动菜单按钮 */
  .mobile-menu-btn { display: flex; }
}
</style>
