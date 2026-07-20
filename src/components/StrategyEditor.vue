<template>
  <div class="strategy-editor">
    <Codemirror
      v-model="code"
      :extensions="extensions"
      :autofocus="true"
      @ready="handleReady"
    />

  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Codemirror } from 'vue-codemirror'
import { javascript } from '@codemirror/lang-javascript'
import { oneDark } from '@codemirror/theme-one-dark'

const props = defineProps<{
  modelValue: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const code = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const extensions = computed(() => [
  javascript(),
  oneDark
])

function handleReady(payload: any) {
  // 编辑器准备就绪
}
</script>

<style scoped>
.strategy-editor {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.strategy-editor :deep(.cm-editor) {
  border-radius: 8px;
  overflow: hidden;
}

.strategy-editor :deep(.cm-scroller) {
  font-family: 'Fira Code', 'Consolas', monospace;
  font-size: 15px;
  line-height: 1.7;
}

.strategy-editor :deep(.cm-gutters) {
  background-color: #282c34;
  border-right: 1px solid #3e4451;
}

.strategy-editor :deep(.cm-activeLineGutter) {
  background-color: #3e4451;
}

.editor-help {
  font-size: 12px;
}

@media (max-width: 768px) {
  .strategy-editor :deep(.cm-scroller) { font-size: 14px; line-height: 1.6; }
  .editor-help { font-size: 12px; }
  .help-content { padding: 10px; }
  .help-content ul { padding-left: 14px; }
}

.editor-help summary {
  cursor: pointer;
  color: #00d4ff;
  padding: 8px 0;
}

.help-content {
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
  padding: 15px;
  margin-top: 10px;
}

.help-content h4 {
  margin: 10px 0 5px 0;
  color: #00ff88;
  font-size: 13px;
}

.help-content h4:first-child {
  margin-top: 0;
}

.help-content ul {
  margin: 0;
  padding-left: 20px;
}

.help-content li {
  margin: 3px 0;
  color: #aaa;
}

.help-content code {
  background: rgba(0, 212, 255, 0.1);
  color: #00d4ff;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Fira Code', monospace;
}
</style>
