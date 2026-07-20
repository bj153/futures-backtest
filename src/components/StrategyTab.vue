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
        <div class="section-label" style="margin-top:10px">最近 {{ Math.min(backtestResult.trades.length, 5) }} 笔交易（共 {{ backtestResult.trades.length }} 笔）</div>
        <div class="bt-trades-wrap">
          <table class="mini-table">
            <thead>
              <tr><th>时间</th><th>操作</th><th>价格</th><th>数量</th><th>盈亏</th></tr>
            </thead>
            <tbody>
              <tr v-for="(t, i) in backtestResult.trades.slice(-5).reverse()" :key="i" :class="t.pnl >= 0 ? 'row-up' : 'row-down'">
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
import { ref, onMounted } from 'vue'
import { Button, Select, Option, Message, Modal, Input } from 'view-ui-plus'
import StrategyEditor from './StrategyEditor.vue'

const props = defineProps<{
  modelValue: string
  running: boolean
  backtestResult?: any
}>()

function getActionClass(action: string) {
  if (['buy', '开多', '买开', '买平', 'cover'].includes(action)) return 'badge-buy'
  if (['sell', '开空', '卖开', '卖平', 'sell_short'].includes(action)) return 'badge-sell'
  return ''
}

const emit = defineEmits<{
  'update:modelValue': [value: string]
  runBacktest: []
  reset: []
}>()

// ---- 策略文件选择（复用 /api/files 和 /api/file 端点）----
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
