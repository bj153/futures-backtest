<template>
  <div class="stock-chart">
    <div v-if="loading" class="loading">
      <div class="spinner"></div>
      <span>加载行情数据中...</span>
    </div>
    <div v-else-if="!data || data.length === 0" class="empty">
      <span>📊 请选择合约和时间段，点击"加载行情数据"</span>
    </div>
    <div v-else ref="chartContainer" class="chart-container"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import Highcharts from 'highcharts/highstock.js'

// 设置语言和时区
Highcharts.setOptions({
  lang: {
    decimalPoint: '.',
    thousandsSep: ','
  },
  time: {
    timezone: 'Asia/Shanghai',
    useUTC: false
  },
  accessibility: {
    enabled: false
  }
} as any)

const props = defineProps<{
  data: any[]
  loading: boolean
  title?: string
  trades?: any[]
  channels?: any[] | {
    upper: { time1: string; price1: number; time2: string; price2: number }
    lower: { time1: string; price1: number; time2: string; price2: number }
  } | null
}>()

const chartContainer = ref<HTMLElement | null>(null)
let chart: Highcharts.StockChart | null = null
function toTs(time: string) {
  return new Date(time.replace(' ', 'T')).getTime()
}

// 画折线图（由父组件调用，连接所有顶点）
function autoDrawPolyline(vertices: { time: string; price: number }[]) {
  if (!chart || vertices.length < 2) return
  clearDrawnLines()

  const data = vertices.map(v => [toTs(v.time), v.price])

  chart.addSeries({
    type: 'line',
    name: `顶点折线 ${Date.now()}`,
    data: data,
    color: '#2196f3',
    lineWidth: 2,
    marker: {
      enabled: true,
      radius: 5,
      fillColor: '#2196f3',
      lineColor: '#fff',
      lineWidth: 2,
      symbol: 'circle'
    },
    enableMouseTracking: true,
    showInLegend: false,
    zIndex: 5,
    dataLabels: {
      enabled: true,
      formatter: function(this: any) {
        // 使用 this.point.index 或按序列
        const idx = this.point && this.point.index != null ? this.point.index : 0
        return (idx + 1).toString()
      },
      style: {
        color: '#2196f3',
        fontWeight: 'bold',
        fontSize: '11px',
        textOutline: '2px #fff'
      },
      y: -12,
      allowOverlap: true
    }
  })
}

// 画波段：用竖线分割区域，不同颜色标注
function autoDrawSegments(segments: { time: string; price: number }[][]) {
  if (!chart || segments.length < 1) return
  clearSegments()

  const bandColors = ['#ff5722', '#4caf50', '#2196f3', '#ff9800', '#9c27b0', '#00bcd4', '#e91e63', '#3f51b5']
  const yAxis = chart.yAxis[0] as any
  const yMin = yAxis.dataMin ?? yAxis.min ?? 0
  const yMax = yAxis.dataMax ?? yAxis.max ?? 1
  if (yMin >= yMax) return
  
  // 收集所有竖线数据，每个波段一对竖线
  const seriesList: any[] = []
  
  for (let s = 0; s < segments.length; s++) {
    const seg = segments[s]!
    if (seg.length < 1) continue
    const color = bandColors[s % bandColors.length]
    const startTime = toTs(seg[0]!.time)
    const last = seg[seg.length - 1]!
    const endTime = toTs(last.time)
    
    // 第一段的起始竖线跳过（在最左边不好看）
    if (s > 0) {
      seriesList.push({
        type: 'line',
        name: `波段s ${Date.now()}`,
        data: [[startTime, yMin], [startTime, yMax]],
        color: color,
        lineWidth: 2,
        dashStyle: 'Dash' as any,
        marker: { enabled: false },
        enableMouseTracking: false,
        showInLegend: false,
        zIndex: 4
      })
    }
    
    // 结束竖线
    seriesList.push({
      type: 'line',
      name: `波段e ${Date.now()}`,
      data: [[endTime, yMin], [endTime, yMax]],
      color: color,
      lineWidth: 2,
      dashStyle: 'Dash' as any,
      marker: { enabled: false },
      enableMouseTracking: false,
      showInLegend: false,
      zIndex: 4
    })
  }
  
  // 批量添加，最后只重绘一次
  const redraw = false
  for (const s of seriesList) {
    chart.addSeries(s, false)
  }
  chart.redraw()
}

function clearDrawnLines() {
  if (!chart) return
  const toRemove: number[] = []
  for (let i = 0; i < chart.series.length; i++) {
    const name = chart.series[i]!.name || ''
    if (name.startsWith('顶点折线') || name.startsWith('波段')) {
      toRemove.push(i)
    }
  }
  for (let i = toRemove.length - 1; i >= 0; i--) {
    chart.series[toRemove[i]!]!.remove()
  }
}

function clearSegments() {
  if (!chart) return
  const toRemove: number[] = []
  for (let i = 0; i < chart.series.length; i++) {
    const name = chart.series[i]!.name || ''
    if (name.startsWith('波段')) {
      toRemove.push(i)
    }
  }
  for (let i = toRemove.length - 1; i >= 0; i--) {
    chart.series[toRemove[i]!]!.remove(false)
  }
  if (toRemove.length > 0) {
    chart.redraw()
  }
}

defineExpose({ autoDrawPolyline, autoDrawSegments, clearDrawnLines, clearSegments })

// 计算均价
function calculateMA(data: any[]): [number, number][] {
  return data.map(item => {
    let timestamp: number
    if (typeof item.time === 'string') {
      timestamp = new Date(item.time.replace(' ', 'T')).getTime()
    } else {
      timestamp = item.time
    }
    const ma = (item.high + item.low + item.close) / 3
    return [timestamp, ma]
  })
}

// 构建图表系列
function buildSeries(ohlcData: any[], volumeData: any[], props: any) {
  const series: any[] = [
    {
      type: 'candlestick',
      name: '行情',
      data: ohlcData,
      color: '#00aa00',
      upColor: '#ff4444',
      lineColor: '#00aa00',
      upLineColor: '#ff4444',
      dataGrouping: { enabled: false }
    },
    {
      type: 'column',
      name: '成交量',
      data: volumeData,
      yAxis: 1,
      dataGrouping: { enabled: false }
    },
    {
      type: 'scatter',
      name: '买开',
      data: buildTradeMarkers(props.trades || []).buyPoints,
      color: '#ff4444',
      marker: {
        symbol: 'triangle',
        radius: 8,
        fillColor: '#ff4444',
        lineColor: '#fff',
        lineWidth: 1
      },
      yAxis: 0,
      stickyTracking: false,
      enableMouseTracking: true,
      tooltip: {
        headerFormat: '',
        pointFormat: '<b>买开</b><br/>时间: {point.formattedTime}<br/>价格: {point.y:.2f}<br/>数量: {point.quantity}手'
      }
    },
    {
      type: 'scatter',
      name: '卖平',
      data: buildTradeMarkers(props.trades || []).sellPoints,
      color: '#00aa00',
      marker: {
        symbol: 'triangle-down',
        radius: 8,
        fillColor: '#00aa00',
        lineColor: '#fff',
        lineWidth: 1
      },
      yAxis: 0,
      stickyTracking: false,
      enableMouseTracking: true,
      tooltip: {
        headerFormat: '',
        pointFormat: '<b>卖平</b><br/>时间: {point.formattedTime}<br/>价格: {point.y:.2f}<br/>数量: {point.quantity}手<br/>盈亏: {point.pnl:+.0f}'
      }
    }
  ]

  // channels 趋势线（已取消蓝色折线）

  return series
}

function buildTradeMarkers(trades: any[]) {
  const buyPoints: any[] = []
  const sellPoints: any[] = []

  for (const t of trades) {
    if (!t.time || t.price == null) continue
    const timestamp = new Date(t.time.replace(' ', 'T')).getTime()
    const action = t.action || ''
    const quantity = t.quantity || 1
    const pnl = t.pnl || 0
    const formattedTime = t.time.length >= 16 ? t.time.slice(5, 16) : t.time
    const reason = t.reason || ''

    const isBuy = action === '买开' || action === '买平'
    if (isBuy) {
      buyPoints.push({ x: timestamp, y: t.price, action, quantity, pnl, reason, formattedTime })
    } else {
      sellPoints.push({ x: timestamp, y: t.price, action, quantity, pnl, reason, formattedTime })
    }
  }

  return { buyPoints, sellPoints }
}

function renderChart() {
  if (!chartContainer.value || !props.data || props.data.length === 0) return

  if (chart) {
    chart.destroy()
    chart = null
  }

  const ohlcData = props.data.map(item => {
    const ts = typeof item.time === 'string' ? new Date(item.time.replace(' ', 'T')).getTime() : item.time
    return [ts, item.open, item.high, item.low, item.close]
  })

  const volumeData = props.data.map(item => {
    const ts = typeof item.time === 'string' ? new Date(item.time.replace(' ', 'T')).getTime() : item.time
    return [ts, item.volume]
  })

  chart = Highcharts.stockChart(chartContainer.value, {
    chart: {
      backgroundColor: '#ffffff',
      style: { fontFamily: 'Arial, sans-serif' }
    },
    accessibility: { enabled: false },
    rangeSelector: {
      enabled: true,
      selected: 3,
      inputEnabled: false,
      buttons: [
        { type: 'day', count: 1, text: '1日' },
        { type: 'day', count: 5, text: '5日' },
        { type: 'month', count: 1, text: '1月' },
        { type: 'all', text: '全部' }
      ]
    },
    title: {
      text: props.title || '行情走势',
      style: { color: '#333', fontSize: '16px' }
    },
    xAxis: {
      type: 'datetime',
      labels: { format: '{value:%Y-%m-%d}', style: { color: '#666' } },
      events: {
        afterSetExtremes: function(e: any) {
          if ((window as any).__chartSyncLock === 'kline') return
          ;(window as any).__chartSyncLock = 'kline'
          window.dispatchEvent(new CustomEvent('chart-extremes', { detail: { min: e.min, max: e.max } }))
          setTimeout(() => { (window as any).__chartSyncLock = '' }, 200)
        }
      },
      dateTimeLabelFormats: {
        millisecond: '%m-%d', second: '%m-%d', minute: '%m-%d',
        hour: '%m-%d', day: '%Y-%m-%d', week: '%Y-%m-%d', month: '%Y-%m', year: '%Y'
      },
      lineColor: '#ddd', tickColor: '#ddd'
    },
    yAxis: [
      { height: '70%', gridLineColor: '#eee', labels: { enabled: false }, margin: 0, offset: 0 },
      { top: '70%', height: '30%', offset: 0, gridLineColor: '#eee', labels: { enabled: false } }
    ],
    tooltip: {
      backgroundColor: 'rgba(255, 255, 255, 0.95)',
      borderColor: '#058DC7',
      style: { color: '#333' },
      split: false,
      shared: true
    },
    plotOptions: {
      scatter: { },
      candlestick: {
        color: '#00aa00', upColor: '#ff4444', lineColor: '#00aa00', upLineColor: '#ff4444',
        pointPadding: 0.1, groupPadding: 0.1
      },
      column: { color: 'rgba(0, 212, 255, 0.5)', borderWidth: 0 }
    },
    series: buildSeries(ohlcData, volumeData, props),
    credits: { enabled: false },
    navigator: {
      enabled: true,
      maskFill: 'rgba(5, 141, 199, 0.1)',
      outlineColor: '#ddd',
      handles: { backgroundColor: '#058DC7', borderColor: '#058DC7' },
      series: { color: '#058DC7', lineWidth: 1 }
    },
    scrollbar: { enabled: false }
  })
}

watch(() => props.data, () => {
  nextTick(() => { renderChart() })
}, { deep: true })

watch(() => props.trades, () => {
  nextTick(() => { renderChart() })
}, { deep: true })

watch(() => props.channels, () => {
  nextTick(() => { renderChart() })
}, { deep: true })

onMounted(() => {
  if (props.data && props.data.length > 0) {
    renderChart()
  }
  // 监听收益曲线范围变化
  const syncFn = (e: any) => {
    if (chart && e.detail) {
      chart.xAxis[0]!.setExtremes(e.detail.min, e.detail.max)
    }
  }
  window.addEventListener('equity-extremes', syncFn)
  ;(window as any).__chartSyncCleanup = syncFn
})

onUnmounted(() => {
  if (chart) {
    chart.destroy()
    chart = null
  }
  const fn = (window as any).__chartSyncCleanup
  if (fn) {
    window.removeEventListener('equity-extremes', fn)
  }
})
</script>

<style scoped>
.stock-chart {
  width: 100%;
  height: 100%;
  display: block;
  line-height: 0;
  font-size: 0;
}

.chart-container {
  width: 100%;
  height: 100%;
  display: block;
  line-height: 0;
  font-size: 0;
}

.chart-container :deep(.highcharts-range-selector-buttons) {
  display: flex !important;
  flex-wrap: wrap;
}

.chart-container :deep(.highcharts-range-selector-group) {
  flex-wrap: wrap !important;
}

@media (max-width: 480px) {
  .chart-container {
    height: 250px !important;
  }
}

@media (max-width: 768px) {
  .stock-chart { min-height: unset; }
  .chart-container { min-height: unset; }
  .loading, .empty { height: 280px; font-size: 13px; }
  .loading .spinner { width: 28px; height: 28px; }
}

.loading,
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 750px;
  color: #aaa;
  gap: 15px;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid rgba(0, 212, 255, 0.2);
  border-top-color: #00d4ff;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
