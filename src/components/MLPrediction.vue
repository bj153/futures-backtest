<template>
  <div class="ml-tab-content">
    <div class="ml-header">
      <div class="section-label">🤖 LightGBM 交易信号预测</div>
      <p class="ml-hint">先加载 K线数据 → 训练模型（永久保存）→ 回测</p>
    </div>

    <!-- 数据状态 -->
    <div class="ml-data-status">
      <span v-if="chartData.length === 0" class="ml-data-warn">⚠️ 请先在左侧选择合约和周期，点击「加载数据」</span>
      <span v-else class="ml-data-ok">✅ 当前数据: {{ contract?.toUpperCase() }} | {{ freqLabel }} | {{ chartData.length }}条 K线</span>
    </div>

    <div class="ml-params">
      <div class="ml-param-row">
        <div class="ml-param-item" style="min-width:220px">
          <label>选择模型</label>
          <Select v-model="mlSelectedModel" size="small" clearable placeholder="自动选最新模型" style="width:100%">
            <Option v-for="m in mlModels" :key="m.model_file" :value="m.model_file">
              {{ m.model_file.replace('.pkl','') }} ({{ (m.accuracy * 100).toFixed(1) }}% / AUC {{ m.auc?.toFixed(3) }})
            </Option>
          </Select>
        </div>
        <div class="ml-param-item">
          <label>阈值</label>
          <Select v-model="mlThreshold" size="small" style="width:90px">
            <Option v-for="t in [0.55,0.58,0.60,0.62,0.65]" :key="t" :value="t">{{ t }}</Option>
          </Select>
        </div>
        <div class="ml-param-item">
          <label style="display:flex;align-items:center;gap:4px">
            <input type="checkbox" v-model="mlUseFilter" />
            动量过滤
          </label>
        </div>
        <Button size="small" type="primary" :loading="mlTraining" @click="runTrain" :disabled="chartData.length === 0">
          🆕 新建模型
        </Button>
        <Button size="small" type="warning" :loading="mlRetraining" @click="runRetrain" :disabled="chartData.length === 0 || !mlSelectedModel">
          🔄 重新训练
        </Button>
        <Button size="small" type="success" :loading="mlBacktesting" @click="runMLBacktest" :disabled="chartData.length === 0 || !mlHasModel">
          📊 回测
        </Button>
        <Button size="small" type="error" :loading="mlDeleting" @click="showDeleteConfirm" :disabled="!mlSelectedModel">
          🗑️ 删除
        </Button>
      </div>
      <div v-if="mlSelectedModel && mlModels.length > 0" class="ml-train-info">
        已选: {{ mlSelectedModel }}
        <template v-if="mlModels.find(m => m.model_file === mlSelectedModel)">
          | 准确率: {{ (mlModels.find(m => m.model_file === mlSelectedModel).accuracy * 100).toFixed(1) }}%
          | AUC: {{ mlModels.find(m => m.model_file === mlSelectedModel).auc?.toFixed(4) }}
        </template>
      </div>
      <div v-if="!mlHasModel && chartData.length > 0" class="ml-train-hint">
        💡 先点击「新建模型」训练一个模型
      </div>
    </div>

    <div v-if="mlError" class="ml-error">{{ mlError }}</div>

    <!-- 回测结果 -->
    <div v-if="mlResult" class="ml-result">
      <div class="ml-cards">
        <div class="ml-card">
          <div class="ml-card-label">最新信号</div>
          <div class="ml-card-value" :class="mlSignalClass">{{ mlResult.latest_signal === 'LONG' ? '🟢 做多' : mlResult.latest_signal === 'SHORT' ? '🔴 做空' : '⚪ 观望' }}</div>
        </div>
        <div class="ml-card">
          <div class="ml-card-label">当前价</div>
          <div class="ml-card-value">{{ mlResult.latest_price?.toFixed(1) }}</div>
        </div>
        <div class="ml-card">
          <div class="ml-card-label">信号数/总K线</div>
          <div class="ml-card-value" style="font-size:16px">{{ mlResult.signal_count }}/{{ mlResult.signal_samples || mlResult.total_samples }} (原始{{ mlResult.total_samples }}条)</div>
        </div>
        <div class="ml-card">
          <div class="ml-card-label">准确率</div>
          <div class="ml-card-value" :class="mlResult.accuracy >= 0.52 ? 'text-up' : 'text-down'">{{ (mlResult.accuracy * 100).toFixed(1) }}%</div>
        </div>
      </div>

      <div class="ml-cards">
        <div class="ml-card">
          <div class="ml-card-label">策略收益</div>
          <div class="ml-card-value" :class="mlResult.strategy_return >= 0 ? 'text-up' : 'text-down'">{{ (mlResult.strategy_return * 100).toFixed(2) }}%</div>
        </div>
        <div class="ml-card">
          <div class="ml-card-label">夏普比率</div>
          <div class="ml-card-value" :class="mlResult.strategy_sharpe >= 1 ? 'text-up' : 'text-down'">{{ mlResult.strategy_sharpe?.toFixed(2) }}</div>
        </div>
        <div class="ml-card">
          <div class="ml-card-label">做多基准</div>
          <div class="ml-card-value" :class="mlResult.benchmark_long >= 0 ? 'text-up' : 'text-down'">{{ (mlResult.benchmark_long * 100).toFixed(2) }}%</div>
        </div>
        <div class="ml-card">
          <div class="ml-card-label">做空基准</div>
          <div class="ml-card-value" :class="mlResult.benchmark_short >= 0 ? 'text-up' : 'text-down'">{{ (mlResult.benchmark_short * 100).toFixed(2) }}%</div>
        </div>
      </div>

      <div class="ml-cards">
        <div class="ml-card">
          <div class="ml-card-label">最大回撤</div>
          <div class="ml-card-value text-down">{{ (mlResult.strategy_max_dd * 100).toFixed(2) }}%</div>
        </div>
        <div class="ml-card">
          <div class="ml-card-label">AUC</div>
          <div class="ml-card-value" :class="mlResult.auc >= 0.53 ? 'text-up' : 'text-down'">{{ mlResult.auc?.toFixed(4) }}</div>
        </div>
      </div>

      <!-- 交易记录 -->
      <div class="ml-signals-section" v-if="mlResult.trades?.length">
        <div class="section-label" style="margin-top:16px">交易记录 ({{ mlResult.trades.length }}笔)</div>
        <div class="table-scroll" style="max-height:250px">
          <table class="mini-table">
            <thead><tr><th>#</th><th>时间</th><th>操作</th><th>价格</th><th>权益</th><th>盈亏</th></tr></thead>
            <tbody>
              <tr v-for="(t, i) in mlResult.trades.slice().reverse()" :key="i" :class="t.pnl >= 0 ? 'row-up' : 'row-down'">
                <td class="td-num">{{ mlResult.trades.length - (i as number) }}</td>
                <td>{{ t.time?.slice(5, 16) }}</td>
                <td><span class="trade-badge" :class="t.action.includes('买') ? 'badge-buy' : 'badge-sell'">{{ t.action }}</span></td>
                <td>{{ t.price?.toFixed(2) }}</td>
                <td>{{ t.equity?.toFixed(2) }}</td>
                <td :class="t.pnl >= 0 ? 'text-up' : 'text-down'">{{ t.pnl >= 0 ? '+' : '' }}{{ t.pnl?.toFixed(2) }}</td>
              </tr>
            </tbody>
            <tfoot>
              <tr class="row-total">
                <td colspan="4">合计</td>
                <td>{{ mlResult.trades[mlResult.trades.length - 1]?.equity?.toFixed(2) }}</td>
                <td :class="totalPnl >= 0 ? 'text-up' : 'text-down'">{{ totalPnl >= 0 ? '+' : '' }}{{ totalPnl?.toFixed(2) }}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      <!-- 信号列表 -->
      <div class="ml-signals-section" v-if="mlResult.signals?.length">
        <div class="section-label" style="margin-top:16px">最近信号 ({{ mlResult.signals?.length || 0 }}条)</div>
        <div class="table-scroll" style="max-height:250px">
          <table class="mini-table">
            <thead><tr><th>时间</th><th>价格</th><th>信号</th><th>置信度</th><th>概率</th></tr></thead>
            <tbody>
              <tr v-for="(s, i) in mlResult.signals?.slice().reverse()" :key="i">
                <td>{{ s.time?.slice(5, 16) }}</td>
                <td>{{ s.price?.toFixed(1) }}</td>
                <td :class="s.signal === 'LONG' ? 'text-up' : s.signal === 'SHORT' ? 'text-down' : ''">
                  {{ s.signal === 'LONG' ? '🟢多' : s.signal === 'SHORT' ? '🔴空' : '⚪—' }}
                </td>
                <td>{{ s.confidence?.toFixed(2) }}</td>
                <td>{{ (s.prob * 100).toFixed(1) }}%</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <!-- 删除模型确认弹窗 -->
  <Modal v-model="mlDeleteConfirmVisible" title="删除模型" :width="400" @on-ok="runDeleteModel">
    <p>确定要删除模型 <strong>{{ mlDeletingName }}</strong> 吗？</p>
    <p style="color:#999;font-size:13px;margin-top:8px">此操作不可恢复。</p>
  </Modal>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Button, Select, Option, InputNumber, Message, Modal } from 'view-ui-plus'

const props = defineProps<{
  chartData: any[]
  contract: string
  freqLabel: string
  backtestResult: any
}>()

const emit = defineEmits<{
  'update:backtestResult': [value: any]
}>()

const mlThreshold = ref(0.60)
const mlUseFilter = ref(true)
const mlTraining = ref(false)
const mlRetraining = ref(false)
const mlDeleting = ref(false)
const mlBacktesting = ref(false)
const mlResult = ref<any>(null)
const mlTrainResult = ref<any>(null)
const mlError = ref('')

const mlModels = ref<any[]>([])
const mlSelectedModel = ref('')

const mlHasModel = computed(() => mlModels.value.length > 0)

const totalPnl = computed(() => {
  if (!mlResult.value?.trades) return 0
  return mlResult.value.trades.reduce((sum: number, t: any) => sum + (t.pnl || 0), 0)
})

async function loadMLModels() {
  try {
    const res = await fetch('/api/ml/models')
    if (res.ok) {
      mlModels.value = await res.json()
      if (mlSelectedModel.value && !mlModels.value.find((m: any) => m.model_file === mlSelectedModel.value)) {
        mlSelectedModel.value = mlModels.value[0]?.model_file || ''
      }
      if (!mlSelectedModel.value && mlModels.value.length > 0) {
        mlSelectedModel.value = mlModels.value[0].model_file
      }
    }
  } catch {}
}

onMounted(() => { loadMLModels() })

const mlSignalClass = computed(() => {
  if (!mlResult.value) return ''
  if (mlResult.value.latest_signal === 'LONG') return 'text-up'
  if (mlResult.value.latest_signal === 'SHORT') return 'text-down'
  return ''
})

async function runTrain() {
  if (props.chartData.length === 0) { mlError.value = '请先加载K线数据'; return }
  mlTraining.value = true; mlError.value = ''; mlResult.value = null; mlTrainResult.value = null
  try {
    const res = await fetch('/api/ml/train', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kline_data: props.chartData, contract: props.contract }),
    })
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || `HTTP ${res.status}`) }
    mlTrainResult.value = await res.json()
    await loadMLModels()
    if (mlTrainResult.value?.model_file) mlSelectedModel.value = mlTrainResult.value.model_file
  } catch (e: any) { mlError.value = e.message || '训练失败' }
  finally { mlTraining.value = false }
}

async function runRetrain() {
  if (props.chartData.length === 0) { mlError.value = '请先加载K线数据'; return }
  if (!mlSelectedModel.value) { mlError.value = '请先选择一个要重新训练的模型'; return }
  mlRetraining.value = true; mlError.value = ''; mlResult.value = null; mlTrainResult.value = null
  try {
    const res = await fetch('/api/ml/train', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kline_data: props.chartData, contract: props.contract, overwrite: mlSelectedModel.value }),
    })
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || `HTTP ${res.status}`) }
    mlTrainResult.value = await res.json()
    await loadMLModels()
    if (mlTrainResult.value?.model_file) mlSelectedModel.value = mlTrainResult.value.model_file
  } catch (e: any) { mlError.value = e.message || '重训练失败' }
  finally { mlRetraining.value = false }
}

const mlDeleteConfirmVisible = ref(false)
const mlDeletingName = ref('')

function showDeleteConfirm() {
  if (!mlSelectedModel.value) return
  mlDeletingName.value = mlSelectedModel.value
  mlDeleteConfirmVisible.value = true
}

async function runDeleteModel() {
  mlDeleteConfirmVisible.value = false
  mlDeleting.value = true; mlError.value = ''
  try {
    const res = await fetch('/api/ml/models/' + encodeURIComponent(mlDeletingName.value), { method: 'DELETE' })
    if (!res.ok) throw new Error('删除失败')
    await loadMLModels(); mlResult.value = null; Message.success('模型已删除')
  } catch (e: any) { mlError.value = e.message || '删除失败' }
  finally { mlDeleting.value = false }
}

async function runMLBacktest() {
  if (props.chartData.length === 0) { mlError.value = '请先加载K线数据'; return }
  if (!mlHasModel.value) { mlError.value = '没有已训练的模型，请先训练'; return }
  mlBacktesting.value = true; mlError.value = ''; mlResult.value = null
  try {
    const body: any = {
      kline_data: props.chartData,
      threshold: mlThreshold.value,
      use_filter: mlUseFilter.value,
      contract: props.contract,
    }
    if (mlSelectedModel.value) body.model_file = mlSelectedModel.value
    const res = await fetch('/api/ml/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || `HTTP ${res.status}`) }
    const result = await res.json()
    mlResult.value = result

    // 回测结果始终同步到交易记录页（即使0笔交易）
    if (result.trades) {
      emit('update:backtestResult', {
        initialEquity: 100000,
        finalEquity: (100000 * (1 + (result.strategy_return || 0))),
        pnl: 100000 * (result.strategy_return || 0),
        netPnl: 100000 * (result.strategy_return || 0),
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
      })
    }
  } catch (e: any) { mlError.value = e.message || '回测失败' }
  finally { mlBacktesting.value = false }
}
</script>

<style scoped>
.ml-tab-content { padding: 16px; }
.ml-header { margin-bottom: 12px; }
.ml-hint { font-size: 13px; color: #666; margin-top: 4px; }
.ml-params { background: #fff; border-radius: 6px; padding: 12px 16px; margin-bottom: 12px; border: 1px solid #e8e8e8; }
.ml-param-row { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
.ml-param-item label { display: block; font-size: 12px; color: #666; margin-bottom: 3px; }
.ml-error { background: #fff1f0; border: 1px solid #ffccc7; color: #cf1322; padding: 8px 12px; border-radius: 4px; margin-bottom: 12px; font-size: 13px; }
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
.table-scroll { flex: 1; overflow-y: auto; max-height: calc(100vh - 260px); }
.section-label { display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 600; color: #333; margin-bottom: 8px; }
.mini-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.mini-table th, .mini-table td { padding: 6px 8px; text-align: right; border-bottom: 1px solid #f0f0f0; white-space: nowrap; }
.mini-table thead th { position: sticky; top: 0; background: #f5f5f5; color: #999; font-weight: 600; border-bottom: 2px solid #e8e8e8; z-index: 1; }
.mini-table th:first-child, .mini-table td:first-child { text-align: left; }
.mini-table tbody tr:hover td { background: #f8f8ff; }
.text-up { color: #cf1322; font-weight: 600; }
.text-down { color: #389e0d; font-weight: 600; }
.td-num { color: #999; font-size: 12px; }
.row-up td { }
.row-down td { }
.row-total { background: #f0f5ff; border-top: 2px solid #d6e4ff; font-weight: 600; }
.row-total td { background: #f0f5ff; padding: 6px 8px; text-align: right; }
.row-total td:first-child { text-align: left; }
.trade-badge { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 12px; }
.badge-buy { background: #fff1f0; color: #cf1322; }
.badge-sell { background: #f6ffed; color: #389e0d; }
</style>
