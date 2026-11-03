<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { useTreeStore } from '../store/tree'

const props = defineProps({ nodeId: { type: String, required: true } })
const store = useTreeStore()

const node = computed(() => store.nodeMap[props.nodeId])
const sending = computed(() => store.streamingNodeIds.includes(props.nodeId))
const childCount = computed(() => (store.childrenMap[props.nodeId] || []).length)
const descendantCount = computed(() => {
  const doomed = new Set([props.nodeId])
  let changed = true
  while (changed) {
    changed = false
    for (const n of store.nodes) {
      if (doomed.has(n.parentId) && !doomed.has(n.nodeId)) { doomed.add(n.nodeId); changed = true }
    }
  }
  return doomed.size - 1
})

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
const renderMd = (s) => md.render(s || '')

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
async function removeSelf() {
  const n = descendantCount.value
  try {
    await ElMessageBox.confirm(
      `将删除该节点${n > 0 ? `及其 ${n} 个子孙节点` : ''}，且不可恢复。确认删除？`,
      '删除节点',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    const count = await store.removeNode(props.nodeId)
    ElMessage.success(`已删除 ${count} 个节点`)
  } catch (e) { /* 取消 */ }
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
  <div v-if="node" class="chat-node" :class="{ collapsed: node.isCollapsed }">
    <header class="node-header" :class="node.parentId ? 'is-branch' : 'is-root'">
      <span class="node-icon">{{ node.parentId ? '🌿' : '🌱' }}</span>
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
      <el-tooltip v-if="node.parentId" content="精简：仅使用选中片段作为上下文" placement="top">
        <span class="mode-chip" :class="{ active: node.contextMode === 'simple' }" @click="setMode('simple')">精简</span>
      </el-tooltip>
      <el-tooltip v-if="node.parentId" content="完整：继承父节点全部对话 + 选中片段" placement="top">
        <span class="mode-chip" :class="{ active: node.contextMode === 'full' }" @click="setMode('full')">完整</span>
      </el-tooltip>
      <el-tooltip :content="node.isCollapsed ? '展开子树' : '折叠子树'" placement="top">
        <span class="hdr-btn" @click="toggleCollapse">{{ node.isCollapsed ? '➕' : '➖' }}</span>
      </el-tooltip>
      <el-dropdown trigger="click" @command="cmd => cmd === 'rename' ? startRename() : cmd === 'collapse' ? toggleCollapse() : removeSelf()">
        <span class="node-menu-btn">⋮</span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="rename">✏️ 重命名</el-dropdown-item>
            <el-dropdown-item command="collapse">
              {{ node.isCollapsed ? `📂 展开子树${childCount ? `（${childCount}）` : ''}` : `📦 折叠子树${descendantCount ? `（${descendantCount}）` : ''}` }}
            </el-dropdown-item>
            <el-dropdown-item command="delete" divided>🗑️ 删除（含子树）</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </header>

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
  </div>
</template>

<script>
export default {
  directives: {
    focus: { mounted: (el) => el.focus() }
  }
}
</script>
