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
          :ema-fast="emaFast"
          :ema-slow="emaSlow"
          :loading="loading"
          :running="running"
          @update:frequency="frequency = $event"
          @update:data-source="dataSource = $event"
          @update:start-date="startDate = $event"
          @update:end-date="endDate = $event"
          @update:initial-capital="initialCapital = $event"
          @update:commission-rate="commissionRate = $event"
          @update:draw-threshold="drawThreshold = $event"
          @update:ema-fast="emaFast = $event"
          @update:ema-slow="emaSlow = $event"
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
            :running="running"
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
const defaultStrategyCode = `# ========== EM双子星 ==========
# 顶点折线 + EMA趋势过滤，只顺着大方向开仓。
# 配置 context['ema_fast'] 和 context['ema_slow'] 调整均线周期。
#
# init(context): 初始化
# handle_bar(context, bar_dict): 每根K线执行一次
# 下单: context['_action']='buy|sell|short|cover'
#       context['_price']=价格  context['_reason']='理由'
# 内置函数: sma, ema, rsi, calc_verts

def init(context):
    context['history'] = []
    # EMA参数（可在前端params中配置）
    context['ema_fast'] = context.get('ema_fast', 10)
    context['ema_slow'] = context.get('ema_slow', 40)

def handle_bar(context, bar_dict):
    history = context['history']
    history.append(bar_dict)
    
    closes = [b['close'] for b in history]
    if len(closes) < context['ema_slow'] + 5:
        return
    
    # ====== 计算EMA趋势 ======
    fast_period = context['ema_fast']
    slow_period = context['ema_slow']
    ema_f = ema(closes, fast_period)[-1]
    ema_s = ema(closes, slow_period)[-1]
    trend_up = ema_f > ema_s      # 快线在上 = 多头趋势
    trend_down = ema_f < ema_s    # 快线在下 = 空头趋势
    
    # ====== 顶点计算 ======
    highs = [b['high'] for b in history]
    lows = [b['low'] for b in history]
    verts = calc_verts(highs, lows, closes, context['threshold'])
    
    pos = context.get('position', 0)
    stop_price = context.get('stop_price')
    c = bar_dict['close']
    h = bar_dict['high']
    l = bar_dict['low']
    
    # ====== 止损检查 ======
    if pos > 0 and stop_price is not None:
        if l <= stop_price or c < stop_price - 1:
            context['_action'] = 'sell'
            context['_price'] = min(stop_price, c)
            context['_reason'] = '止损平多 止损价' + str(round(stop_price)) + ' 最低' + str(round(l))
            context['stop_price'] = None
            context['entry_vertex'] = None
            return
    elif pos < 0 and stop_price is not None:
        if h >= stop_price or c > stop_price + 1:
            context['_action'] = 'cover'
            context['_price'] = max(stop_price, c)
            context['_reason'] = '止损平空 止损价' + str(round(stop_price)) + ' 最高' + str(round(h))
            context['stop_price'] = None
            context['entry_vertex'] = None
            return
    
    # ====== 顶点形态判断 ======
    if len(verts) < 4:
        return
    
    v3 = verts[-1]
    v2 = verts[-2]
    v1 = verts[-3]
    v0 = verts[-4]
    
    is_up = c > v3['price'] and v3['price'] > v1['price'] and v2['price'] > v0['price']
    is_down = c < v3['price'] and v3['price'] < v1['price'] and v2['price'] < v0['price']
    
    # 只顺着EMA趋势方向开仓
    if is_up and trend_up:
        if pos < 0:
            # 平空开多
            context['_action'] = 'flip_long'
            context['_price'] = c
            context['_reason'] = 'EM上行+顶点突破开多 ' + str(round(c)) + ' ema' + str(round(ema_f,1)) + '/' + str(round(ema_s,1))
            context['stop_price'] = v0['price']
        elif pos == 0:
            context['_action'] = 'buy'
            context['_price'] = c
            context['_reason'] = 'EM上行+顶点突破开多 ' + str(round(c)) + ' ema' + str(round(ema_f,1)) + '/' + str(round(ema_s,1))
            context['stop_price'] = v0['price']
        elif pos > 0:
            # 已持多仓，更新止损到最新顶点（移动止损）
            if v0['price'] > stop_price:
                context['stop_price'] = v0['price']
    elif is_down and trend_down:
        if pos > 0:
            context['_action'] = 'flip_short'
            context['_price'] = c
            context['_reason'] = 'EM下行+顶点突破开空 ' + str(round(c)) + ' ema' + str(round(ema_f,1)) + '/' + str(round(ema_s,1))
            context['stop_price'] = v0['price']
        elif pos == 0:
            context['_action'] = 'short'
            context['_price'] = c
            context['_reason'] = 'EM下行+顶点突破开空 ' + str(round(c)) + ' ema' + str(round(ema_f,1)) + '/' + str(round(ema_s,1))
            context['stop_price'] = v0['price']
        elif pos < 0:
            if v0['price'] < stop_price:
                context['stop_price'] = v0['price']
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
  // 清空旧数据
  chartData.value = []
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
        multiplier: 100,
        threshold: drawThreshold.value,
        ema_fast: emaFast.value,
        ema_slow: emaSlow.value,
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
