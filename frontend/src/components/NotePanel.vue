<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useNotesStore } from '../store/notes'

const notes = useNotesStore()

const draft = ref('')
const draftRef = ref(null)
const editingId = ref('')
const editDraft = ref('')
const expanded = ref({})        // 长笔记展开状态
const filter = ref('all')       // 分类筛选：all / node / excerpt / manual
const now = ref(Date.now())
let ticker = null

onMounted(() => {
  ticker = setInterval(() => { now.value = Date.now() }, 30000)
})
onBeforeUnmount(() => {
  clearInterval(ticker)
})

// 打开面板时把搜索词与筛选清掉，避免"上次搜完忘了"看不到全部
watch(() => notes.panelOpen, (open) => {
  if (open) {
    notes.keyword = ''
    filter.value = 'all'
    nextTick(() => draftRef.value?.focus())
  } else {
    editingId.value = ''
  }
})

function relTime(iso) {
  const t = new Date(iso).getTime()
  if (!t || Number.isNaN(t)) return ''
  const d = now.value - t
  if (d < 60000) return '刚刚'
  if (d < 3600000) return Math.floor(d / 60000) + ' 分钟前'
  if (d < 86400000) return Math.floor(d / 3600000) + ' 小时前'
  if (d < 604800000) return Math.floor(d / 86400000) + ' 天前'
  const dt = new Date(t)
  const sameYear = dt.getFullYear() === new Date(now.value).getFullYear()
  const md = `${dt.getMonth() + 1}-${String(dt.getDate()).padStart(2, '0')}`
  return sameYear ? md : `${dt.getFullYear()}-${md}`
}

function sourceLabel(n) {
  if (!n.source) return '✍️ 手动记录'
  if (n.kind === 'node' || n.source.role === 'node') {
    return `⭐ 「${n.source.treeTitle}」· ${n.source.nodeTitle}`
  }
  const who = n.source.role === 'user' ? '我' : 'AI'
  return `📎 「${n.source.treeTitle}」· ${n.source.nodeTitle} · ${who}`
}

function sourceTitle(n) {
  if (!n.source) return '自己写下的备忘'
  if (n.kind === 'node' || n.source.role === 'node') {
    return `收藏的整个节点：来自画布「${n.source.treeTitle}」的「${n.source.nodeTitle}」（收藏时的对话快照）`
  }
  return `来自画布「${n.source.treeTitle}」的节点「${n.source.nodeTitle}」（${n.source.role === 'user' ? '我的提问' : 'AI 回答'}）`
}

const preview = (text) => (text.length > 220 ? text.slice(0, 220) + '…' : text)

function saveNew() {
  const text = draft.value.trim()
  if (!text) return
  notes.add(text, null)
  draft.value = ''
  ElMessage.success('已记下')
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch (e) {
    // pywebview / 非安全上下文下 clipboard 可能不可用，降级到 textarea
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.cssText = 'position:fixed;left:-9999px;top:0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      ElMessage.success('已复制')
    } catch (err) {
      ElMessage.error('复制失败，请手动选中文字复制')
    }
  }
}

function startEdit(n) {
  editingId.value = n.id
  editDraft.value = n.content
  nextTick(() => {
    const el = document.querySelector('.np-item.editing textarea')
    if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length) }
  })
}
function saveEdit() {
  if (!editingId.value) return
  if (!editDraft.value.trim()) { ElMessage.warning('内容不能为空'); return }
  notes.update(editingId.value, editDraft.value)
  editingId.value = ''
  editDraft.value = ''
  ElMessage.success('已保存修改')
}
function cancelEdit() {
  editingId.value = ''
  editDraft.value = ''
}

async function remove(n) {
  try {
    await ElMessageBox.confirm(
      `确定删除这条笔记？\n\n${preview(n.content).slice(0, 60)}`,
      '删除笔记',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    notes.remove(n.id)
    ElMessage.success('已删除')
  } catch (e) { /* 取消 */ }
}

async function clearAll() {
  if (!notes.count) return
  try {
    await ElMessageBox.confirm(
      `将删除全部 ${notes.count} 条笔记，且无法恢复。`,
      '清空笔记',
      { confirmButtonText: '全部清空', cancelButtonText: '取消', type: 'warning' }
    )
    notes.clearAll()
    ElMessage.success('笔记已清空')
  } catch (e) { /* 取消 */ }
}

// 关键词搜索 + 分类筛选 的组合结果
const list = computed(() => {
  return filter.value === 'all'
    ? notes.filtered
    : notes.filtered.filter(n => n.kind === filter.value)
})

const filters = computed(() => ([
  { key: 'all', label: '全部', count: notes.count },
  { key: 'node', label: '⭐ 节点', count: notes.nodeCount },
  { key: 'excerpt', label: '📌 摘录', count: notes.excerptCount },
  { key: 'manual', label: '✍️ 手动', count: notes.count - notes.nodeCount - notes.excerptCount }
]))

const isEmpty = computed(() => notes.count === 0)
const noMatch = computed(() => notes.count > 0 && list.value.length === 0)
const filterName = computed(() => filters.value.find(f => f.key === filter.value)?.label || '')
</script>

<template>
  <transition name="note-slide">
    <aside v-if="notes.panelOpen" class="note-panel">
      <header class="np-head">
        <span class="np-title">📝 我的笔记</span>
        <span class="np-count">{{ notes.count }}</span>
        <span class="spacer"></span>
        <span class="np-close" title="收起笔记（Esc）" @click="notes.close()">✕</span>
      </header>

      <div class="np-search">
        <input v-model="notes.keyword" type="text" placeholder="搜索内容、画布或节点名…" />
        <span v-if="notes.keyword" class="np-search-clear" @click="notes.keyword = ''">✕</span>
      </div>

      <div class="np-filters">
        <button
          v-for="f in filters"
          :key="f.key"
          class="np-chip"
          :class="{ on: filter === f.key }"
          @click="filter = f.key"
        >{{ f.label }} <i v-if="f.count">{{ f.count }}</i></button>
      </div>

      <div class="np-compose">
        <textarea
          ref="draftRef"
          v-model="draft"
          rows="3"
          maxlength="20000"
          placeholder="随手记一条：灵感、提示词、待查的问题…  Ctrl + Enter 保存"
          @keydown.ctrl.enter.prevent="saveNew"
          @keydown.meta.enter.prevent="saveNew"
        ></textarea>
        <div class="np-compose-bar">
          <span class="np-hint">{{ draft.length ? draft.length + ' 字' : '也能在对话里划线收藏' }}</span>
          <button class="np-btn primary" :disabled="!draft.trim()" @click="saveNew">记下来</button>
        </div>
      </div>

      <div class="np-list">
        <div v-if="isEmpty" class="np-empty">
          <div class="np-empty-icon">🗒️</div>
          <p>还没有笔记。</p>
          <p class="np-empty-sub">在 AI 回答里划选一段文字、悬停消息点 📝、或右键节点「收藏节点」，都会存到这里。</p>
        </div>
        <div v-else-if="noMatch && notes.keyword" class="np-empty">
          <div class="np-empty-icon">🔍</div>
          <p>没有匹配「{{ notes.keyword }}」的笔记。</p>
        </div>
        <div v-else-if="noMatch" class="np-empty">
          <div class="np-empty-icon">🗂️</div>
          <p>{{ filterName }}分类下还没有笔记。</p>
        </div>

        <article
          v-for="n in list"
          :key="n.id"
          class="np-item"
          :class="{ fresh: n.id === notes.lastAddedId, editing: n.id === editingId }"
        >
          <template v-if="n.id === editingId">
            <textarea
              v-model="editDraft"
              class="np-edit"
              rows="5"
              maxlength="20000"
              @keydown.ctrl.enter.prevent="saveEdit"
              @keydown.meta.enter.prevent="saveEdit"
              @keydown.esc.prevent.stop="cancelEdit"
            ></textarea>
            <div class="np-item-actions editing-actions">
              <button class="np-mini primary" @click="saveEdit">保存</button>
              <button class="np-mini" @click="cancelEdit">取消</button>
            </div>
          </template>

          <template v-else>
            <div class="np-item-body" :class="{ expanded: expanded[n.id] }">{{ n.content }}</div>
            <span
              v-if="n.content.length > 220"
              class="np-more"
              @click="expanded[n.id] = !expanded[n.id]"
            >{{ expanded[n.id] ? '收起' : '展开全文' }}</span>

            <div class="np-item-meta" :title="sourceTitle(n)">
              <span class="np-src" :class="n.kind">{{ sourceLabel(n) }}</span>
              <span class="np-time">{{ relTime(n.createdAt) }}</span>
            </div>

            <div class="np-item-actions">
              <button class="np-mini" title="复制全文" @click="copy(n.content)">📋 复制</button>
              <button class="np-mini" title="编辑这条笔记" @click="startEdit(n)">✏️ 编辑</button>
              <button class="np-mini danger" title="删除这条笔记" @click="remove(n)">🗑️ 删除</button>
            </div>
          </template>
        </article>
      </div>

      <footer class="np-foot">
        <span class="np-foot-tip">保存在本机浏览器，刷新不丢</span>
        <span v-if="notes.count" class="np-clear" @click="clearAll">清空全部</span>
      </footer>
    </aside>
  </transition>
</template>
