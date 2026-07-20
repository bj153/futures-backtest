<template>
  <div class="editor-page">
    <header class="editor-header">
      <div class="header-left">
        <Button type="text" @click="treeVisible = !treeVisible" class="toggle-btn">{{ treeVisible ? '◀' : '▶' }}</Button>
        <Button type="text" @click="$emit('back')" class="back-btn">← 返回</Button>
        <Button type="text" @click="goUp" class="up-btn">⬆️ 上级</Button>
        <span class="header-title">📝 代码编辑器</span>
        <span class="path-display" v-if="currentPath !== '.'">{{ currentPath }}</span>
      </div>
      <div class="header-actions">
        <Button type="default" size="small" @click="refreshFiles">🔄 刷新</Button>
        <Button type="primary" size="small" @click="saveFile" :loading="saving" :disabled="!currentFile">💾 保存</Button>
      </div>
    </header>
    
    <div class="editor-body">
      <!-- 左侧文件树 -->
      <aside class="file-tree-panel" v-show="treeVisible">
        <div class="panel-header">
          <span>📁 {{ currentPath }}</span>
        </div>
        <div class="tree-content">
          <FileTree :tree="fileTree" :selected="currentFile" @select="onFileSelect" />
        </div>
      </aside>
      
      <!-- 右侧编辑器 -->
      <main class="code-editor-panel">
        <div v-if="!currentFile" class="no-file-selected">
          <div class="no-file-icon">📄</div>
          <p>从左侧选择文件进行编辑</p>
        </div>
        <div v-else class="editor-wrapper">
          <div class="editor-toolbar">
            <span class="current-file">{{ currentFile }}</span>
          </div>
          <Codemirror
            v-model="code"
            :style="{ height: '100%' }"
            :autofocus="true"
            :indent-with-tab="true"
            :tab-size="2"
            :extensions="extensions"
            @ready="onEditorReady"
          />
        </div>
      </main>
    </div>
    
    <!-- 状态栏 -->
    <footer class="editor-footer">
      <span v-if="currentFile">当前文件: {{ currentFile }}</span>
      <span v-else>未选择文件</span>
      <span v-if="lastSaved" class="save-status">已保存: {{ lastSaved }}</span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, shallowRef } from 'vue'
import { Button, Message } from 'view-ui-plus'
import { Codemirror } from 'vue-codemirror'
import { javascript } from '@codemirror/lang-javascript'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView } from '@codemirror/view'
import FileTree from '../components/FileTree.vue'

defineEmits(['back'])

const treeVisible = ref(true)
const fileTree = ref<any[]>([])
const currentFile = ref<string | null>(null)
const currentPath = ref('.')
const code = ref('')
const originalCode = ref('')
const saving = ref(false)
const lastSaved = ref<string | null>(null)
const editorRef = shallowRef<any>(null)

// CodeMirror extensions
const extensions = [
  javascript(),
  oneDark,
  EditorView.lineWrapping,
  EditorView.theme({
    '&': { height: '100%' },
    '.cm-scroller': { overflow: 'auto' },
    '.cm-content': { fontFamily: 'Consolas, Monaco, monospace', fontSize: '13px' },
    '.cm-gutters': { backgroundColor: '#1e1e1e' },
  }),
]

function onEditorReady({ view }: any) {
  editorRef.value = view
}

function goUp() {
  if (currentPath.value === '.') return
  const parts = currentPath.value.split('/')
  parts.pop()
  currentPath.value = parts.join('/') || '.'
  currentFile.value = null
  refreshFiles()
}

async function refreshFiles() {
  try {
    const res = await fetch('/api/files?path=' + encodeURIComponent(currentPath.value))
    const data = await res.json()
    fileTree.value = data.children || []
  } catch (e) {
    Message.error('加载文件列表失败')
  }
}

async function onFileSelect(file: any) {
  if (file.is_dir) {
    // 进入子目录
    currentPath.value = file.path
    currentFile.value = null
    refreshFiles()
    return
  }
  
  try {
    currentFile.value = file.path
    const res = await fetch('/api/file?path=' + encodeURIComponent(file.path))
    const data = await res.json()
    code.value = data.content
    originalCode.value = data.content
    lastSaved.value = null
  } catch (e) {
    Message.error('读取文件失败')
  }
}

async function saveFile() {
  if (!currentFile.value) return
  
  saving.value = true
  try {
    const res = await fetch('/api/file?path=' + encodeURIComponent(currentFile.value), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ content: code.value })
    })
    if (res.ok) {
      originalCode.value = code.value
      const now = new Date()
      lastSaved.value = now.toLocaleTimeString()
      Message.success('保存成功')
    } else {
      throw new Error('保存失败')
    }
  } catch (e) {
    Message.error('保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  refreshFiles()
})
</script>

<style scoped>
.editor-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #1e1e1e;
  color: #fff;
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #252526;
  border-bottom: 1px solid #3c3c3c;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.back-btn, .up-btn, .toggle-btn {
  color: #fff !important;
  padding: 4px 8px !important;
}

.path-display {
  color: #888;
  font-size: 13px;
}

.header-title {
  font-size: 14px;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.editor-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.file-tree-panel {
  width: 200px;
  min-width: 200px;
  background: #252526;
  border-right: 1px solid #3c3c3c;
  display: flex;
  flex-direction: column;
}

.panel-header {
  padding: 10px 12px;
  font-size: 12px;
  font-weight: 600;
  color: #cccccc;
  border-bottom: 1px solid #3c3c3c;
  text-transform: uppercase;
  word-break: break-all;
}

.tree-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.code-editor-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.no-file-selected {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #666;
}

.no-file-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

.editor-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.editor-toolbar {
  padding: 6px 12px;
  background: #2d2d2d;
  border-bottom: 1px solid #3c3c3c;
  font-size: 12px;
  color: #ccc;
}

.current-file {
  font-family: Consolas, monospace;
}

/* 手机竖屏适配 */
@media (max-width: 768px) {
  .editor-page { height: 100dvh; }
  .editor-header { padding: 6px 8px; flex-wrap: wrap; gap: 4px; }
  .header-left { gap: 2px; flex-wrap: wrap; }
  .back-btn, .up-btn, .toggle-btn { padding: 2px 6px !important; font-size: 12px !important; }
  .header-title { font-size: 13px; }
  .path-display { display: none; }
  .header-actions :deep(.ivu-btn) { font-size: 11px; padding: 0 6px; }
  .file-tree-panel { position: fixed; top: 0; left: 0; bottom: 40px; z-index: 10; width: 80vw; max-width: 300px; }
  .code-editor-panel { }
  .editor-wrapper :deep(.cm-editor) { font-size: 12px; }
  .editor-wrapper :deep(.cm-content) { font-size: 12px !important; }
  .editor-footer { font-size: 11px; padding: 2px 8px; }
}

.editor-footer {
  display: flex;
  justify-content: space-between;
  padding: 4px 12px;
  background: #007acc;
  font-size: 12px;
}

.save-status {
  opacity: 0.8;
}
</style>
