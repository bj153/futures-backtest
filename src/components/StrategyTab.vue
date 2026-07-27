<template>
  <div class="strategy-fullscreen">
    <div class="strategy-fs-header">
      <div class="strategy-fs-title">
        <span>📝 策略编辑器</span>
        <span class="strategy-fs-hint">Python · 内置变量: close, high, low, volume, ema, rsi, atr, bb ...</span>
      </div>
      <div class="strategy-fs-actions">
        <Select
          v-model="selectedStrategy"
          size="small"
          clearable
          placeholder="选择策略文件"
          style="width:200px"
          @on-change="onSelectStrategy"
        >
          <Option v-for="s in strategyFiles" :key="s" :value="s">{{ s.replace('.py', '') }}</Option>
        </Select>
        <Button size="small" type="primary" :loading="saving" @click="saveStrategy">保存</Button>
        <Button size="small" type="default" @click="newStrategyVisible = true">新建</Button>
        <Button size="small" type="error" :disabled="!selectedStrategy" @click="confirmDelete">删除</Button>
        <Button size="small" type="success" :loading="running" @click="$emit('runBacktest')">开始回测</Button>
        <Button size="small" type="default" @click="$emit('reset')">重置</Button>
      </div>
    </div>
    <div class="strategy-fs-body">
      <StrategyEditor :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" />
    </div>

    <!-- 策略参数面板（根据选中策略动态显示） -->
    <div class="strategy-params" v-if="currentParamSpecs.length > 0">
      <div class="section-label" style="margin-bottom:6px;font-size:13px">
        策略参数（{{ selectedStrategy.replace('.py', '') }}）
        <Button size="small" type="default" @click="resetParams" style="padding:2px 8px;font-size:12px">重置默认</Button>
      </div>
      <div class="param-grid">
        <div class="param-item" v-for="spec in currentParamSpecs" :key="spec.name">
          <label :title="spec.name">{{ spec.label }}</label>
          <template v-if="spec.type === 'switch'">
            <Switch :model-value="paramValue(spec)" @on-change="(v: boolean) => onParamChange(spec.name, v)" size="small" />
          </template>
          <template v-else-if="spec.type === 'select'">
            <Select :model-value="paramValue(spec)" @on-change="(v: any) => onParamChange(spec.name, v)" size="small">
              <Option v-for="o in spec.options" :key="o.value" :value="o.value">{{ o.label }}</Option>
            </Select>
          </template>
          <template v-else>
            <InputNumber :model-value="paramValue(spec)" @on-change="(v: number) => onParamChange(spec.name, v)" :min="spec.min" :max="spec.max" :step="spec.step || 1" size="small" style="width:100%" />
          </template>
        </div>
      </div>
    </div>

    <!-- 回测结果摘要 -->
    <div class="bt-result" v-if="backtestResult">
      <div class="section-label">📊 回测结果</div>
      <div class="bt-cards">
        <div class="bt-card">
          <div class="bt-card-label">总收益率</div>
          <div class="bt-card-value" :class="backtestResult.totalReturn >= 0 ? 'text-up' : 'text-down'">
            {{ backtestResult.totalReturn >= 0 ? '+' : '' }}{{ backtestResult.totalReturn.toFixed(2) }}%
          </div>
        </div>
        <div class="bt-card">
          <div class="bt-card-label">年化收益</div>
          <div class="bt-card-value" :class="(backtestResult.annualizedReturn || 0) >= 0 ? 'text-up' : 'text-down'">
            {{ (backtestResult.annualizedReturn || 0) >= 0 ? '+' : '' }}{{ (backtestResult.annualizedReturn || 0).toFixed(2) }}%
          </div>
        </div>
        <div class="bt-card">
          <div class="bt-card-label">胜率</div>
          <div class="bt-card-value">{{ backtestResult.winRate.toFixed(1) }}%</div>
        </div>
        <div class="bt-card">
          <div class="bt-card-label">交易笔数</div>
          <div class="bt-card-value">{{ backtestResult.tradeCount }}</div>
        </div>
        <div class="bt-card">
          <div class="bt-card-label">最大回撤</div>
          <div class="bt-card-value text-down">-{{ backtestResult.maxDrawdown.toFixed(2) }}%</div>
        </div>
        <div class="bt-card">
          <div class="bt-card-label">期末权益</div>
          <div class="bt-card-value" :class="backtestResult.netPnl >= 0 ? 'text-up' : 'text-down'">
            {{ backtestResult.finalEquity?.toFixed(0) }}
          </div>
        </div>
      </div>

      <!-- 最近 5 笔交易 -->
      <template v-if="backtestResult.trades?.length">
        <div class="section-label" style="margin-top:10px">全部交易记录（共 {{ backtestResult.trades.length }} 笔）</div>
        <div class="bt-trades-wrap">
          <table class="mini-table">
            <thead>
              <tr><th>时间</th><th>操作</th><th>价格</th><th>数量</th><th>盈亏</th></tr>
            </thead>
            <tbody>
              <tr v-for="(t, i) in backtestResult.trades.slice().reverse()" :key="i" :class="t.pnl >= 0 ? 'row-up' : 'row-down'">
                <td>{{ t.time?.slice(5, 16) }}</td>
                <td><span class="trade-badge" :class="getActionClass(t.action)">{{ t.action }}</span></td>
                <td>{{ t.price?.toFixed(2) }}</td>
                <td>{{ t.quantity }}</td>
                <td :class="t.pnl >= 0 ? 'text-up' : 'text-down'">{{ t.pnl >= 0 ? '+' : '' }}{{ t.pnl?.toFixed(2) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>
  </div>

  <!-- 新建策略弹窗 -->
  <Modal v-model="newStrategyVisible" title="新建策略" :width="400" @on-ok="createStrategy">
    <p style="margin-bottom:8px;font-size:13px;color:#666">请输入策略名（仅限字母、数字、下划线，自动追加 .py）：</p>
    <Input v-model="newStrategyName" placeholder="例如 my_strategy" />
  </Modal>

  <!-- 删除策略确认弹窗 -->
  <Modal v-model="deleteConfirmVisible" title="删除策略" :width="400" @on-ok="deleteStrategy">
    <p>确定要删除策略 <strong>{{ selectedStrategy }}</strong> 吗？</p>
    <p style="color:#999;font-size:13px;margin-top:8px">此操作不可恢复。</p>
  </Modal>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { Button, Select, Option, Message, Modal, Input, InputNumber, Switch } from 'view-ui-plus'
import StrategyEditor from './StrategyEditor.vue'

const props = defineProps<{
  modelValue: string
  running: boolean
  backtestResult?: any
  strategyParams: Record<string, any>
  selectedFile: string
}>()

function getActionClass(action: string) {
  if (['buy', '开多', '买开', '买平', 'cover'].includes(action)) return 'badge-buy'
  if (['sell', '开空', '卖开', '卖平', 'sell_short'].includes(action)) return 'badge-sell'
  return ''
}

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:strategyParams': [params: Record<string, any>]
  'update:selectedFile': [name: string]
  runBacktest: []
  reset: []
}>()

// ---- 策略参数定义（每种策略对应不同参数面板）----
interface ParamSpec {
  name: string; label: string; type: 'number' | 'switch' | 'select'
  min?: number; max?: number; step?: number
  default: number | boolean
  options?: { value: any; label: string }[]
}

const STRATEGY_PARAM_SPECS: Record<string, ParamSpec[]> = {
  'stable_reversion.py': [
    { name: 'rsi_len', label: 'RSI周期', type: 'number', min: 1, max: 60, default: 2 },
    { name: 'long_rsi', label: 'RSI下限', type: 'number', min: 0, max: 50, default: 10 },
    { name: 'short_rsi', label: 'RSI上限', type: 'number', min: 50, max: 100, default: 90 },
    { name: 'ema_len', label: 'EMA周期', type: 'number', min: 10, max: 500, default: 200 },
    { name: 'adx_period', label: 'ADX周期', type: 'number', min: 3, max: 60, default: 14 },
    { name: 'adx_max', label: 'ADX上限', type: 'number', min: 10, max: 60, default: 25 },
    { name: 'atr_len', label: 'ATR周期', type: 'number', min: 3, max: 60, default: 14 },
    { name: 'vwap_dev', label: 'VWAP偏离(0=关)', type: 'number', min: 0, max: 5, step: 0.1, default: 0 },
    { name: 'sl_atr', label: '止损ATR', type: 'number', min: 0.1, max: 20, step: 0.1, default: 2.0 },
    { name: 'tp_atr', label: '止盈ATR', type: 'number', min: 0.1, max: 20, step: 0.1, default: 3.0 },
    { name: 'time_stop', label: '时间止损K线', type: 'number', min: 1, max: 500, default: 12 },
  ],
  'rsi2_revert.py': [
    { name: 'rsi_len', label: 'RSI周期', type: 'number', min: 1, max: 60, default: 2 },
    { name: 'long_rsi', label: 'RSI下限', type: 'number', min: 0, max: 50, default: 5 },
    { name: 'short_rsi', label: 'RSI上限', type: 'number', min: 50, max: 100, default: 95 },
    { name: 'slow_len', label: 'EMA方向周期', type: 'number', min: 10, max: 500, default: 200 },
    { name: 'use_ema', label: 'EMA方向保护', type: 'switch', default: true },
    { name: 'tp_len', label: '止盈SMA周期', type: 'number', min: 1, max: 60, default: 5 },
    { name: 'tp_mode', label: '止盈模式', type: 'select', options: [{ value: 'sma', label: 'SMA' }, { value: 'atr', label: 'ATR' }], default: 'sma' },
    { name: 'tp_atr', label: '止盈ATR倍数', type: 'number', min: 0.1, max: 10, step: 0.1, default: 1.0 },
    { name: 'atr_len', label: 'ATR周期', type: 'number', min: 3, max: 60, default: 14 },
    { name: 'sl_atr', label: '止损ATR', type: 'number', min: 0.1, max: 20, step: 0.1, default: 2.5 },
    { name: 'time_stop', label: '时间止损K线', type: 'number', min: 1, max: 500, default: 30 },
  ],
  'mean_revert.py': [
    { name: 'boll_len', label: 'BOLL周期', type: 'number', min: 5, max: 200, default: 20 },
    { name: 'boll_mult', label: 'BOLL标准差', type: 'number', min: 0.5, max: 5, step: 0.1, default: 2.0 },
    { name: 'use_ema_filter', label: 'EMA方向过滤', type: 'select', options: [{ value: 0, label: '关闭' }, { value: 1, label: '只顺EMA' }, { value: 2, label: '双向但逆向更深' }], default: 1 },
    { name: 'ema_len', label: 'EMA周期', type: 'number', min: 10, max: 500, default: 200 },
    { name: 'counter_mult', label: '逆向通道倍数', type: 'number', min: 1, max: 5, step: 0.05, default: 1.25 },
    { name: 'adx_period', label: 'ADX周期', type: 'number', min: 3, max: 60, default: 14 },
    { name: 'adx_max', label: 'ADX上限', type: 'number', min: 10, max: 60, default: 25 },
    { name: 'entry_mode', label: '入场模式', type: 'select', options: [{ value: 'break', label: '突破即入场' }, { value: 'reentry', label: '收回通道再入场' }], default: 'break' },
    { name: 'tp_mode', label: '止盈模式', type: 'select', options: [{ value: 'atr', label: 'ATR固定' }, { value: 'mid', label: '中轨' }], default: 'atr' },
    { name: 'atr_len', label: 'ATR周期', type: 'number', min: 3, max: 60, default: 14 },
    { name: 'tp_atr', label: '止盈ATR', type: 'number', min: 0.1, max: 10, step: 0.1, default: 1.0 },
    { name: 'sl_atr', label: '止损ATR', type: 'number', min: 0.1, max: 10, step: 0.1, default: 1.5 },
    { name: 'time_stop', label: '时间止损K线', type: 'number', min: 1, max: 500, default: 20 },
  ],
  'trend_atr_v2.py': [
    { name: 'donchian_len', label: '唐奇安周期', type: 'number', min: 10, max: 200, default: 40 },
    { name: 'ema_len', label: 'EMA趋势周期', type: 'number', min: 10, max: 500, default: 60 },
    { name: 'use_adx', label: 'ADX过滤', type: 'switch', default: true },
    { name: 'adx_period', label: 'ADX周期', type: 'number', min: 3, max: 60, default: 14 },
    { name: 'adx_threshold', label: 'ADX阈值', type: 'number', min: 10, max: 60, default: 25 },
    { name: 'use_er', label: 'ER过滤', type: 'switch', default: true },
    { name: 'er_len', label: 'ER窗口', type: 'number', min: 5, max: 100, default: 25 },
    { name: 'er_threshold', label: 'ER阈值', type: 'number', min: 0.1, max: 1, step: 0.05, default: 0.45 },
    { name: 'atr_period', label: 'ATR周期', type: 'number', min: 3, max: 60, default: 14 },
    { name: 'init_sl_atr', label: '初始止损ATR', type: 'number', min: 0.5, max: 10, step: 0.1, default: 2.0 },
    { name: 'trail_atr', label: '吊灯止损ATR', type: 'number', min: 0.5, max: 10, step: 0.1, default: 3.0 },
    { name: 'tp_r', label: 'R倍数止盈(0=关)', type: 'number', min: 0, max: 20, step: 0.5, default: 0 },
  ],
  'eagle_ladder_k.py': [
    { name: 'ema_fast', label: 'SMA周期', type: 'number', min: 5, max: 100, default: 24 },
    { name: 'use_structure_filter', label: '结构过滤', type: 'switch', default: true },
    { name: 'dow_gap', label: '极点最小间隔', type: 'number', min: 1, max: 10, default: 1 },
    { name: 'dow_lookback', label: '道氏搜索窗口', type: 'number', min: 10, max: 200, default: 40 },
    { name: 'tick', label: '最小变动价位', type: 'number', min: 0.1, max: 10, step: 0.1, default: 1.0 },
    { name: 'rr_ratio', label: '盈亏比', type: 'number', min: 0.5, max: 5, step: 0.1, default: 1.0 },
    { name: 'tp_extra_ticks', label: '止盈额外tick', type: 'number', min: 0, max: 20, default: 1 },
    { name: 'atr_n', label: 'ATR窗口', type: 'number', min: 3, max: 60, default: 14 },
    { name: 'max_risk_ratio', label: '最大风险ATR倍数', type: 'number', min: 0, max: 20, step: 0.5, default: 5 },
    { name: 'reentry_bars', label: '再入场冷却K线', type: 'number', min: 0, max: 20, default: 2 },
  ],
  'vwap_revert.py': [
    { name: 'dev_atr', label: '偏离ATR倍数', type: 'number', min: 0.5, max: 5, step: 0.1, default: 1.5 },
    { name: 'atr_len', label: 'ATR周期', type: 'number', min: 3, max: 60, default: 14 },
    { name: 'sl_atr', label: '止损ATR', type: 'number', min: 0.1, max: 10, step: 0.1, default: 1.5 },
    { name: 'time_stop', label: '时间止损K线', type: 'number', min: 1, max: 500, default: 20 },
    { name: 'min_bars', label: '最小K线数', type: 'number', min: 1, max: 100, default: 10 },
  ],
  'streak_revert.py': [
    { name: 'streak_n', label: '连续K线数', type: 'number', min: 1, max: 10, default: 3 },
    { name: 'move_atr', label: '累积ATR倍数', type: 'number', min: 0.1, max: 10, step: 0.1, default: 1.5 },
    { name: 'atr_len', label: 'ATR周期', type: 'number', min: 3, max: 60, default: 14 },
    { name: 'tp_atr', label: '止盈ATR', type: 'number', min: 0.1, max: 5, step: 0.1, default: 0.8 },
    { name: 'sl_atr', label: '止损ATR', type: 'number', min: 0.1, max: 5, step: 0.1, default: 1.2 },
    { name: 'time_stop', label: '时间止损K线', type: 'number', min: 1, max: 500, default: 15 },
  ],
}

// 当前策略的参数规格
const currentParamSpecs = computed<ParamSpec[]>(() => {
  return STRATEGY_PARAM_SPECS[props.selectedFile] || []
})

// 当前策略参数值（local copy）
const localParams = ref<Record<string, any>>({ ...props.strategyParams })

watch(() => props.selectedFile, () => {
  // 切换策略时，用默认值初始化参数
  const specs = STRATEGY_PARAM_SPECS[props.selectedFile] || []
  const defaults: Record<string, any> = {}
  for (const s of specs) {
    defaults[s.name] = props.strategyParams[s.name] ?? s.default
  }
  localParams.value = defaults
  emit('update:strategyParams', { ...defaults })
}, { immediate: true })

function onParamChange(name: string, val: any) {
  localParams.value[name] = val
  emit('update:strategyParams', { ...localParams.value })
}

function resetParams() {
  const specs = STRATEGY_PARAM_SPECS[props.selectedFile] || []
  const defaults: Record<string, any> = {}
  for (const s of specs) {
    defaults[s.name] = s.default
  }
  localParams.value = defaults
  emit('update:strategyParams', { ...defaults })
}

// 参数值（处理 select 类型的 value 转换）
function paramValue(spec: ParamSpec): any {
  const v = localParams.value[spec.name]
  if (v === undefined || v === null) return spec.default
  return v
}

const strategyFiles = ref<string[]>([])
const selectedStrategy = ref('')

async function loadStrategyFiles() {
  try {
    const res = await fetch('/api/files?path=backend/strategies')
    if (!res.ok) return
    const data = await res.json()
    strategyFiles.value = (data.children || [])
      .filter((f: any) => !f.is_dir && f.name.endsWith('.py'))
      .map((f: any) => f.name)
  } catch {}
}

async function onSelectStrategy(name: string) {
  if (!name) return
  try {
    const res = await fetch(`/api/file?path=${encodeURIComponent('backend/strategies/' + name)}`)
    if (!res.ok) throw new Error('Failed')
    const data = await res.json()
    emit('update:modelValue', data.content)
    emit('update:selectedFile', name)
    Message.success(`已加载策略 ${name}`)
  } catch {
    Message.error('加载策略文件失败')
  }
}

onMounted(loadStrategyFiles)

// ---- 保存当前策略 ----
const saving = ref(false)

async function saveStrategy() {
  if (!selectedStrategy.value) {
    Message.warning('请先选择策略文件，或点击「新建」创建新策略')
    return
  }
  saving.value = true
  try {
    const res = await fetch(`/api/file?path=${encodeURIComponent('backend/strategies/' + selectedStrategy.value)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: props.modelValue }),
    })
    if (!res.ok) throw new Error('Failed')
    Message.success(`已保存 ${selectedStrategy.value}`)
  } catch {
    Message.error('保存失败')
  } finally {
    saving.value = false
  }
}

// ---- 新建策略 ----
const newStrategyVisible = ref(false)
const newStrategyName = ref('')

const newStrategyTemplate = `# ========== 新策略 ==========
# init(context): 初始化
# handle_bar(context, bar_dict): 每根K线执行一次
# 下单: context['_action']='buy|sell|short|cover'
#       context['_price']=价格  context['_reason']='理由'
# 内置函数: sma, ema, rsi, calc_verts

def init(context):
    context['history'] = []

def handle_bar(context, bar_dict):
    history = context['history']
    history.append(bar_dict)
    # TODO: 在这里编写策略逻辑
`

async function createStrategy() {
  const name = newStrategyName.value.trim()
  if (!/^[A-Za-z0-9_]+$/.test(name)) {
    Message.warning('策略名只允许字母、数字、下划线')
    return
  }
  const fileName = name + '.py'
  if (strategyFiles.value.includes(fileName)) {
    Message.warning(`策略 ${fileName} 已存在，请换个名字`)
    return
  }
  try {
    const res = await fetch(`/api/file?path=${encodeURIComponent('backend/strategies/' + fileName)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: newStrategyTemplate }),
    })
    if (!res.ok) throw new Error('Failed')
    Message.success(`已创建 ${fileName}`)
    newStrategyName.value = ''
    await loadStrategyFiles()
    selectedStrategy.value = fileName
    emit('update:modelValue', newStrategyTemplate)
  } catch {
    Message.error('创建策略失败')
  }
}

// ---- 删除策略 ----
const deleteConfirmVisible = ref(false)

function confirmDelete() {
  if (!selectedStrategy.value) return
  deleteConfirmVisible.value = true
}

async function deleteStrategy() {
  const fileName = selectedStrategy.value
  try {
    const res = await fetch(`/api/file?path=${encodeURIComponent('backend/strategies/' + fileName)}`, {
      method: 'DELETE',
    })
    if (!res.ok) throw new Error('Failed')
    Message.success(`已删除 ${fileName}`)
    selectedStrategy.value = ''
    await loadStrategyFiles()
  } catch {
    Message.error('删除失败')
  }
}
</script>

<style scoped>
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

/* 策略参数面板 */
.strategy-params { padding: 10px 16px; border-top: 1px solid #e8e8e8; background: #fafafa; flex-shrink: 0; }
.strategy-params .param-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; }
.strategy-params .param-item { display: flex; flex-direction: column; gap: 2px; }
.strategy-params .param-item label { font-size: 12px; color: #888; }
@media (max-width: 1000px) { .strategy-params .param-grid { grid-template-columns: repeat(4, 1fr); } }
@media (max-width: 768px) { .strategy-params .param-grid { grid-template-columns: repeat(2, 1fr); } }

/* 回测结果摘要 */
.bt-result { padding: 12px 16px; border-top: 1px solid #e8e8e8; flex-shrink: 0; }
.section-label { display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 600; color: #333; margin-bottom: 8px; }
.bt-cards { display: flex; flex-wrap: wrap; gap: 8px; }
.bt-card { background: #fafafa; border: 1px solid #f0f0f0; border-radius: 6px; padding: 10px 14px; min-width: 120px; flex: 1; }
.bt-card-label { font-size: 12px; color: #999; margin-bottom: 4px; }
.bt-card-value { font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
.bt-trades-wrap { max-height: 180px; overflow-y: auto; border: 1px solid #f0f0f0; border-radius: 4px; }

/* 迷你表格 */
.mini-table { width: 100%; font-size: 13px; border-collapse: collapse; }
.mini-table th { position: sticky; top: 0; background: #f5f5f5; color: #999; padding: 6px 8px; text-align: right; font-weight: 600; border-bottom: 2px solid #e8e8e8; z-index: 1; }
.mini-table td { padding: 4px 8px; text-align: right; color: #333; border-bottom: 1px solid #f0f0f0; }
.mini-table th:first-child, .mini-table td:first-child { text-align: left; }
.mini-table tbody tr:hover td { background: #f8f8ff; }
.row-up td { background: #f6ffed; }
.row-down td { background: #fff2f0; }

/* 红涨绿跌 */
.text-up { color: #cf1322; font-weight: 600; }
.text-down { color: #389e0d; font-weight: 600; }

/* 交易标签 */
.trade-badge { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 12px; font-weight: 500; }
.badge-buy { background: #fff2f0; color: #cf1322; border: 1px solid #ffccc7; }
.badge-sell { background: #f6ffed; color: #389e0d; border: 1px solid #b7eb8f; }

@media (max-width: 768px) {
  .strategy-fs-body { min-height: 60vh; }
  .strategy-fs-body :deep(.cm-editor) { height: 60vh !important; }
  .strategy-fs-header { padding: 10px 12px; flex-wrap: wrap; gap: 6px; }
  .strategy-fs-title { font-size: 14px; }
  .strategy-fs-hint { display: none; }
}
</style>
