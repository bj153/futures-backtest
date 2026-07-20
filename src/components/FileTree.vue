<template>
  <div class="file-tree">
    <div
      v-for="item in tree"
      :key="item.path"
      class="tree-item"
    >
      <div
        :class="['tree-node', { 'is-dir': item.is_dir, 'is-selected': selected === item.path }]"
        @click="onClick(item)"
      >
        <span v-if="item.is_dir" class="expand-icon" @click.stop="toggle(item)">
          {{ isExpanded(item) ? '📂' : '📁' }}
        </span>
        <span v-else class="file-icon">📄</span>
        <span class="node-name">{{ item.name }}</span>
      </div>
      <div v-if="item.is_dir && isExpanded(item)" class="tree-children">
        <FileTree :tree="item.children || []" :selected="selected" @select="$emit('select', $event)" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

interface FileNode {
  name: string
  path: string
  is_dir: boolean
  children?: FileNode[]
}

const props = defineProps<{
  tree: FileNode[]
  selected: string | null
}>()

const emit = defineEmits<{
  select: [node: FileNode]
}>()

const expandedPaths = ref<Set<string>>(new Set())

function isExpanded(item: FileNode): boolean {
  return expandedPaths.value.has(item.path)
}

function toggle(item: FileNode) {
  if (isExpanded(item)) {
    expandedPaths.value.delete(item.path)
  } else {
    expandedPaths.value.add(item.path)
  }
}

function onClick(item: FileNode) {
  if (item.is_dir) {
    toggle(item)
  } else {
    emit('select', item)
  }
}
</script>

<style scoped>
.file-tree {
  font-size: 13px;
}

.tree-node {
  display: flex;
  align-items: center;
  padding: 4px 8px 4px 12px;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}

.tree-node:hover {
  background: #2a2d2e;
}

.tree-node.is-selected {
  background: #094771;
}

.expand-icon, .file-icon {
  margin-right: 6px;
  font-size: 12px;
}

.node-name {
  overflow: hidden;
  text-overflow: ellipsis;
}

.tree-children {
  padding-left: 16px;
}
</style>
