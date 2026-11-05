<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useVueFlow, Handle, Position } from '@vue-flow/core'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { useTreeStore } from '../store/tree'
import { useNotesStore } from '../store/notes'

const props = defineProps({
  nodeId: { type: String, required: true },
  /** 是否为悬浮球「快速对话」的承载节点（专属画布的根节点） */
  quickChat: { type: Boolean, default: false }
})
const emit = defineEmits(['menu', 'child-created'])
const store = useTreeStore()
const notesStore = useNotesStore()
const { viewport } = useVueFlow()

const node = computed(() => store.nodeMap[props.nodeId])
const sending = computed(() => store.streamingNodeIds.includes(props.nodeId))
const childCount = computed(() => (store.childrenMap[props.nodeId] || []).length)
const descendantCount = computed(() => store.subtreeIds(props.nodeId).length - 1)
const isRoot = computed(() => !node.value?.parentId)

/** 节点状态：生成中 / 报错 / 已完成 / 待编辑 */
const status = computed(() => {
  const n = node.value
  if (!n) return { key: 'empty', text: '待编辑' }
  if (sending.value) return { key: 'busy', text: '生成中' }
  const last = [...(n.messages || [])].reverse().find(m => m.role === 'assistant')
  if (last && String(last.content).startsWith('⚠️')) return { key: 'error', text: '报错' }
  if (!(n.messages || []).length) return { key: 'empty', text: '待编辑' }
  return { key: 'done', text: '已完成' }
})
const isEmpty = computed(() => !(node.value?.messages || []).length)

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
const renderMd = (s) => md.render(s || '')
const plainText = (s) => (s || '').replace(/[#>*`\-]/g, ' ').replace(/\s+/g, ' ').trim()

const draft = ref('')
const editing = ref(false)
const titleDraft = ref('')
const msgsRef = ref(null)

async function send() {
  const content = draft.value.trim()
  if (!content || sending.value) return
  draft.value = ''
  await store.send(props.nodeId, content)
}

function startRename() {
  titleDraft.value = node.value.title
  editing.value = true
}
async function saveRename() {
  editing.value = false
  const t = titleDraft.value.trim()
  if (t && t !== node.value.title) store.patchNode(props.nodeId, { title: t })
}
function toggleCollapse() {
  store.patchNode(props.nodeId, { isCollapsed: !node.value.isCollapsed })
}
function setMode(m) {
  if (node.value.contextMode !== m) store.patchNode(props.nodeId, { contextMode: m })
}
function retry() {
  const msgs = node.value.messages
  if (msgs.length < 2) return
  const lastUser = [...msgs].reverse().find(m => m.role === 'user')
  if (!lastUser) return
  msgs.splice(msgs.length - 2, 2)
  store.send(props.nodeId, lastUser.content)
}
function toggleStar() {
  store.toggleStar(props.nodeId)
}

/** 整条消息收藏进笔记（划词收藏的补充：不想挑句子时直接存整条） */
function collectMessage(m) {
  const n = node.value
  if (!n || !m?.content?.trim()) return
  const item = notesStore.add(m.content, {
    treeId: store.treeId,
    treeTitle: store.treeTitle,
    nodeId: n.nodeId,
    nodeTitle: n.title,
    role: m.role
  })
  if (item) {
    ElMessage.success({
      message: m.role === 'user' ? '已把我的提问收藏到笔记 📝' : '已把这条回答收藏到笔记 📝',
      duration: 1600
    })
  }
}

/** 右键菜单：交给外层统一渲染（新增子分支 / 复制 / 折叠 / 导出 / 删除） */
function onContextMenu(e) {
  emit('menu', { nodeId: props.nodeId, x: e.clientX, y: e.clientY })
}

/** ＋ 快速新建子分支：继承父节点完整对话，2 次点击内完成 */
async function addChild() {
  if (!node.value) return
  try {
    const child = await store.createChild(props.nodeId, '', 'full', '新分支')
    ElMessage.success('已新建子分支，去新节点继续追问')
    emit('child-created', child?.nodeId)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

// ---------- 悬浮 300ms 显示全文预览 ----------
const preview = ref(false)
let previewTimer = null
function enterPreview() {
  clearTimeout(previewTimer)
  previewTimer = setTimeout(() => {
    if ((node.value?.messages || []).length) preview.value = true
  }, 300)
}
function leavePreview() {
  clearTimeout(previewTimer)
  preview.value = false
}

// ---------- 卡片尺寸：可拖拽调整并持久化 ----------
const DEFAULT_W = 340, DEFAULT_H = 380
const MIN_W = 260, MIN_H = 240, MAX_W = 1200, MAX_H = 1600
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

// 八向：四条边 + 四个角，dir 由 n/s/e/w 组合而成
const RESIZE_DIRS = [
  { dir: 'n', title: '拖动调整高度' },
  { dir: 's', title: '拖动调整高度' },
  { dir: 'e', title: '拖动调整宽度' },
  { dir: 'w', title: '拖动调整宽度' },
  { dir: 'ne', title: '拖动调整大小' },
  { dir: 'nw', title: '拖动调整大小' },
  { dir: 'se', title: '拖动调整大小' },
  { dir: 'sw', title: '拖动调整大小' },
]

const resizing = ref(false)
const liveSize = ref(null)                       // 拖拽过程中的临时尺寸（含 x/y）
const savedSize = computed(() => {
  const s = node.value?.size
  return {
    w: clamp(Number(s?.w) || DEFAULT_W, MIN_W, MAX_W),
    h: clamp(Number(s?.h) || DEFAULT_H, MIN_H, MAX_H),
  }
})
const cardSize = computed(() => liveSize.value || savedSize.value)

function startResize(e, dir) {
  e.stopPropagation()
  e.preventDefault()
  const zoom = viewport?.value?.zoom || 1        // 画布缩放：屏幕位移需换算为节点位移
  const startX = e.clientX, startY = e.clientY
  const base = { ...cardSize.value, x: node.value?.x || 0, y: node.value?.y || 0 }
  resizing.value = true

  const onMove = (ev) => {
    const dx = (ev.clientX - startX) / zoom
    const dy = (ev.clientY - startY) / zoom
    let { w, h, x, y } = base

    if (dir.includes('e')) w = clamp(base.w + dx, MIN_W, MAX_W)
    if (dir.includes('s')) h = clamp(base.h + dy, MIN_H, MAX_H)
    if (dir.includes('w')) {                     // 拖左边：宽度变，右边界保持不动
      const nw = clamp(base.w - dx, MIN_W, MAX_W)
      x = base.x + (base.w - nw)
      w = nw
    }
    if (dir.includes('n')) {                     // 拖上边：高度变，下边界保持不动
      const nh = clamp(base.h - dy, MIN_H, MAX_H)
      y = base.y + (base.h - nh)
      h = nh
    }
    liveSize.value = { w, h, x, y }

    // 拖动左/上边时同步移动节点位置（仅本地，松手才写库）
    const n = node.value
    if (n && (n.x !== x || n.y !== y)) { n.x = x; n.y = y }
  }
  const onUp = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    resizing.value = false
    const next = liveSize.value
    liveSize.value = null
    if (!next) return
    const patch = {
      size: { w: Math.round(next.w), h: Math.round(next.h) },
    }
    if (dir.includes('w') || dir.includes('n')) {
      patch.x = Math.round(next.x)
      patch.y = Math.round(next.y)
    }
    const changed = Math.round(next.w) !== Math.round(base.w)
      || Math.round(next.h) !== Math.round(base.h)
      || (patch.x !== undefined && (Math.round(next.x) !== Math.round(base.x) || Math.round(next.y) !== Math.round(base.y)))
    if (changed) store.patchNode(props.nodeId, patch)
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}
function resetSize() {
  store.patchNode(props.nodeId, { size: { w: DEFAULT_W, h: DEFAULT_H } })
}

// 流式输出时滚动到底部
watch(
  () => node.value?.messages?.map(m => m.content.length).join(','),
  async () => {
    await nextTick()
    const el = msgsRef.value
    if (el) el.scrollTop = el.scrollHeight
  }
)
</script>

<template>
  <div
    v-if="node"
    class="chat-node"
    :class="{
      collapsed: node.isCollapsed,
      resizing,
      'is-empty': isEmpty && !node.isCollapsed,
      'is-error': status.key === 'error',
      'is-root': isRoot,
      'is-quick': quickChat
    }"
    :style="{ width: cardSize.w + 'px', height: node.isCollapsed ? 'auto' : cardSize.h + 'px' }"
    @contextmenu.prevent="onContextMenu"
  >
    <header
      class="node-header"
      :class="node.parentId ? 'is-branch' : 'is-root'"
      @mouseenter="enterPreview"
      @mouseleave="leavePreview"
    >
      <span class="node-icon">{{ node.parentId ? '🌿' : '🌱' }}</span>
      <span v-if="isRoot" class="node-badge badge-root">起始</span>
      <el-tooltip
        v-if="quickChat"
        content="悬浮球「快速对话」的内容就记在这个节点上，两处实时共用同一段对话"
        placement="top"
      >
        <span class="node-badge badge-quick">⚡ 快速对话</span>
      </el-tooltip>
      <template v-if="editing">
        <input
          v-model="titleDraft"
          class="title-input"
          @keydown.enter="saveRename"
          @blur="saveRename"
          v-focus
        />
      </template>
      <span v-else class="node-title" title="双击或点 ✏️ 重命名" @dblclick="startRename">{{ node.title }}</span>
      <span v-if="!editing" class="title-edit-btn" title="重命名" @click="startRename">✏️</span>
      <span v-if="node.isCollapsed && descendantCount" class="collapsed-count" :title="`已折叠 ${descendantCount} 个子孙节点`">
        ➕ {{ descendantCount }}
      </span>
      <el-tooltip :content="node.isCollapsed ? '展开子树' : '折叠子树'" placement="top">
        <span class="hdr-btn" @click="toggleCollapse">{{ node.isCollapsed ? '➕' : '➖' }}</span>
      </el-tooltip>
      <span class="node-menu-btn" title="更多操作（也可右键卡片）" @click.stop="onContextMenu({ clientX: $event.clientX, clientY: $event.clientY })">⋮</span>
    </header>

    <!-- 元信息行：上下文模式 + 状态徽标 + 收藏 + 快速建分支 -->
    <div v-if="!node.isCollapsed" class="meta-bar">
      <template v-if="node.parentId">
        <el-tooltip content="精简：仅使用选中片段作为上下文" placement="top">
          <span class="mode-chip" :class="{ active: node.contextMode === 'simple' }" @click="setMode('simple')">精简</span>
        </el-tooltip>
        <el-tooltip content="完整：继承父节点全部对话 + 选中片段" placement="top">
          <span class="mode-chip" :class="{ active: node.contextMode === 'full' }" @click="setMode('full')">完整</span>
        </el-tooltip>
      </template>
      <span class="status-badge" :class="'st-' + status.key">{{ status.text }}</span>
      <span class="hdr-btn star-btn" :class="{ on: node.starred }" :title="node.starred ? '取消收藏' : '收藏该节点'" @click="toggleStar">
        {{ node.starred ? '⭐' : '☆' }}
      </span>
      <span class="spacer"></span>
      <el-tooltip content="直接基于本节点的对话新建一个子分支" placement="top">
        <span class="add-child-btn" @click="addChild">＋ 子分支</span>
      </el-tooltip>
    </div>

    <div v-if="node.parentId && node.selectedContext" class="ctx-bar" :title="node.selectedContext">
      <span class="ctx-text">📌 {{ node.selectedContext }}</span>
    </div>

    <div ref="msgsRef" class="messages nodrag nowheel">
      <div v-if="!node.messages.length" class="empty-tip">
        {{ node.parentId ? '基于选中的片段，在这里继续追问…' : '输入你的第一个问题开始对话…' }}
      </div>
      <div v-for="(m, i) in node.messages" :key="i" class="msg" :class="m.role">
        <div v-if="m.role === 'user'" class="bubble user-bubble">{{ m.content }}</div>
        <div v-else class="assistant-wrap">
          <div
            class="bubble assistant-bubble md-body"
            :data-node-id="node.nodeId"
            v-html="renderMd(m.content) || (sending ? '<span class=typing>▍</span>' : '')"
          ></div>
          <div v-if="m.content.startsWith('⚠️')" class="retry-row">
            <el-button size="small" text type="primary" @click="retry">🔄 重试</el-button>
          </div>
        </div>
        <span
          class="msg-note-btn nodrag"
          :title="m.role === 'user' ? '把我的这条提问收藏到笔记' : '把这条回答收藏到笔记'"
          @click.stop="collectMessage(m)"
        >📝</span>
      </div>
    </div>

    <!-- 悬停 300ms 后的全文预览浮层（卡片内滚动） -->
    <div v-if="preview" class="node-preview" @mouseleave="leavePreview">
      <div class="np-title">📄 全文预览</div>
      <div class="np-body">
        <div v-for="(m, i) in node.messages" :key="i" class="np-msg">
          <span class="np-who">{{ m.role === 'user' ? '🙋 我' : '🤖 AI' }}</span>
          {{ plainText(m.content).slice(0, 2000) }}
        </div>
      </div>
    </div>

    <div class="input-bar nodrag">
      <el-input
        v-model="draft"
        type="textarea"
        :rows="2"
        resize="none"
        placeholder="输入问题，Enter 发送 / Shift+Enter 换行"
        @keydown.enter.exact.prevent="send"
      />
      <el-button type="primary" :loading="sending" class="send-btn" @click="send">发送</el-button>
    </div>

    <!-- 金字塔布局的连接锚点：上进下出（隐藏显示，仅作为连线端点） -->
    <Handle type="target" :position="Position.Top" :is-connectable="false" class="node-anchor" />
    <Handle type="source" :position="Position.Bottom" :is-connectable="false" class="node-anchor" />

    <!-- 拖拽调整卡片尺寸：四条边 + 四个角，任意方向自由缩放 -->
    <template v-if="!node.isCollapsed">
      <div
        v-for="h in RESIZE_DIRS"
        :key="h.dir"
        class="rs-handle nodrag"
        :class="'rs-' + h.dir"
        :title="h.title"
        @mousedown.stop.prevent="startResize($event, h.dir)"
      ></div>
    </template>
  </div>
</template>

<script>
export default {
  directives: {
    focus: { mounted: (el) => el.focus() }
  }
}
</script>
