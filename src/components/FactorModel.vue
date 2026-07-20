<template>
  <div class="factor-tab-content">
    <div class="factor-scroll-wrap">
    <div class="factor-header">
      <div class="section-label">📊 多因子动态评分模型</div>
      <p class="factor-hint">
        7个独立因子分别回测 → 近10/20/30/50根K线滚动评分 → 动态分配权重 → Ensemble综合信号
      </p>
    </div>

    <!-- 数据状态 -->
    <div class="factor-data-status">
      <span v-if="chartData.length === 0" class="factor-data-warn">
        ⚠️ 请先在左侧选择合约和周期，点击「加载数据」
      </span>
      <span v-else class="factor-data-ok">
        ✅ 当前数据: {{ contract?.toUpperCase() }} | {{ freqLabel }} | {{ chartData.length }}条 K线
      </span>
    </div>

    <!-- 参数栏 -->
    <div class="factor-params">
      <div class="factor-param-row">
        <div class="factor-param-item">
          <label>模式</label>
          <Select v-model="factorMode" size="small" style="width:120px">
            <Option value="auto">🔄 自适应</Option>
            <Option value="trending">📈 趋势</Option>
            <Option value="ranging">📊 震荡</Option>
          </Select>
        </div>
        <div class="factor-param-item">
          <label>评分周期</label>
          <span class="param-value">10 / 20 / 30 / 50</span>
        </div>
        <div class="factor-param-item">
          <label>周期权重</label>
          <span class="param-value">0.40 / 0.30 / 0.20 / 0.10</span>
        </div>
        <div class="factor-param-item">
          <label>信号阈值</label>
          <Select v-model="factorThreshold" size="small" style="width:90px">
            <Option v-for="t in [0.05,0.10,0.15,0.20,0.25]" :key="t" :value="t">{{ t }}</Option>
          </Select>
        </div>
        <Button size="small" type="primary" :loading="factorLoading" @click="runFactorBacktest"
          :disabled="chartData.length === 0">
          🚀 运行因子回测
        </Button>
      </div>
    </div>

    <!-- 市场状态 -->
    <div v-if="marketRegime.regime" class="regime-bar" :class="'regime-' + marketRegime.regime">
      <span class="regime-icon">{{ marketRegime.regime === 'trending' ? '📈' : '📊' }}</span>
      <span class="regime-label">市场状态: <b>{{ marketRegime.regime === 'trending' ? '趋势行情' : '震荡行情' }}</b></span>
      <span class="regime-detail">ADX均值 {{ marketRegime.adx_avg }} | 最新 {{ marketRegime.adx_latest }}</span>
      <span class="regime-status">{{ factorMode === 'auto' ? '🔄 自适应模式' : factorMode === 'trending' ? '📈 强制趋势模式' : '📊 强制震荡模式' }}</span>
    </div>

    <!-- 错误提示 -->
    <div v-if="factorError" class="factor-error">{{ factorError }}</div>

    <!-- 因子评分表 -->
    <div v-if="factorResults.length > 0" class="factor-section">
      <div class="section-label">因子评分与权重</div>
      <div class="table-scroll" style="max-height:260px">
        <table class="factor-table">
          <thead>
            <tr>
              <th>因子</th>
              <th>近10收益</th>
              <th>近20收益</th>
              <th>近30收益</th>
              <th>近50收益</th>
              <th>动态评分</th>
              <th>权重</th>
              <th>信号数</th>
              <th>胜率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="f in factorResults" :key="f.factor_id" :class="factorRowClass(f)">
              <td>
                <span class="factor-badge" :style="{ background: factorColor(f.factor_id) + '22', color: factorColor(f.factor_id) }">
                  {{ f.factor_name }}
                </span>
              </td>
              <td :class="returnClass(f.returns['10'])">{{ (f.returns['10'] * 100).toFixed(2) }}%</td>
              <td :class="returnClass(f.returns['20'])">{{ (f.returns['20'] * 100).toFixed(2) }}%</td>
              <td :class="returnClass(f.returns['30'])">{{ (f.returns['30'] * 100).toFixed(2) }}%</td>
              <td :class="returnClass(f.returns['50'])">{{ (f.returns['50'] * 100).toFixed(2) }}%</td>
              <td :class="scoreClass(f.dynamic_score)">{{ (f.dynamic_score * 100).toFixed(2) }}</td>
              <td>
                <div class="weight-bar-container">
                  <div class="weight-bar" :style="{ width: (f.weight * 100) + '%', background: factorColor(f.factor_id) }"></div>
                </div>
                <span class="weight-text"> {{ (f.weight * 100).toFixed(1) }}%</span>
              </td>
              <td class="td-num">{{ f.signal_count }}</td>
              <td :class="returnClass(f.win_rate - 0.5)">{{ (f.win_rate * 100).toFixed(1) }}%</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Ensemble结果 -->
    <div v-if="ensembleResult" class="factor-section">
      <div class="section-label">Ensemble 综合回测</div>
      <div class="factor-cards">
        <div class="factor-card">
          <div class="factor-card-label">总收益</div>
          <div class="factor-card-value" :class="ensembleResult.total_return >= 0 ? 'text-up' : 'text-down'">
            {{ (ensembleResult.total_return * 100).toFixed(2) }}%
          </div>
        </div>
        <div class="factor-card">
          <div class="factor-card-label">夏普比率</div>
          <div class="factor-card-value" :class="ensembleResult.sharpe >= 1 ? 'text-up' : 'text-down'">
            {{ ensembleResult.sharpe.toFixed(2) }}
          </div>
        </div>
        <div class="factor-card">
          <div class="factor-card-label">最大回撤</div>
          <div class="factor-card-value text-down">{{ (ensembleResult.max_dd * 100).toFixed(2) }}%</div>
        </div>
        <div class="factor-card">
          <div class="factor-card-label">交易/信号</div>
          <div class="factor-card-value" style="font-size:16px">{{ ensembleResult.trade_count }} / {{ ensembleResult.signal_count }}</div>
        </div>
      </div>
    </div>

    <!-- 因子权益曲线对比 -->
    <div v-if="factorResults.length > 0" class="factor-section">
      <div class="section-label">因子收益对比（近50根K线）</div>
      <div class="factor-chart-container" ref="factorChartRef"></div>
    </div>

    <!-- 最新信号 -->
    <div v-if="lastSignals.length > 0" class="factor-section">
      <div class="section-label">最新 Ensemble 信号 (最近20条)</div>
      <div class="table-scroll" style="max-height:200px">
        <table class="mini-table">
          <thead><tr><th>时间</th><th>价格</th><th>信号</th><th>综合值</th></tr></thead>
          <tbody>
            <tr v-for="(s, i) in lastSignals" :key="i">
              <td>{{ s.time?.slice(5, 16) }}</td>
              <td>{{ s.price?.toFixed(1) }}</td>
              <td :class="s.signal === 'LONG' ? 'text-up' : s.signal === 'SHORT' ? 'text-down' : ''">
                {{ s.signal === 'LONG' ? '🟢多' : s.signal === 'SHORT' ? '🔴空' : '⚪—' }}
              </td>
              <td>{{ s.ensemble_value?.toFixed(3) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { Button, Select, Option } from 'view-ui-plus'

const props = defineProps<{
  chartData: any[]
  contract: string
  freqLabel: string
}>()

const emit = defineEmits<{
  'update:backtestResult': [value: any]
}>()

const factorThreshold = ref(0.15)
const factorMode = ref('auto')
const factorLoading = ref(false)
const factorError = ref('')
const factorResults = ref<any[]>([])
const ensembleResult = ref<any>(null)
const lastSignals = ref<any[]>([])
const marketRegime = ref<any>({})
const factorChartRef = ref<HTMLElement | null>(null)

const MODE_LABELS: Record<string, string> = {
  'auto': '自适应',
  'trending': '趋势',
  'ranging': '震荡',
}

const FACTOR_COLORS: Record<string, string> = {
  'ma_cross': '#1890ff',
  'rsi': '#52c41a',
  'macd': '#722ed1',
  'bb': '#fa8c16',
  'volume': '#eb2f96',
  'momentum': '#13c2c2',
  'ma_trend': '#f5222d',
}

function factorColor(id: string) {
  return FACTOR_COLORS[id] || '#666'
}

function returnClass(v: number) {
  if (!v) return ''
  return v > 0 ? 'text-up' : 'text-down'
}

function scoreClass(v: number) {
  if (v > 0.01) return 'text-up'
  if (v < -0.01) return 'text-down'
  return ''
}

function factorRowClass(f: any) {
  return f.weight > 0.3 ? 'row-top' : f.weight > 0.1 ? 'row-mid' : ''
}

async function runFactorBacktest() {
  if (props.chartData.length === 0) {
    factorError.value = '请先加载K线数据'
    return
  }
  factorLoading.value = true
  factorError.value = ''
  factorResults.value = []
  ensembleResult.value = null
  lastSignals.value = []

  try {
    const body = {
      kline_data: props.chartData,
      threshold: factorThreshold.value,
      mode: factorMode.value,
      factor_filter: [],
    }
    const res = await fetch('/api/factors/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    const result = await res.json()
    factorResults.value = result.factors || []
    ensembleResult.value = result.ensemble || null
    lastSignals.value = result.kline_signals?.slice(-20) || []
    marketRegime.value = result.regime || {}

    // 通知交易记录页
    if (result.ensemble) {
      emit('update:backtestResult', {
        initialEquity: 100000,
        finalEquity: 100000 * (1 + (result.ensemble.total_return || 0)),
        pnl: 100000 * (result.ensemble.total_return || 0),
        netPnl: 100000 * (result.ensemble.total_return || 0),
        totalCommission: 0,
        totalReturn: (result.ensemble.total_return || 0) * 100,
        annualizedReturn: 0,
        winRate: 0,
        tradeCount: result.ensemble.trade_count || 0,
        maxDrawdown: (result.ensemble.max_dd || 0) * 100,
        sharpeRatio: result.ensemble.sharpe || 0,
        profitLossRatio: 0,
        equityCurve: [],
        trades: [],
      })
    }

    await nextTick()
    renderFactorChart()
  } catch (e: any) {
    factorError.value = e.message || '因子回测失败'
  } finally {
    factorLoading.value = false
  }
}

function renderFactorChart() {
  if (!factorChartRef.value || factorResults.value.length === 0) return
  const container = factorChartRef.value
  const colors = ['#1890ff','#52c41a','#722ed1','#fa8c16','#eb2f96','#13c2c2','#f5222d']
  
  let html = '<div style="display:flex;flex-wrap:wrap;gap:6px;padding:8px 0">'
  factorResults.value.forEach((f: any, i: number) => {
    const ret50 = (f.returns['50'] || 0) * 100
    const ret30 = (f.returns['30'] || 0) * 100
    const ret20 = (f.returns['20'] || 0) * 100
    const ret10 = (f.returns['10'] || 0) * 100
    const score = (f.dynamic_score || 0) * 100
    const color = colors[i % colors.length]
    html += `
      <div style="flex:1;min-width:140px;background:#fafafa;border-radius:6px;padding:8px 10px;border-left:3px solid ${color}">
        <div style="font-size:12px;font-weight:600;color:${color}">${f.factor_name}</div>
        <div style="font-size:11px;color:#999;margin:2px 0">评分 <b style="color:${score>=0?'#cf1322':'#389e0d'}">${score.toFixed(2)}</b> · 权重 ${(f.weight*100).toFixed(1)}%</div>
        <div style="display:flex;gap:4px;font-size:10px;color:#666;flex-wrap:wrap">
          <span>10: <b style="color:${ret10>=0?'#cf1322':'#389e0d'}">${ret10.toFixed(1)}%</b></span>
          <span>20: <b style="color:${ret20>=0?'#cf1322':'#389e0d'}">${ret20.toFixed(1)}%</b></span>
          <span>30: <b style="color:${ret30>=0?'#cf1322':'#389e0d'}">${ret30.toFixed(1)}%</b></span>
          <span>50: <b style="color:${ret50>=0?'#cf1322':'#389e0d'}">${ret50.toFixed(1)}%</b></span>
        </div>
      </div>
    `
  })
  html += '</div>'
  container.innerHTML = html
}
</script>

<style scoped>
.factor-tab-content { padding: 16px; }
@media (max-width: 768px) {
  .factor-tab-content { padding: 8px; display: flex; flex-direction: column; min-height: 0; flex: 1; overflow: hidden; }
  .factor-scroll-wrap { flex: 1; overflow-y: auto; -webkit-overflow-scrolling: touch; }
  .factor-chart-container { min-height: 120px; }
  .factor-section { padding: 8px 10px; }
  .table-scroll { max-height: 180px !important; }
}
.factor-header { margin-bottom: 12px; }
.factor-hint { font-size: 12px; color: #888; margin-top: 4px; }
.factor-data-status { margin-bottom: 10px; }
.factor-data-warn { color: #fa8c16; font-size: 14px; font-weight: 500; }
.factor-data-ok { color: #52c41a; font-size: 13px; }
.factor-params { background: #fff; border-radius: 6px; padding: 12px 16px; margin-bottom: 12px; border: 1px solid #e8e8e8; }
.factor-param-row { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
.factor-param-item label { display: block; font-size: 12px; color: #666; margin-bottom: 3px; }
.param-value { font-size: 13px; color: #333; font-weight: 500; }
.factor-error { background: #fff1f0; border: 1px solid #ffccc7; color: #cf1322; padding: 8px 12px; border-radius: 4px; margin-bottom: 12px; font-size: 13px; }
.factor-section { background: #fff; border-radius: 6px; padding: 12px 16px; margin-bottom: 12px; border: 1px solid #e8e8e8; }
.factor-cards { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.factor-card { background: #fff; border: 1px solid #e8e8e8; border-radius: 6px; padding: 10px 14px; min-width: 120px; flex: 1; }
.factor-card-label { font-size: 12px; color: #999; margin-bottom: 4px; }
.factor-card-value { font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
.factor-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.factor-table th, .factor-table td { padding: 6px 6px; text-align: right; border-bottom: 1px solid #f0f0f0; white-space: nowrap; }
.factor-table th { position: sticky; top: 0; background: #f5f5f5; color: #999; font-weight: 600; border-bottom: 2px solid #e8e8e8; z-index: 1; }
.factor-table th:first-child, .factor-table td:first-child { text-align: left; }
.factor-badge { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 11px; font-weight: 600; }
.weight-bar-container { display: inline-block; width: 50px; height: 6px; background: #f0f0f0; border-radius: 3px; vertical-align: middle; }
.weight-bar { height: 6px; border-radius: 3px; transition: width 0.3s; }
.weight-text { font-size: 11px; color: #666; vertical-align: middle; }
.factor-chart-container { min-height: 80px; }
.table-scroll { flex: 1; overflow-y: auto; }
.mini-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.mini-table th, .mini-table td { padding: 4px 8px; text-align: right; border-bottom: 1px solid #f0f0f0; white-space: nowrap; }
.mini-table th { position: sticky; top: 0; background: #f5f5f5; color: #999; font-weight: 600; border-bottom: 2px solid #e8e8e8; z-index: 1; }
.td-num { color: #999; font-size: 12px; }
.text-up { color: #cf1322; font-weight: 600; }
.text-down { color: #389e0d; font-weight: 600; }
.row-top td { background: #fff7e6; }
.row-mid td { background: #f0f5ff; }
.regime-bar {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 14px; border-radius: 6px; margin-bottom: 12px;
  font-size: 13px; flex-wrap: wrap;
}
.regime-trending { background: #fff7e6; border: 1px solid #ffd591; color: #d46b08; }
.regime-ranging { background: #e6f7ff; border: 1px solid #91d5ff; color: #096dd9; }
.regime-icon { font-size: 18px; }
.regime-label b { font-weight: 600; }
.regime-detail { color: #999; font-size: 12px; }
.regime-status { margin-left: auto; font-size: 12px; opacity: 0.8; }
.section-label { font-size: 14px; font-weight: 600; color: #333; margin-bottom: 8px; }
</style>
