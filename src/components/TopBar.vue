<template>
  <header class="topbar">
    <div class="topbar-brand">
      <span class="brand-text">回测平台</span>
    </div>
    <div class="topbar-actions">
      <div class="live-clock">{{ nowStr }}</div>
      <Button size="small" :type="showEditor ? 'default' : 'text'" @click="$emit('toggleEditor')">
        {{ showEditor ? '← 回测' : '项目文件' }}
      </Button>
      <Button size="small" type="primary" :loading="updatingContracts" @click="$emit('updateContracts')">
        更新合约
      </Button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Button } from 'view-ui-plus'

defineProps<{
  showEditor: boolean
  updatingContracts: boolean
}>()

defineEmits<{
  toggleEditor: []
  updateContracts: []
}>()

// ---- 时钟 ----
const nowStr = ref('')
let clockTimer: any = null
function updateClock() {
  nowStr.value = new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}
onMounted(() => { updateClock(); clockTimer = setInterval(updateClock, 1000) })
onUnmounted(() => clearInterval(clockTimer))
</script>

<style scoped>
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

@media (max-width: 768px) {
  .topbar { padding: 0 12px; height: 44px; }
  .brand-text { font-size: 14px; }
  .brand-badge { display: none; }
  .live-clock { font-size: 12px; }
  .topbar-actions :deep(.ivu-btn) { font-size: 12px; padding: 0 8px; }
}
</style>
