<template>
  <div class="sidebar-section">
    <div class="section-label">
      <span>合约品种</span>
      <span class="section-hint">{{ filteredContracts.length }}个</span>
    </div>
    <div class="contract-search">
      <input v-model="contractSearch" placeholder="搜索合约..." class="search-input" />
    </div>
    <div class="contract-tags">
      <span
        v-for="cat in contractCategories"
        :key="cat.key"
        class="tag"
        :class="{ active: activeCategory === cat.key }"
        @click="activeCategory = cat.key"
      >{{ cat.label }}</span>
    </div>
    <div class="contract-list">
      <div
        v-for="c in filteredContracts"
        :key="c.code"
        class="contract-item"
        :class="{ active: selectedContract === c.code }"
        @click="selectContract(c.code)"
      >
        <span class="contract-code">{{ c.code.toUpperCase() }}</span>
        <span class="contract-name">{{ c.name.replace(c.code.toUpperCase(), '').trim() }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

const props = defineProps<{
  selectedContract: string
}>()

const emit = defineEmits<{
  'update:selectedContract': [value: string]
}>()

const contracts = ref<{ code: string; name: string }[]>([])
const contractSearch = ref('')
const activeCategory = ref('all')

const contractCategories = [
  { key: 'all', label: '全部' },
  { key: 'black', label: '黑色' },
  { key: 'nonferrous', label: '有色' },
  { key: 'chemical', label: '化工' },
  { key: 'agriculture', label: '农产品' },
  { key: 'index', label: '股指' },
]

const categoryMap: Record<string, string> = {
  jm: 'black', j: 'black', i: 'black', rb: 'black', hc: 'black', sm: 'black', sf: 'black',
  fg: 'black', zc: 'black',
  cu: 'nonferrous', al: 'nonferrous', zn: 'nonferrous', ni: 'nonferrous', sn: 'nonferrous',
  pb: 'nonferrous', ss: 'nonferrous', ao: 'nonferrous',
  au: 'nonferrous', ag: 'nonferrous',
  sc: 'chemical', ru: 'chemical', nr: 'chemical', bu: 'chemical', fu: 'chemical',
  ta: 'chemical', ma: 'chemical', eg: 'chemical', pp: 'chemical', l: 'chemical',
  v: 'chemical', sa: 'chemical', ur: 'chemical', eb: 'chemical', pg: 'chemical',
  sp: 'chemical', sh: 'chemical', px: 'chemical', br: 'chemical',
  m: 'agriculture', y: 'agriculture', p: 'agriculture', oi: 'agriculture',
  rm: 'agriculture', a: 'agriculture', b: 'agriculture', c: 'agriculture',
  cf: 'agriculture', sr: 'agriculture', ap: 'agriculture', jd: 'agriculture',
  cs: 'agriculture', pk: 'agriculture', lh: 'agriculture',
  if: 'index', ic: 'index', ih: 'index', im: 'index',
}

function getCategory(code: string): string {
  const prefix = code.replace(/\d/g, '').toLowerCase()
  return categoryMap[prefix] || 'other'
}

const filteredContracts = computed(() => {
  let list = contracts.value
  if (activeCategory.value !== 'all') {
    list = list.filter(c => getCategory(c.code) === activeCategory.value)
  }
  if (contractSearch.value) {
    const q = contractSearch.value.toLowerCase()
    list = list.filter(c => c.code.toLowerCase().includes(q) || c.name.includes(q))
  }
  const mainMonths = ['05', '08', '09', '10', '11', '12', '01', '02']
  list = [...list].sort((a, b) => {
    const aMain = mainMonths.some(m => a.code.endsWith(m)) ? 0 : 1
    const bMain = mainMonths.some(m => b.code.endsWith(m)) ? 0 : 1
    return aMain - bMain || a.code.localeCompare(b.code)
  })
  return list
})

function selectContract(code: string) {
  emit('update:selectedContract', code)
}

async function loadContracts() {
  try {
    const res = await fetch('/api/contracts')
    const data = await res.json()
    contracts.value = data
    if (!contracts.value.find(c => c.code === props.selectedContract)) {
      const ma = contracts.value.find(c => c.code === 'ma2609')
      if (ma) emit('update:selectedContract', 'ma2609')
    }
  } catch {
    contracts.value = [
      { code: 'ma2609', name: '甲醇2609' },
      { code: 'ao2609', name: '氧化铝2609' },
      { code: 'if2606', name: '沪深300 2606' },
      { code: 'ic2606', name: '中证500 2606' },
    ]
  }
}

defineExpose({ loadContracts })

onMounted(loadContracts)
</script>

<style scoped>
.contract-search { margin-bottom: 8px; }
.search-input {
  width: 100%; padding: 5px 10px; font-size: 14px; border: 1px solid #d9d9d9; border-radius: 4px;
  background: #fff; color: #333; outline: none; transition: border-color 0.2s;
}
.search-input:focus { border-color: #1890ff; box-shadow: 0 0 0 2px rgba(24,144,255,0.1); }
.search-input::placeholder { color: #bbb; }

.contract-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
.tag {
  font-size: 13px; padding: 2px 8px; border-radius: 3px; cursor: pointer;
  background: #fafafa; color: #666; border: 1px solid #e8e8e8; transition: all 0.2s;
}
.tag:hover { border-color: #1890ff; color: #1890ff; }
.tag.active { background: #e6f7ff; border-color: #1890ff; color: #1890ff; }

.contract-list { max-height: 200px; overflow-y: auto; }
.contract-item {
  display: flex; align-items: center; gap: 8px; padding: 5px 8px; border-radius: 3px;
  cursor: pointer; transition: background 0.15s; font-size: 14px;
}
.contract-item:hover { background: #f5f5f5; }
.contract-item.active { background: #e6f7ff; }
.contract-code { font-family: monospace; font-weight: 600; color: #1890ff; min-width: 50px; font-size: 13px; }
.contract-name { color: #666; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.section-hint { font-size: 12px; color: #999; font-weight: normal; }
</style>
