<template>
  <!-- 悬浮球 / 迷你对话面板 -->
  <div class="mini-root" :class="{ expanded }">
    <button v-if="!expanded" class="mini-ball" title="快速对话" @click="expand">
      <svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">
        <path d="M4 4h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9l-5 4V6a2 2 0 0 1 2-2z"
              fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round" />
        <circle cx="8.5" cy="10.5" r="1.1" fill="currentColor" />
        <circle cx="12" cy="10.5" r="1.1" fill="currentColor" />
        <circle cx="15.5" cy="10.5" r="1.1" fill="currentColor" />
      </svg>
    </button>

    <div v-else class="mini-panel">
      <header class="mini-head">
        <span class="mini-dot"></span>
        <b>快速对话</b>
        <span class="mini-tree">{{ treeTitle || '正在准备…' }}</span>
        <div class="mini-ops">
          <button title="在主窗口打开" @click="openMain">⤢</button>
          <button title="收起为悬浮球" @click="collapse">—</button>
        </div>
      </header>

      <div ref="listEl" class="mini-list">
        <div v-if="!messages.length" class="mini-empty">
          <p>💬 直接提问，AI 会接着这个画布继续聊</p>
          <p class="mini-sub">内容会保存到画布「{{ treeTitle || '悬浮速记' }}」</p>
        </div>
        <div v-for="(m, i) in messages" :key="i" class="mini-msg" :class="m.role">
          <div class="mini-bubble" v-html="renderMd(m.content) || (m.role === 'assistant' && sending && i === messages.length - 1 ? '<span class=typing>▍</span>' : '')"></div>
        </div>
      </div>

      <div class="mini-input">
        <textarea
          v-model="draft"
          rows="2"
          placeholder="输入问题，Enter 发送（Shift+Enter 换行）"
          @keydown.enter.exact.prevent="send"
        ></textarea>
        <button class="mini-send" :disabled="sending || !draft.trim()" @click="send">
          {{ sending ? '…' : '发送' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, nextTick, onMounted } from 'vue'
import MarkdownIt from 'markdown-it'
import { createTree, getTree, sendQuestionStream } from '../api'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
const renderMd = (s) => md.render(s || '')

const MINI_KEY = 'bcc:miniTreeId'
const MINI_TITLE = '悬浮速记'

const expanded = ref(false)
const sending = ref(false)
const draft = ref('')
const messages = ref([])
const listEl = ref(null)
const treeId = ref('')
const treeTitle = ref('')
let nodeId = ''

const api = () => (window.pywebview && window.pywebview.api) || null

function scrollBottom() {
  nextTick(() => {
    if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
  })
}

async function expand() {
  const a = api()
  if (a && a.toggle_mini) await a.toggle_mini(true)
  expanded.value = true
  await ensureTree()
  scrollBottom()
}

async function collapse() {
  expanded.value = false
  const a = api()
  if (a && a.toggle_mini) await a.toggle_mini(false)
}

async function openMain() {
  const a = api()
  if (a && a.open_main) await a.open_main(treeId.value)
  await collapse()
}

/** 取用/创建「悬浮速记」画布，并取它的根节点作为对话载体 */
async function ensureTree() {
  if (treeId.value && nodeId) return
  let id = localStorage.getItem(MINI_KEY) || ''
  if (id) {
    try {
      const t = await getTree(id)
      bindTree(t)
      return
    } catch (e) { /* 画布已被删除，重建 */ }
  }
  const created = await createTree(MINI_TITLE)
  localStorage.setItem(MINI_KEY, created.treeId)
  bindTree(created)
}

function bindTree(tree) {
  treeId.value = tree.treeId
  treeTitle.value = tree.title
  const root = (tree.nodeList || []).find((n) => !n.parentId) || (tree.nodeList || [])[0]
  nodeId = root ? root.nodeId : ''
  messages.value = (root && root.messages ? root.messages : []).map((m) => ({
    role: m.role, content: m.content
  }))
}

async function send() {
  const content = draft.value.trim()
  if (!content || sending.value) return
  await ensureTree()
  if (!nodeId) return
  draft.value = ''
  messages.value.push({ role: 'user', content })
  const ai = reactive({ role: 'assistant', content: '' })
  messages.value.push(ai)
  sending.value = true
  scrollBottom()
  try {
    await sendQuestionStream(treeId.value, nodeId, content, (chunk) => {
      ai.content += chunk
      scrollBottom()
    })
  } catch (e) {
    if (!ai.content) ai.content = `⚠️ ${e.message || '请求失败'}`
    else ai.content += `\n\n⚠️ ${e.message || '请求中断'}`
  } finally {
    sending.value = false
    scrollBottom()
    // 与后端落库内容对齐（后端会把本轮问答写入节点）
    try {
      const t = await getTree(treeId.value)
      bindTree(t)
      scrollBottom()
    } catch (e) { /* ignore */ }
  }
}

onMounted(async () => {
  // 悬浮球窗口默认收起；主窗口里不该出现此组件
  try { await ensureTree() } catch (e) { /* 后端未就绪时静默 */ }
})
</script>

<style scoped>
.mini-root {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  overflow: hidden;
}

/* ---------- 悬浮球 ---------- */
.mini-ball {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  border: none;
  cursor: pointer;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(145deg, #3d7bff, #2f5fd0);
  box-shadow: 0 6px 18px rgba(47, 95, 208, .45), 0 0 0 1px rgba(255, 255, 255, .25) inset;
  transition: transform .16s ease, box-shadow .16s ease;
  -webkit-user-select: none;
  user-select: none;
}
.mini-ball:hover { transform: scale(1.07); box-shadow: 0 8px 22px rgba(47, 95, 208, .55), 0 0 0 1px rgba(255,255,255,.3) inset; }
.mini-ball:active { transform: scale(.96); }

/* ---------- 展开面板 ---------- */
.mini-root.expanded {
  background: #fff;
  border-radius: 14px;
  align-items: stretch;
  justify-content: flex-start;
  box-shadow: 0 10px 30px rgba(16, 24, 40, .16);
  overflow: hidden;
}
.mini-panel { display: flex; flex-direction: column; width: 100%; height: 100%; background: #fff; }

.mini-head {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid #eef0f4;
  background: #fafbfc;
  flex-shrink: 0;
}
.mini-dot { width: 8px; height: 8px; border-radius: 50%; background: #00b42a; box-shadow: 0 0 0 3px rgba(0,180,42,.15); }
.mini-head b { font-size: 13px; color: #1f2329; font-weight: 600; }
.mini-tree {
  font-size: 11px; color: #8a94a6; max-width: 130px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.mini-ops { margin-left: auto; display: flex; gap: 4px; }
.mini-ops button {
  width: 24px; height: 24px; border: none; border-radius: 6px; cursor: pointer;
  background: transparent; color: #6b7280; font-size: 14px; line-height: 1;
}
.mini-ops button:hover { background: #eef2ff; color: #2f5fd0; }

.mini-list { flex: 1; overflow-y: auto; padding: 14px; background: #fff; }
.mini-empty { color: #8a94a6; font-size: 12.5px; text-align: center; margin-top: 60px; line-height: 1.9; }
.mini-empty .mini-sub { font-size: 11.5px; color: #b0b7c3; }

.mini-msg { margin-bottom: 12px; display: flex; }
.mini-msg.user { justify-content: flex-end; }
.mini-bubble {
  max-width: 88%;
  padding: 9px 12px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.7;
  word-break: break-word;
}
.mini-msg.user .mini-bubble { background: #2f5fd0; color: #fff; border-bottom-right-radius: 3px; }
.mini-msg.assistant .mini-bubble { background: #f5f6f8; color: #1f2329; border-bottom-left-radius: 3px; }
.mini-bubble :deep(p) { margin: 0 0 8px; }
.mini-bubble :deep(p:last-child) { margin-bottom: 0; }
.mini-bubble :deep(code) { background: rgba(0,0,0,.06); padding: 1px 4px; border-radius: 4px; font-size: 12px; }
.mini-bubble :deep(pre) { background: #1f2329; color: #e6edf3; padding: 10px; border-radius: 8px; overflow-x: auto; font-size: 12px; }
.mini-bubble :deep(pre code) { background: none; color: inherit; padding: 0; }
.mini-bubble :deep(ul), .mini-bubble :deep(ol) { padding-left: 18px; margin: 6px 0; }
.mini-bubble :deep(.typing) { animation: blink 1s steps(2) infinite; }
@keyframes blink { 50% { opacity: 0; } }

.mini-input {
  display: flex; gap: 8px; align-items: flex-end;
  padding: 10px 12px;
  border-top: 1px solid #eef0f4;
  background: #fafbfc;
  flex-shrink: 0;
}
.mini-input textarea {
  flex: 1; resize: none; border: 1px solid #e3e6ec; border-radius: 8px;
  padding: 8px 10px; font-size: 13px; line-height: 1.5; font-family: inherit;
  outline: none; max-height: 90px;
}
.mini-input textarea:focus { border-color: #2f5fd0; box-shadow: 0 0 0 3px rgba(47,95,208,.12); }
.mini-send {
  height: 36px; padding: 0 14px; border: none; border-radius: 8px;
  background: #2f5fd0; color: #fff; font-size: 13px; cursor: pointer;
}
.mini-send:disabled { background: #c8d3e8; cursor: not-allowed; }
</style>
