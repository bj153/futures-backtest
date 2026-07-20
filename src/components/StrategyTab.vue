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
        <Button size="small" type="success" :loading="running" @click="$emit('runBacktest')">开始回测</Button>
        <Button size="small" type="default" @click="$emit('reset')">重置</Button>
      </div>
    </div>
    <div class="strategy-fs-body">
      <StrategyEditor :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Button, Select, Option, Message } from 'view-ui-plus'
import StrategyEditor from './StrategyEditor.vue'

defineProps<{
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
