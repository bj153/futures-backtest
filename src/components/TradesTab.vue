<template>
  <div class="table-tab-content" v-if="backtestResult?.trades?.length">
    <div class="section-label">交易记录 ({{ backtestResult.trades.length }}笔)</div>
    <div class="table-scroll">
      <table class="mini-table">
        <thead>
          <tr><th>#</th><th>时间</th><th>操作</th><th>价格</th><th>数量</th><th>权益</th><th>盈亏</th></tr>
        </thead>
        <tbody>
          <tr v-for="(t, i) in backtestResult.trades.slice().reverse()" :key="i" :class="t.pnl >= 0 ? 'row-up' : 'row-down'">
            <td class="td-num">{{ backtestResult.trades.length - (i as number) }}</td>
            <td>{{ t.time?.slice(5, 16) }}</td>
            <td><span class="trade-badge" :class="getActionClass(t.action)">{{ t.action }}</span></td>
            <td>{{ t.price?.toFixed(2) }}</td>
            <td>{{ t.quantity }}</td>
            <td>{{ t.equity?.toFixed(2) }}</td>
            <td :class="t.pnl >= 0 ? 'text-up' : 'text-down'">{{ t.pnl >= 0 ? '+' : '' }}{{ t.pnl?.toFixed(2) }}</td>
          </tr>
        </tbody>
        <tfoot>
          <tr class="row-total">
            <td colspan="5">合计</td>
            <td>{{ backtestResult.trades[backtestResult.trades.length - 1]?.equity?.toFixed(2) }}</td>
            <td :class="totalTradesPnl >= 0 ? 'text-up' : 'text-down'">{{ totalTradesPnl >= 0 ? '+' : '' }}{{ totalTradesPnl?.toFixed(2) }}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  </div>
  <div v-else class="empty-state">
    <div class="empty-icon">📋</div>
    <p>先运行回测查看交易记录</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  backtestResult: any
}>()

function getActionClass(action: string) {
  if (['buy', '开多', '买开', '买平', 'cover'].includes(action)) return 'badge-buy'
  if (['sell', '开空', '卖开', '卖平', 'sell_short'].includes(action)) return 'badge-sell'
  return ''
}

const totalTradesPnl = computed(() => {
  if (!props.backtestResult?.trades) return 0
  return props.backtestResult.trades.reduce((sum: number, t: any) => sum + (t.pnl || 0), 0)
})
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
.mini-table tfoot td { background: #f0f5ff; border-top: 2px solid #d6e4ff; font-weight: 600; padding: 6px 8px; text-align: right; }
.mini-table tfoot td:first-child { text-align: left; }
.td-num { color: #ccc; font-size: 12px; }
.row-up td { background: #f6ffed; }
.row-down td { background: #fff2f0; }

/* 红涨绿跌 */
.text-up { color: #cf1322; font-weight: 600; }
.text-down { color: #389e0d; font-weight: 600; }

/* 交易标签 */
.trade-badge { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 12px; font-weight: 500; }
.badge-buy { background: #fff2f0; color: #cf1322; border: 1px solid #ffccc7; }
.badge-sell { background: #f6ffed; color: #389e0d; border: 1px solid #b7eb8f; }

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
