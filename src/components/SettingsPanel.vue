<template>
  <div class="sidebar-section">
    <div class="section-label">参数设置 <span style="font-weight:400;font-size:13px;color:#1890ff">{{ contract?.toUpperCase() || '未选择' }}</span></div>
    <div class="param-grid">
      <div class="param-item">
        <label>周期</label>
        <Select v-model="localFrequency" size="small">
          <Option v-for="f in frequencies" :key="f.value" :value="f.value">{{ f.label }}</Option>
        </Select>
      </div>
      <div class="param-item">
        <label>数据源</label>
        <Select v-model="localDataSource" size="small">
          <Option v-for="s in dataSources" :key="s.value" :value="s.value">{{ s.label }}</Option>
        </Select>
      </div>
      <div class="param-item">
        <label>初始资金</label>
        <InputNumber v-model="localInitialCapital" :min="1000" :step="1000" size="small" style="width:100%" />
      </div>
      <div class="param-item">
        <label>手续费率</label>
        <InputNumber v-model="localCommissionRate" :min="0" :step="0.0001" size="small" style="width:100%" />
      </div>
    </div>
    <div class="param-row">
      <div class="param-item">
        <label>开始日期</label>
        <DatePicker v-model="localStartDate" type="date" size="small" :format="'yyyy-MM-dd' as any" />
      </div>
      <div class="param-item">
        <label>结束日期</label>
        <DatePicker v-model="localEndDate" type="date" size="small" :format="'yyyy-MM-dd' as any" />
      </div>
    </div>
    <div class="action-buttons">
      <Button type="primary" long @click="$emit('loadData')" :loading="loading" :disabled="!contract">
        加载数据
      </Button>
    </div>
    <div class="draw-line-row">
      <span class="draw-label">回撤值</span>
      <InputNumber :min="0.01" :max="20" :step="0.05" v-model="localDrawThreshold" size="small" style="width:80px" />
      <Button type="default" @click="$emit('drawPolyline')">画折线</Button>
    </div>
    <div class="param-row" style="margin-top:6px">
      <div class="param-item" style="width:48%">
        <label>EMA快线</label>
        <InputNumber :min="3" :max="60" v-model="localEmaFast" size="small" style="width:100%" />
      </div>
      <div class="param-item" style="width:48%">
        <label>EMA慢线</label>
        <InputNumber :min="10" :max="200" v-model="localEmaSlow" size="small" style="width:100%" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Button, Select, Option, DatePicker, InputNumber } from 'view-ui-plus'

const props = defineProps<{
  contract: string
  frequency: string
  dataSource: string
  startDate: Date
  endDate: Date
  initialCapital: number
  commissionRate: number
  drawThreshold: number
  emaFast: number
  emaSlow: number
  loading: boolean
  running: boolean
}>()

const emit = defineEmits<{
  'update:frequency': [v: string]
  'update:dataSource': [v: string]
  'update:startDate': [v: Date]
  'update:endDate': [v: Date]
  'update:initialCapital': [v: number]
  'update:commissionRate': [v: number]
  'update:drawThreshold': [v: number]
  'update:emaFast': [v: number]
  'update:emaSlow': [v: number]
  'loadData': []
  'runBacktest': []
  'drawPolyline': []
}>()

const frequencies = [
  { value: '1d', label: '日线' },
  { value: '1h', label: '小时线' },
  { value: '30m', label: '30分钟' },
  { value: '15m', label: '15分钟' },
  { value: '10m', label: '10分钟' },
  { value: '5m', label: '5分钟' },
  { value: '1m', label: '1分钟' },
]
const dataSources = [
  { value: 'akshare', label: 'AKShare' },
  { value: 'tushare', label: 'Tushare' },
  { value: 'tqsdk', label: '天勤' },
]

const localFrequency = ref(props.frequency)
const localDataSource = ref(props.dataSource)
const localStartDate = ref<any>(props.startDate)
const localEndDate = ref<any>(props.endDate)
const localInitialCapital = ref(props.initialCapital)
const localCommissionRate = ref(props.commissionRate)
const localDrawThreshold = ref(props.drawThreshold)
const localEmaFast = ref(props.emaFast)
const localEmaSlow = ref(props.emaSlow)

watch(localFrequency, v => emit('update:frequency', v))
watch(localDataSource, v => emit('update:dataSource', v))
watch(localStartDate, v => v && emit('update:startDate', v))
watch(localEndDate, v => v && emit('update:endDate', v))
watch(localInitialCapital, v => emit('update:initialCapital', v))
watch(localCommissionRate, v => emit('update:commissionRate', v))
watch(localDrawThreshold, v => emit('update:drawThreshold', v))
watch(localEmaFast, v => emit('update:emaFast', v))
watch(localEmaSlow, v => emit('update:emaSlow', v))
</script>

<style scoped>
.param-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
.param-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
.param-item { display: flex; flex-direction: column; gap: 3px; }
.param-item label { font-size: 13px; color: #666; }
.num-input {
  width: 100%; padding: 4px 8px; font-size: 14px; border: 1px solid #d9d9d9; border-radius: 4px;
  background: #fff; color: #333; outline: none; transition: border-color 0.2s;
}
.num-input:focus { border-color: #1890ff; box-shadow: 0 0 0 2px rgba(24,144,255,0.1); }

.action-buttons { display: flex; gap: 6px; margin-top: 4px; }
.draw-line-row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  margin-top: 8px;
  flex-wrap: wrap;
}
.draw-label {
  font-size: 12px;
  color: #888;
  white-space: nowrap;
}
</style>
