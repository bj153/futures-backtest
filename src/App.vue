<template>
  <div class="app-layout">
    <!-- 顶栏 -->
    <header class="topbar">
      <div class="topbar-brand">
        <span class="brand-text">回测平台</span>
      </div>
      <div class="topbar-actions">
        <div class="live-clock">{{ nowStr }}</div>
        <Button size="small" :type="showEditor ? 'default' : 'text'" @click="showEditor = !showEditor">
          {{ showEditor ? '← 回测' : '项目文件' }}
        </Button>
        <Button size="small" type="primary" :loading="updatingContracts" @click="updateContracts">
          更新合约
        </Button>
      </div>
    </header>

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
          @draw-polyline="drawPolyline"
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
        <!-- 图表区域 -->
        <div class="chart-section">
          <StockChart ref="stockChartRef" v-if="chartData.length || loading" :data="chartData" :loading="loading" :title="selectedContract" :trades="backtestResult?.trades" :channels="backtestResult?.channels" />
          <div v-else class="empty-state">
            <div class="empty-icon">📈</div>
            <p>选择合约 → 加载数据 → 开始回测</p>
            <p class="empty-hint">支持日线、小时线、分钟线等周期</p>
          </div>
        </div>

        <!-- 指标卡片 + 收益曲线合并在一行 -->
        <div class="metric-bar" v-if="backtestResult">
          <span class="metric-info">{{ selectedContract?.toUpperCase() }} {{ frequencyLabel }} {{ dataSourceLabel }} {{ localDateStr(startDate) }} ~ {{ localDateStr(endDate) }} 资金{{ initialCapital }} 手续费{{ commissionRate }} 乘数100 阈值{{ drawThreshold }} {{ chartData.length }}条</span>
        </div>
        <div class="metric-bar" v-if="backtestResult">
          <span><b>总</b> <span :class="backtestResult.totalReturn >= 0 ? 'text-up' : 'text-down'">{{ backtestResult.totalReturn >= 0 ? '+' : '' }}{{ backtestResult.totalReturn.toFixed(2) }}%</span></span>
          <span class="metric-sep">年化 {{ (backtestResult.annualizedReturn || 0).toFixed(2) }}%</span>
          <span class="metric-sep">|</span>
          <span><b>胜</b> {{ backtestResult.winRate.toFixed(1) }}%</span>
          <span class="metric-sep">盈亏 {{ (backtestResult.profitLossRatio || 0).toFixed(2) }}</span>
          <span class="metric-sep">|</span>
          <span><b>夏普</b> {{ (backtestResult.sharpeRatio || 0).toFixed(2) }}</span>
          <span class="metric-sep">交易 {{ backtestResult.tradeCount }} 次</span>
          <span class="metric-sep">|</span>
          <span><b>回撤</b> <span class="text-down">-{{ backtestResult.maxDrawdown.toFixed(2) }}%</span></span>
          <span class="metric-sep">净 {{ backtestResult.pnl >= 0 ? '+' : '' }}{{ backtestResult.netPnl?.toFixed(0) }}</span>
        </div>
        <!-- 交易记录 -->
        <div class="equity-section" v-if="backtestResult?.equityCurve">
          <div class="section-label">收益曲线</div>
          <div class="equity-curve" ref="equityChartContainer"></div>
        </div>

        </template>

        <!-- Tab: 策略 -->
        <template v-if="activeTab === 'strategy'">
        <div class="strategy-fullscreen">
          <div class="strategy-fs-header">
            <div class="strategy-fs-title">
              <span>📝 策略编辑器</span>
              <span class="strategy-fs-hint">Python · 内置变量: close, high, low, volume, ema, rsi, atr, bb ...</span>
            </div>
            <div class="strategy-fs-actions">
              <Button size="small" type="success" :loading="running" @click="runBacktest">开始回测</Button>
              <Button size="small" type="default" @click="resetStrategy">重置</Button>
            </div>
          </div>
          <div class="strategy-fs-body">
            <StrategyEditor v-model="strategyCode" />
          </div>
        </div>
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
        <div class="table-tab-content" v-if="chartData.length">
          <div class="section-label">行情数据 ({{ chartData.length }}条)</div>
          <div class="table-scroll">
            <table class="mini-table">
              <thead>
                <tr><th>时间</th><th>开</th><th>高</th><th>低</th><th>收</th><th>成交量</th></tr>
              </thead>
              <tbody>
                <tr v-for="(d, i) in chartData.slice().reverse()" :key="i">
                  <td>{{ d.time?.slice(5, 16) }}</td>
                  <td>{{ d.open?.toFixed(2) }}</td>
                  <td>{{ d.high?.toFixed(2) }}</td>
                  <td>{{ d.low?.toFixed(2) }}</td>
                  <td :class="d.close >= d.open ? 'text-up' : 'text-down'">{{ d.close?.toFixed(2) }}</td>
                  <td>{{ d.volume?.toLocaleString() }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div v-else class="empty-state">
          <div class="empty-icon">📊</div>
          <p>先加载数据查看行情</p>
        </div>
        </template>

        <!-- Tab: 交易记录 -->
        <template v-if="activeTab === 'trades'">
        <div class="table-tab-content" v-if="backtestResult?.trades?.length">
          <div class="section-label">交易记录 ({{ backtestResult.trades.length }}笔)</div>
          <div class="table-scroll">
            <table class="mini-table">
              <thead>
                <tr><th>#</th><th>时间</th><th>操作</th><th>价格</th><th>数量</th><th>权益</th><th>盈亏</th></tr>
              </thead>
              <tbody>
                <tr v-for="(t, i) in backtestResult.trades.slice().reverse()" :key="i" :class="t.pnl >= 0 ? 'row-up' : 'row-down'">
                  <td class="td-num">{{ backtestResult.trades.length - i }}</td>
                  <td>{{ t.time?.slice(5, 16) }}</td>
                  <td><span class="trade-badge" :class="getActionClass(t.action)">{{ t.action }}</span></td>
                  <td>{{ t.price?.toFixed(2) }}</td>
                  <td>{{ t.quantity }}</td>
                  <td>{{ t.equity?.toFixed(2) }}</td>
                  <td :class="t.pnl >= 0 ? 'text-up' : 'text-down'">{{ t.pnl >= 0 ? '+' : '' }}{{ t.pnl?.toFixed(2) }}</td>
                </tr>
              </tbody>
              <tfoot>
                <tr class="row-total">
                  <td colspan="5">合计</td>
                  <td>{{ backtestResult.trades[backtestResult.trades.length - 1]?.equity?.toFixed(2) }}</td>
                  <td :class="totalTradesPnl >= 0 ? 'text-up' : 'text-down'">{{ totalTradesPnl >= 0 ? '+' : '' }}{{ totalTradesPnl?.toFixed(2) }}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
        <div v-else class="empty-state">
          <div class="empty-icon">📋</div>
          <p>先运行回测查看交易记录</p>
        </div>
        </template>
      </main>
    </div>
  </div>
  
  <!-- 删除模型确认弹窗 -->
<!-- 删除模型确认弹窗（已移至MLPrediction组件）-->
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { Button, Select, Option, DatePicker, InputNumber, Message, Modal } from 'view-ui-plus'
import Highcharts from 'highcharts/highstock.js'
import StockChart from './components/StockChart.vue'
import StrategyEditor from './components/StrategyEditor.vue'
import EditorView from './views/EditorView.vue'
import ApiReference from './components/ApiReference.vue'
import ContractPanel from './components/ContractPanel.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import MLPrediction from './components/MLPrediction.vue'
import FactorModel from './components/FactorModel.vue'

// ---- 时钟 ----
const nowStr = ref('')
let clockTimer: any = null
function updateClock() {
  nowStr.value = new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}
onMounted(() => { updateClock(); clockTimer = setInterval(updateClock, 1000) })
onUnmounted(() => clearInterval(clockTimer))

// ---- 编辑器切换 ----
const activeTab = ref('chart')
const showEditor = ref(false)
const mobileSidebarOpen = ref(false)
const contractPanelRef = ref()
const updatingContracts = ref(false)

// ---- 画线（基于回撤阈值识别顶点）----
const stockChartRef = ref<any>(null)

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
const drawThreshold = ref(5)  // 默认5（实际值，表示回撤50元）

function drawPolyline() {
  if (chartData.value.length < 10) {
    Message.warning('数据太少')
    return
  }
  stockChartRef.value?.clearDrawnLines()
  const vertices = detectVertices()
  if (vertices.length < 2) return

  // 生成折线数据
  const lineData = vertices.map(v => ({ time: v.time, price: Math.round(v.price * 100) / 100 }))
  // 最后顶点连到最后一根K线收盘价
  const bars = chartData.value
  const lastBar = bars[bars.length - 1]
  const lastV = vertices[vertices.length - 1]
  if (lastV.time !== lastBar.time) {
    lineData.push({ time: lastBar.time, price: Math.round(lastBar.close * 100) / 100 })
  }

  stockChartRef.value?.autoDrawPolyline(lineData)
  Message.success(`识别到 ${vertices.length} 个顶点, 阈值 ${drawThreshold.value}`)
}

function drawSegments() {
  if (chartData.value.length < 10) {
    Message.warning('数据太少')
    return
  }
  // 不清除折线，只增删波段标注
  stockChartRef.value?.clearSegments()
  const vertices = detectVertices()
  if (vertices.length < 2) return

  // 按波段分组：基于顶点高低点结构识别波段
  // 上升波段：低点→高点→低点，特征：一个高点比前一个高点高，一个低点比前一个低点高
  // 下降波段：高点→低点→高点，特征：一个高点比前一个高点低，一个低点比前一个低点低
  const segments: { time: string; price: number }[][] = []

  // 用高低点交替结构来分组
  // 因为顶点原本就是 high/low/high/low 交替的
  // 一个上升波段由 低→高→低 组成：v0(low)→v1(high)→v2(low)
  // 如果 v2(low) > v0(low) 且 v1(high) > 前一段的high，说明趋势延续
  // 把这样的连续段合并为一个波段
  
  let segStart = 0
  while (segStart < vertices.length - 2) {
    // 检查连续3个顶点是否为完整的波段结构
    const v0 = vertices[segStart]
    const v1 = vertices[segStart + 1]
    const v2 = vertices[segStart + 2]
    
    // 正常应该是 low→high→low 交替
    if (v0.type !== 'low' || v1.type !== 'high' || v2.type !== 'low') {
      // 如果模式不对，跳过
      segStart++
      continue
    }
    
    // 第1段低→高→低为上升波段候选
    // 收集波段：从 segStart 开始向后延展
    const seg: { time: string; price: number }[] = [
      { time: v0.time, price: Math.round(v0.price * 100) / 100 },
      { time: v1.time, price: Math.round(v1.price * 100) / 100 },
      { time: v2.time, price: Math.round(v2.price * 100) / 100 },
    ]
    
    // 记录当前波段已知的最高high和最低low
    let prevHigh = v1.price
    let prevLow = v0.price
    
    // 向后延展：每次加一个 high+low 对
    let k = segStart + 3
    while (k + 1 < vertices.length) {
      const nextHigh = vertices[k]
      const nextLow = vertices[k + 1]
      
      if (nextHigh.type !== 'high' || nextLow.type !== 'low') break
      
      // 上升波段要求：high越来越高，low也越来越高
      if (nextHigh.price < prevHigh || nextLow.price < prevLow) break
      
      seg.push(
        { time: nextHigh.time, price: Math.round(nextHigh.price * 100) / 100 },
        { time: nextLow.time, price: Math.round(nextLow.price * 100) / 100 },
      )
      prevHigh = nextHigh.price
      prevLow = nextLow.price
      k += 2
    }
    
    segments.push(seg)
    segStart = k - 1  // 从最后一个low开始找下降波段
  }
  
  // 同样逻辑找下降波段（高→低→高，特征：high越来越低, low越来越低）
  segStart = 0
  while (segStart < vertices.length - 2) {
    const v0 = vertices[segStart]
    const v1 = vertices[segStart + 1]
    const v2 = vertices[segStart + 2]
    
    if (v0.type !== 'high' || v1.type !== 'low' || v2.type !== 'high') {
      segStart++
      continue
    }
    
    const seg: { time: string; price: number }[] = [
      { time: v0.time, price: Math.round(v0.price * 100) / 100 },
      { time: v1.time, price: Math.round(v1.price * 100) / 100 },
      { time: v2.time, price: Math.round(v2.price * 100) / 100 },
    ]
    
    let prevHigh = v0.price
    let prevLow = v1.price
    
    let k = segStart + 3
    while (k + 1 < vertices.length) {
      const nextLow = vertices[k]
      const nextHigh = vertices[k + 1]
      
      if (nextLow.type !== 'low' || nextHigh.type !== 'high') break
      
      // 下降波段要求：low越来越低，high也越来越低
      if (nextLow.price > prevLow || nextHigh.price < prevHigh) break
      
      seg.push(
        { time: nextLow.time, price: Math.round(nextLow.price * 100) / 100 },
        { time: nextHigh.time, price: Math.round(nextHigh.price * 100) / 100 },
      )
      prevLow = nextLow.price
      prevHigh = nextHigh.price
      k += 2
    }
    
    segments.push(seg)
    segStart = k - 1
  }

  stockChartRef.value?.autoDrawSegments(segments)
  Message.success(`识别到 ${segments.length} 个波段, 阈值 ${drawThreshold.value}`)
}

function detectVertices() {
  const bars = chartData.value
  const times = bars.map((b: any) => b.time)
  const n = bars.length
  const threshold = drawThreshold.value
  
  const vertices: { time: string; price: number; type: 'high' | 'low' }[] = []
  
  let i = 0
  while (i < n) {
    if (vertices.length === 0) {
      vertices.push({ time: times[0], price: bars[0].close, type: 'low' })
      i = 1
      continue
    }
    
    const lastType = vertices[vertices.length - 1].type
    
    if (lastType === 'low') {
      var hIdx = i
      var hPrice = bars[i].high
      var hFound = false
      for (var hJ = i; hJ < n; hJ++) {
        if (bars[hJ].high > hPrice) {
          hPrice = bars[hJ].high
          hIdx = hJ
        }
        if ((hPrice - bars[hJ].close) >= threshold && hJ > hIdx) {
          vertices.push({ time: times[hIdx], price: hPrice, type: 'high' })
          i = hIdx + 1
          hFound = true
          break
        }
      }
      if (!hFound) break
    } else {
      var lIdx = i
      var lPrice = bars[i].low
      var lFound = false
      for (var lJ = i; lJ < n; lJ++) {
        if (bars[lJ].low < lPrice) {
          lPrice = bars[lJ].low
          lIdx = lJ
        }
        if ((bars[lJ].close - lPrice) >= threshold && lJ > lIdx) {
          vertices.push({ time: times[lIdx], price: lPrice, type: 'low' })
          i = lIdx + 1
          lFound = true
          break
        }
      }
      if (!lFound) break
    }
  }
  
  if (vertices.length < 2) {
    Message.warning('阈值过大，识别不到足够的顶点')
    return []
  }
  return vertices
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
} | null>(null)

const equityChartContainer = ref<HTMLElement | null>(null)
let equityChart: any = null

function renderEquityCurve() {
  if (!equityChartContainer.value || !backtestResult.value?.equityCurve) return
  if (equityChart) equityChart.destroy()
  const data = backtestResult.value.equityCurve.map(item => {
    const ts = typeof item.time === 'string' ? new Date(item.time.replace(' ', 'T')).getTime() : item.time
    return [ts, item.value]
  })
  equityChart = Highcharts.stockChart(equityChartContainer.value, {
    chart: { backgroundColor: 'transparent', height: 180, style: { fontFamily: 'inherit' } },
    rangeSelector: { enabled: false },
    title: { text: undefined },
    xAxis: { type: 'datetime', lineColor: '#333', labels: { style: { color: '#888' } },
      events: {
        afterSetExtremes: function(e: any) {
          if ((window as any).__chartSyncLock === 'equity') return
          ;(window as any).__chartSyncLock = 'equity'
          window.dispatchEvent(new CustomEvent('equity-extremes', { detail: { min: e.min, max: e.max } }))
          setTimeout(() => { (window as any).__chartSyncLock = '' }, 200)
        }
      }
    },
    yAxis: { title: undefined, gridLineColor: '#2a2a3e', labels: { style: { color: '#888' } } },
    series: [{ type: 'line', name: '权益', data, color: '#00d4ff', lineWidth: 1.5 }],
    credits: { enabled: false }, legend: { enabled: false },
    navigator: { enabled: false },
    scrollbar: { enabled: false },
  } as any)
  
  // 监听另一个图表的范围变化
  function onSync(e: any) {
    if (equityChart && e.detail) {
      equityChart.xAxis[0].setExtremes(e.detail.min, e.detail.max)
    }
  }
  window.addEventListener('chart-extremes', onSync)
}

watch(backtestResult, val => { if (val?.equityCurve) nextTick(renderEquityCurve) }, { deep: true })

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


async function runMLBacktest() {
  if (chartData.value.length === 0) {
    mlError.value = '请先加载K线数据'
    return
  }
  if (!mlHasModel.value) {
    mlError.value = '没有已训练的模型，请先训练'
    return
  }
  mlBacktesting.value = true
  mlError.value = ''
  mlResult.value = null
  try {
    const body: any = {
      kline_data: chartData.value,
      threshold: mlThreshold.value,
      use_filter: mlUseFilter.value,
      contract: selectedContract.value,
    }
    // 如果选了模型，传给后端
    if (mlSelectedModel.value) {
      body.model_file = mlSelectedModel.value
    }
    const res = await fetch('/api/ml/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    const result = await res.json()
    mlResult.value = result
    
    // ML回测的交易记录同步到图表页
    if (result.trades && result.trades.length > 0) {
      backtestResult.value = {
        initialEquity: 10000,
        finalEquity: (10000 * (1 + (result.strategy_return || 0))),
        pnl: 10000 * (result.strategy_return || 0),
        netPnl: 10000 * (result.strategy_return || 0),
        totalCommission: 0,
        totalReturn: (result.strategy_return || 0) * 100,
        annualizedReturn: 0,
        winRate: (result.trades.filter((t: any) => t.pnl > 0).length / Math.max(result.trades.length, 1)) * 100,
        tradeCount: result.trades.length,
        maxDrawdown: (result.strategy_max_dd || 0) * 100,
        sharpeRatio: result.strategy_sharpe || 0,
        profitLossRatio: 0,
        equityCurve: result.equity_curve || [],
        trades: result.trades,
      }
    }
  } catch (e: any) {
    mlError.value = e.message || '回测失败'
  } finally {
    mlBacktesting.value = false
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
function copyTrades() {
  if (!backtestResult.value?.trades) return
  const headers = ['#', '时间', '操作', '价格', '数量', '权益', '盈亏']
  const rows = backtestResult.value.trades.map((t: any, i: number) =>
    [i + 1, t.time?.slice(0, 16), t.action, t.price?.toFixed(2), t.quantity, t.equity?.toFixed(2), t.pnl?.toFixed(2)])
  const text = [headers.join('\t'), ...rows.map(r => r.join('\t'))].join('\n')
  const ta = document.createElement('textarea')
  ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'
  document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta)
  Message.success('已复制')
}

function getActionClass(action: string) {
  if (['buy', '开多', '买开', '买平', 'cover'].includes(action)) return 'badge-buy'
  if (['sell', '开空', '卖开', '卖平', 'sell_short'].includes(action)) return 'badge-sell'
  return ''
}

const totalTradesPnl = computed(() => {
  if (!backtestResult.value?.trades) return 0
  return backtestResult.value.trades.reduce((sum: number, t: any) => sum + (t.pnl || 0), 0)
})
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

/* ---- 顶栏 ---- */
.topbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0 20px; height: 48px; background: #fff; border-bottom: 1px solid #e8e8e8;
  flex-shrink: 0; box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.topbar-brand { display: flex; align-items: center; gap: 8px; }
.brand-text { font-size: 16px; font-weight: 600; color: #1a1a2e; }
.brand-badge { font-size: 12px; padding: 1px 5px; border-radius: 3px; background: #e6f7ff; color: #1890ff; border: 1px solid #91d5ff; }
.topbar-actions { display: flex; align-items: center; gap: 10px; }
.live-clock { font-size: 14px; color: #999; font-variant-numeric: tabular-nums; font-family: monospace; }

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
.section-hint { font-size: 12px; color: #999; font-weight: normal; }

/* 合约搜索 */
.contract-search { margin-bottom: 8px; }
.search-input {
  width: 100%; padding: 5px 10px; font-size: 14px; border: 1px solid #d9d9d9; border-radius: 4px;
  background: #fff; color: #333; outline: none; transition: border-color 0.2s;
}
.search-input:focus { border-color: #1890ff; box-shadow: 0 0 0 2px rgba(24,144,255,0.1); }
.search-input::placeholder { color: #bbb; }

/* 分类标签 */
.contract-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
.tag {
  font-size: 13px; padding: 2px 8px; border-radius: 3px; cursor: pointer;
  background: #fafafa; color: #666; border: 1px solid #e8e8e8; transition: all 0.2s;
}
.tag:hover { border-color: #1890ff; color: #1890ff; }
.tag.active { background: #e6f7ff; border-color: #1890ff; color: #1890ff; }

/* 合约列表 */
.contract-list { max-height: 200px; overflow-y: auto; }
.contract-item {
  display: flex; align-items: center; gap: 8px; padding: 5px 8px; border-radius: 3px;
  cursor: pointer; transition: background 0.15s; font-size: 14px;
}
.contract-item:hover { background: #f5f5f5; }
.contract-item.active { background: #e6f7ff; }
.contract-code { font-family: monospace; font-weight: 600; color: #1890ff; min-width: 50px; font-size: 13px; }
.contract-name { color: #666; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }

/* 参数 */
.param-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
.param-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
.param-item { display: flex; flex-direction: column; gap: 3px; }
.param-item label { font-size: 13px; color: #666; }
.num-input {
  width: 100%; padding: 4px 8px; font-size: 14px; border: 1px solid #d9d9d9; border-radius: 4px;
  background: #fff; color: #333; outline: none; transition: border-color 0.2s;
}
.num-input:focus { border-color: #1890ff; box-shadow: 0 0 0 2px rgba(24,144,255,0.1); }

.action-buttons { display: flex; gap: 6px; margin-top: 4px; }

/* 策略区 */
.strategy-section { flex: 1; overflow: hidden; display: flex; flex-direction: column; }
.strategy-section :deep(.strategy-editor) { flex: 1; overflow: hidden; }
.strategy-section :deep(.cm-editor) { height: 180px !important; }
.strategy-section :deep(.cm-scroller) { background: #fafafa; }
.strategy-section :deep(.cm-gutters) { background: #f0f0f0; border-right-color: #e0e0e0; color: #999; }
.reset-link { color: #ff4d4f !important; font-size: 13px !important; padding: 2px 6px !important; }

/* ---- 右侧内容 ---- */
.content { flex: 1; display: flex; flex-direction: column; overflow-y: auto; padding: 12px 16px; background: #fff; overflow-x: hidden; position: relative; }

/* 状态栏 */
.status-bar { display: flex; gap: 16px; padding: 6px 0; border-bottom: 1px solid #f0f0f0; margin-bottom: 12px; font-size: 14px; }
.status-item { display: flex; align-items: center; gap: 5px; color: #888; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; }
.status-dot.active { background: #52c41a; }

/* 指标卡片 */
.metric-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 8px; }
.metric-card {
  background: #fafafa; border: 1px solid #f0f0f0; border-radius: 4px; padding: 8px 10px;
  transition: box-shadow 0.2s;
}
.metric-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.metric-label { font-size: 12px; color: #999; line-height: 1.2; }
.metric-value { font-size: 18px; font-weight: 700; font-variant-numeric: tabular-nums; color: #333; line-height: 1.3; }
.metric-value.up, .metric-card.up .metric-value { color: #cf1322; }
.metric-card.down .metric-value { color: #389e0d; }
.metric-card.warn .metric-value { color: #d48806; }
.metric-sub { font-size: 12px; color: #999; margin-top: 1px; line-height: 1.2; }

/* 图表 */
.chart-section { height: 750px; margin-bottom: 12px; border: 1px solid #f0f0f0; border-radius: 6px; flex-shrink: 0; }
.chart-section :deep(.stock-chart) { height: 100%; }
.chart-section :deep(.chart-container) { height: 100%; }

/* 空状态 */
.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 400px; color: #bbb; }
.empty-icon { font-size: 40px; margin-bottom: 10px; }
.empty-state p { margin: 3px 0; font-size: 15px; }
.empty-hint { font-size: 13px !important; color: #d9d9d9; }
.empty-mini { text-align: center; padding: 30px; color: #bbb; font-size: 14px; }

/* 指标独占一行 */
.metric-row .metric-cards { margin-bottom: 8px; }
.metric-row .equity-section { margin-bottom: 8px; }

/* 收益曲线 */
.equity-section { margin-bottom: 12px; }
.equity-curve { width: 100%; height: 200px; border: 1px solid #f0f0f0; border-radius: 6px; flex-shrink: 0; display: block; line-height: 0; font-size: 0; }

/* Tab 表格 */
.table-tab-content { display: flex; flex-direction: column; flex: 1; }
.table-tab-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.table-scroll { flex: 1; overflow-y: auto; max-height: calc(100vh - 260px); }

/* 迷你表格 */
.mini-table { width: 100%; font-size: 13px; border-collapse: collapse; }
.mini-table th { position: sticky; top: 0; background: #f5f5f5; color: #999; padding: 6px 8px; text-align: right; font-weight: 600; border-bottom: 2px solid #e8e8e8; z-index: 1; }
.mini-table td { padding: 4px 8px; text-align: right; color: #333; border-bottom: 1px solid #f0f0f0; }
.mini-table th:first-child, .mini-table td:first-child { text-align: left; }
.mini-table tbody tr:hover td { background: #f8f8ff; }
.mini-table tfoot td { background: #f0f5ff; border-top: 2px solid #d6e4ff; font-weight: 600; padding: 6px 8px; text-align: right; }
.mini-table tfoot td:first-child { text-align: left; }
.td-num { color: #ccc; font-size: 12px; }
.row-up td { background: #f6ffed; }
.row-down td { background: #fff2f0; }

/* 红涨绿跌 */
.text-up { color: #cf1322; font-weight: 600; }
.text-down { color: #389e0d; font-weight: 600; }

/* 指标文字条 */
.metric-bar {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; margin-bottom: 4px;
  font-size: 14px; color: #555;
  background: #fafafa; border: 1px solid #f0f0f0; border-radius: 4px;
  flex-wrap: wrap;
}
.metric-info { color: #888; font-size: 14px; }

/* 交易标签 */
.trade-badge { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 12px; font-weight: 500; }
.badge-buy { background: #fff2f0; color: #cf1322; border: 1px solid #ffccc7; }
.badge-sell { background: #f6ffed; color: #389e0d; border: 1px solid #b7eb8f; }

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

  /* 顶栏精简 */
  .topbar { padding: 0 12px; height: 44px; }
  .brand-text { font-size: 14px; }
  .brand-badge { display: none; }
  .live-clock { font-size: 12px; }
  .topbar-actions :deep(.ivu-btn) { font-size: 12px; padding: 0 8px; }

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

  /* 状态栏精简 */
  .status-bar { font-size: 12px; gap: 10px; padding: 4px 0; margin-bottom: 8px; }

  /* 指标卡片 2×2 */
  .metric-cards { grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 8px; }
  .metric-card { padding: 8px 10px; }
  .metric-value { font-size: 18px; }
  .metric-label { font-size: 12px; }
  .metric-sub { font-size: 11px; }

  /* 内容Tab */
  .content-tab { font-size: 14px; padding: 4px 12px; }

  /* 图表缩小 */
  .chart-section { height: 380px; margin-bottom: 8px; }
  .chart-section :deep(.chart-container) { height: 360px; }

  /* 收益曲线缩小 */
  .equity-curve { height: 300px; }

  /* 底部双栏 → 单列 */
  .bottom-panels { grid-template-columns: 1fr; gap: 6px; }
  .panel-half { padding: 8px 10px; }
  .trade-table-wrap, .data-section { margin-top: 16px; border-top: 1px solid #e8e8e8; padding-top: 12px; }
.data-section .table-scroll { max-height: 350px; }
.data-table-wrap { max-height: 180px; }

  /* 迷你表格字体缩小 */
  .mini-table { font-size: 12px; }
  .mini-table th, .mini-table td { padding: 3px 5px; }

  /* 策略全屏编辑器（手机） */
  .strategy-fs-body { min-height: 60vh; }
  .strategy-fs-body :deep(.cm-editor) { height: 60vh !important; }
  .strategy-fs-header { padding: 10px 12px; flex-wrap: wrap; gap: 6px; }
  .strategy-fs-title { font-size: 14px; }
  .strategy-fs-hint { display: none; }

  /* 浮动菜单按钮 */
  .mobile-menu-btn { display: flex; }

  /* 空状态 */
  .empty-state { height: 280px; }
  .empty-state p { font-size: 14px; }
}

/* 策略全屏编辑器 */
.strategy-fullscreen {
  display: flex; flex-direction: column;
  flex: 1;
  background: #fff;
}
.strategy-fs-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #e8e8e8;
  background: #fafafa;
  flex-shrink: 0;
}
.strategy-fs-title {
  display: flex; flex-direction: column; gap: 2px;
  font-weight: 600; font-size: 15px;
}
.strategy-fs-hint {
  font-weight: 400; font-size: 11px; color: #999;
}

/* 画线输入框行 */
.draw-line-row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  margin-top: 8px;
  flex-wrap: wrap;
}
.draw-label {
  font-size: 12px;
  color: #888;
  white-space: nowrap;
}
.strategy-fs-actions { display: flex; gap: 8px; align-items: center; }
.strategy-fs-body {
  height: 600px;
  overflow-y: auto;
  display: flex; flex-direction: column;
}
.strategy-fs-body :deep(.strategy-editor) { flex: 1; display: flex; flex-direction: column; }
.strategy-fs-body :deep(.cm-editor) { flex: 1; height: 100% !important; }
.strategy-fs-body :deep(.cm-scroller) { background: #1e1e1e; }
.strategy-fs-body :deep(.cm-gutters) { background: #282c34; border-right-color: #3e4451; color: #636d83; }

/* ---- ML 预测 ---- */
.ml-tab-content { padding: 16px; }
.ml-header { margin-bottom: 12px; }
.ml-hint { font-size: 13px; color: #666; margin-top: 4px; }
.ml-params { background: #fff; border-radius: 6px; padding: 12px 16px; margin-bottom: 12px; border: 1px solid #e8e8e8; }
.ml-param-row { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
.ml-param-item label { display: block; font-size: 12px; color: #666; margin-bottom: 3px; }
.ml-error { background: #fff1f0; border: 1px solid #ffccc7; color: #cf1322; padding: 8px 12px; border-radius: 4px; margin-bottom: 12px; font-size: 13px; }
.ml-result { }
.ml-cards { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.ml-card { background: #fff; border: 1px solid #e8e8e8; border-radius: 6px; padding: 10px 14px; min-width: 120px; flex: 1; }
.ml-card-label { font-size: 12px; color: #999; margin-bottom: 4px; }
.ml-card-value { font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
.ml-signals-section { margin-top: 8px; }
.ml-data-status { margin-bottom: 10px; }
.ml-data-warn { color: #fa8c16; font-size: 14px; font-weight: 500; }
.ml-data-ok { color: #52c41a; font-size: 13px; }
.ml-train-info { margin-top: 8px; font-size: 13px; color: #1890ff; }
.ml-train-hint { margin-top: 6px; font-size: 13px; color: #999; }
</style>