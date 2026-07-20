<template>
  <div class="table-tab-content" v-if="chartData.length">
    <div class="section-label">行情数据 ({{ chartData.length }}条)</div>
    <div class="table-scroll">
      <table class="mini-table">
        <thead>
          <tr><th>时间</th><th>开</th><th>高</th><th>低</th><th>收</th><th>成交量</th></tr>
        </thead>
        <tbody>
          <tr v-for="(d, i) in chartData.slice().reverse()" :key="i">
            <td>{{ d.time?.slice(5, 16) }}</td>
            <td>{{ d.open?.toFixed(2) }}</td>
            <td>{{ d.high?.toFixed(2) }}</td>
            <td>{{ d.low?.toFixed(2) }}</td>
            <td :class="d.close >= d.open ? 'text-up' : 'text-down'">{{ d.close?.toFixed(2) }}</td>
            <td>{{ d.volume?.toLocaleString() }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
  <div v-else class="empty-state">
    <div class="empty-icon">📊</div>
    <p>先加载数据查看行情</p>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  chartData: any[]
}>()
</script>

<style scoped>
/* Tab 表格 */
.table-tab-content { display: flex; flex-direction: column; flex: 1; }
.table-scroll { flex: 1; overflow-y: auto; max-height: calc(100vh - 260px); }

/* 迷你表格 */
.mini-table { width: 100%; font-size: 13px; border-collapse: collapse; }
.mini-table th { position: sticky; top: 0; background: #f5f5f5; color: #999; padding: 6px 8px; text-align: right; font-weight: 600; border-bottom: 2px solid #e8e8e8; z-index: 1; }
.mini-table td { padding: 4px 8px; text-align: right; color: #333; border-bottom: 1px solid #f0f0f0; }
.mini-table th:first-child, .mini-table td:first-child { text-align: left; }
.mini-table tbody tr:hover td { background: #f8f8ff; }

/* 红涨绿跌 */
.text-up { color: #cf1322; font-weight: 600; }
.text-down { color: #389e0d; font-weight: 600; }

.section-label { display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 600; color: #333; margin-bottom: 8px; }

/* 空状态 */
.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 400px; color: #bbb; }
.empty-icon { font-size: 40px; margin-bottom: 10px; }
.empty-state p { margin: 3px 0; font-size: 15px; }

@media (max-width: 768px) {
  /* 迷你表格字体缩小 */
  .mini-table { font-size: 12px; }
  .mini-table th, .mini-table td { padding: 3px 5px; }

  /* 空状态 */
  .empty-state { height: 280px; }
  .empty-state p { font-size: 14px; }
}
</style>
