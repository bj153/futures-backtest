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
}>()

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

@media (max-width: 768px) {
  .strategy-fs-body { min-height: 60vh; }
  .strategy-fs-body :deep(.cm-editor) { height: 60vh !important; }
  .strategy-fs-header { padding: 10px 12px; flex-wrap: wrap; gap: 6px; }
  .strategy-fs-title { font-size: 14px; }
  .strategy-fs-hint { display: none; }
}
</style>
