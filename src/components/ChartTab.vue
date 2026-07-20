<template>
  <div>
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
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted } from 'vue'
import { Message } from 'view-ui-plus'
import Highcharts from 'highcharts/highstock.js'
import StockChart from './StockChart.vue'

const props = defineProps<{
  chartData: any[]
  loading: boolean
  selectedContract: string
  backtestResult: any
  frequencyLabel: string
  dataSourceLabel: string
  startDate: Date | string
  endDate: Date | string
  initialCapital: number
  commissionRate: number
  drawThreshold: number
}>()

function localDateStr(d: any) {
  if (typeof d === 'string') return d.slice(0, 10)
  const y = d.getFullYear()
  const m = (d.getMonth() + 1).toString().padStart(2, '0')
  const day = d.getDate().toString().padStart(2, '0')
  return `${y}-${m}-${day}`
}

// ---- 画线（基于回撤阈值识别顶点）----
const stockChartRef = ref<any>(null)

function drawPolyline() {
  if (props.chartData.length < 10) {
    Message.warning('数据太少')
    return
  }
  stockChartRef.value?.clearDrawnLines()
  const vertices = detectVertices()
  if (vertices.length < 2) return

  // 生成折线数据
  const lineData = vertices.map(v => ({ time: v.time, price: Math.round(v.price * 100) / 100 }))
  // 最后顶点连到最后一根K线收盘价
  const bars = props.chartData
  const lastBar = bars[bars.length - 1]
  const lastV = vertices[vertices.length - 1]!
  if (lastV.time !== lastBar.time) {
    lineData.push({ time: lastBar.time, price: Math.round(lastBar.close * 100) / 100 })
  }

  stockChartRef.value?.autoDrawPolyline(lineData)
  Message.success(`识别到 ${vertices.length} 个顶点, 阈值 ${props.drawThreshold}`)
}

function detectVertices() {
  const bars = props.chartData
  const times = bars.map((b: any) => b.time)
  const n = bars.length
  const threshold = props.drawThreshold

  const vertices: { time: string; price: number; type: 'high' | 'low' }[] = []

  let i = 0
  while (i < n) {
    if (vertices.length === 0) {
      vertices.push({ time: times[0], price: bars[0].close, type: 'low' })
      i = 1
      continue
    }

    const lastType = vertices[vertices.length - 1]!.type

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

defineExpose({ drawPolyline })

// ---- 收益曲线 ----
const equityChartContainer = ref<HTMLElement | null>(null)
let equityChart: any = null

function renderEquityCurve() {
  if (!equityChartContainer.value || !props.backtestResult?.equityCurve) return
  if (equityChart) equityChart.destroy()
  const data = props.backtestResult.equityCurve.map((item: any) => {
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

watch(() => props.backtestResult, val => { if (val?.equityCurve) nextTick(renderEquityCurve) }, { deep: true })

// 组件挂载时若已有回测结果（例如从策略 Tab 回测完成后切回图表 Tab），立即渲染收益曲线
onMounted(() => {
  if (props.backtestResult?.equityCurve) nextTick(renderEquityCurve)
})
</script>

<style scoped>
/* 图表 */
.chart-section { height: 750px; margin-bottom: 12px; border: 1px solid #f0f0f0; border-radius: 6px; flex-shrink: 0; }
.chart-section :deep(.stock-chart) { height: 100%; }
.chart-section :deep(.chart-container) { height: 100%; }

/* 空状态 */
.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 400px; color: #bbb; }
.empty-icon { font-size: 40px; margin-bottom: 10px; }
.empty-state p { margin: 3px 0; font-size: 15px; }
.empty-hint { font-size: 13px !important; color: #d9d9d9; }

/* 收益曲线 */
.equity-section { margin-bottom: 12px; }
.equity-curve { width: 100%; height: 200px; border: 1px solid #f0f0f0; border-radius: 6px; flex-shrink: 0; display: block; line-height: 0; font-size: 0; }

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

.section-label { display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 600; color: #333; margin-bottom: 8px; }

@media (max-width: 768px) {
  /* 图表缩小 */
  .chart-section { height: 380px; margin-bottom: 8px; }
  .chart-section :deep(.chart-container) { height: 360px; }

  /* 收益曲线缩小 */
  .equity-curve { height: 300px; }

  /* 空状态 */
  .empty-state { height: 280px; }
  .empty-state p { font-size: 14px; }
}
</style>
