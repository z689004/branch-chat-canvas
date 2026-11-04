<template>
  <!-- 悬浮球窗口：圆球 / 右键菜单 / 迷你对话面板 -->
  <div
    class="mini-root"
    :class="{ expanded, 'menu-open': menuOpen, dragging }"
    @mousedown.self="onRootDown"
    @contextmenu.prevent="openMenu"
  >
    <!-- ============ 圆球 ============ -->
    <button
      v-if="!expanded"
      class="mini-ball"
      title="左键打开快速对话，按住可拖动，右键更多操作"
      @pointerdown.left.prevent.stop="onBallDown"
      @contextmenu.prevent.stop="openMenu"
    >
    </button>

    <!-- ============ 右键菜单（窗口临时放大，球固定在右下角） ============ -->
    <transition name="bm">
      <div v-if="menuOpen && !expanded" class="ball-menu" @mousedown.stop @contextmenu.prevent.stop>
        <button class="bm-item" @click="quickChat"><span>⚡</span>快速对话</button>
        <button class="bm-item" @click="menuOpenMain"><span>🖥️</span>打开主界面</button>
        <button class="bm-item" @click="menuHideBall"><span>👁️</span>隐藏悬浮球</button>
        <div class="bm-sep"></div>
        <button class="bm-item danger" @click="menuQuit"><span>⏻</span>退出程序</button>
        <div class="bm-tip">左键直接快速对话，按住可拖动<br />点击空白处或按 Esc 关闭菜单</div>
      </div>
    </transition>

    <!-- ============ 迷你对话面板 ============ -->
    <div v-if="expanded" class="mini-panel">
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
// 与后端 MENU_SIZE 保持一致：右键菜单展开时需要的窗口尺寸
const MENU_W = 212
const MENU_H = 306

const expanded = ref(false)
const menuOpen = ref(false)
const dragging = ref(false)
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

// ---------------- 圆球交互 ----------------

const CLICK_TOL = 4       // 位移小于该值视为"点击"
const DRAG_INTERVAL = 28  // 拖拽移动节流（毫秒）

let dragState = null

/**
 * 按下圆球：捕获指针后进入拖拽。
 * - 移动 → 实时移动窗口（屏幕坐标差值，绝对定位不累积误差）
 * - 未移动（点击）→ 唤起 / 收起主窗口
 */
async function onBallDown(e) {
  if (e.button !== 0) return
  if (menuOpen.value) {
    await closeMenu()
    return
  }
  const a = api()
  if (!a || !a.toggle_main) return
  try { e.currentTarget.setPointerCapture(e.pointerId) } catch (err) { /* ignore */ }
  dragState = { startX: e.screenX, startY: e.screenY, moved: false, lastMove: 0, winX: null, winY: null }
  dragging.value = true
  if (a.get_ball_pos) {
    try {
      const p = await a.get_ball_pos()
      if (dragState) { dragState.winX = p.x; dragState.winY = p.y }
    } catch (err) { /* ignore */ }
  }
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', onDragUp)
  window.addEventListener('pointercancel', onDragUp)
}

function onDragMove(e) {
  if (!dragState) return
  const dx = e.screenX - dragState.startX
  const dy = e.screenY - dragState.startY
  if (!dragState.moved && Math.abs(dx) < CLICK_TOL && Math.abs(dy) < CLICK_TOL) return
  dragState.moved = true
  const now = performance.now()
  if (now - dragState.lastMove < DRAG_INTERVAL) return
  dragState.lastMove = now
  const a = api()
  if (a && a.move_ball && dragState.winX != null) {
    a.move_ball(dragState.winX + dx, dragState.winY + dy)
  }
}

async function onDragUp() {
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragUp)
  window.removeEventListener('pointercancel', onDragUp)
  const st = dragState
  dragState = null
  dragging.value = false
  const a = api()
  if (!st || !a) return
  if (!st.moved) {
    // 点击：直接进入快速会话（打开主界面在右键菜单里）
    quickChat()
  } else if (a.end_drag) {
    // 拖完：贴边吸附 + 记住位置
    await a.end_drag()
  }
}

async function openMenu() {
  if (menuOpen.value || expanded.value) return
  // 先切视图再扩窗口：避免窗口已变大而球还铺满整个窗口的瞬态
  menuOpen.value = true
  const a = api()
  if (a && a.expand_menu) {
    try { await a.expand_menu(MENU_W, MENU_H) } catch (e) { /* ignore */ }
  }
}

async function closeMenu() {
  if (!menuOpen.value) return
  menuOpen.value = false
  const a = api()
  if (a && a.collapse_menu) {
    try { await a.collapse_menu() } catch (e) { /* ignore */ }
  }
}

function onRootDown() {
  if (menuOpen.value) closeMenu()
}

// ---------------- 右键菜单项 ----------------

async function quickChat() {
  menuOpen.value = false
  expanded.value = true
  const a = api()
  if (a && a.toggle_mini) await a.toggle_mini(true)
  try { await ensureTree() } catch (e) { /* 后端未就绪 */ }
  scrollBottom()
}

async function menuOpenMain() {
  await closeMenu()
  const a = api()
  if (a && a.open_main) await a.open_main(treeId.value || '')
}

async function menuHideBall() {
  await closeMenu()
  const a = api()
  if (a && a.show_ball) await a.show_ball(false)
}

async function menuQuit() {
  const a = api()
  if (a && a.quit_app) await a.quit_app()
}

// ---------------- 面板 ----------------

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
  const id = localStorage.getItem(MINI_KEY) || ''
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

/** 窗口被后端收回成球尺寸（如菜单被外部点击关闭）时，同步收起菜单视图 */
function onWinResize() {
  if (menuOpen.value && window.innerWidth <= 120 && window.innerHeight <= 120) {
    menuOpen.value = false
  }
}

function onKeyDown(e) {
  if (e.key === 'Escape' && menuOpen.value) closeMenu()
}

onMounted(async () => {
  // 供后端在"点菜单外部"时回调，收起菜单视图
  window.__closeBallMenu = () => { menuOpen.value = false }
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('resize', onWinResize)
  // 悬浮球窗口默认收起；主窗口里不该出现此组件
  try { await ensureTree() } catch (e) { /* 后端未就绪时静默 */ }
})
</script>

<style scoped>
.mini-root {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 与应用图标边缘同色系：图标透明四角与窗口系统圆角之间的细缝不可见 */
  background: linear-gradient(145deg, #0FB47E, #067D5A);
  overflow: hidden;
  font-family: 'PingFang SC', 'Microsoft YaHei', 'Segoe UI', sans-serif;
}

/* ---------- 悬浮球：直接使用应用图标（squircle），铺满窗口 ---------- */
.mini-ball {
  width: 100%;
  height: 100%;
  padding: 0;
  border: none;
  border-radius: 10px; /* 与窗口系统圆角自然衔接 */
  cursor: grab;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  /* contain + 图标同款渐变兜底：窗口尺寸瞬间异常时图标也不会被拉伸 */
  background:
    url('/icon-ball.png') center / contain no-repeat,
    linear-gradient(145deg, #0FB47E, #067D5A);
  transition: filter .16s ease;
  -webkit-user-select: none;
  user-select: none;
}
/* 窗口四角由系统圆角裁切，动画只用亮度反馈（不位移、不缩放） */
.mini-ball:hover { filter: brightness(1.09); }
.mini-ball:active { filter: brightness(.94); cursor: grabbing; }
.mini-root.dragging .mini-ball { filter: brightness(.96); cursor: grabbing; }

/* ---------- 右键菜单：窗口即菜单，圆角浮层 ---------- */
.mini-root.menu-open {
  align-items: stretch;
  justify-content: stretch;
  background: var(--bg-panel);
}
/* 菜单态窗口整体就是菜单面板，球隐藏避免挤压布局 */
.mini-root.menu-open .mini-ball { display: none; }

.ball-menu {
  width: 100%;
  height: 100%;
  padding: 10px;
  border-radius: 14px;
  background: var(--bg-panel);
  display: flex;
  flex-direction: column;
  gap: 2px;
  user-select: none;
  box-sizing: border-box;
  overflow: hidden;
}
.bm-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 9px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  font-family: inherit;
}
.bm-item span { font-size: 13px; width: 16px; text-align: center; }
.bm-item:hover { background: var(--bg-subtle); color: var(--primary); }
.bm-item.danger:hover { background: rgba(245, 63, 63, .1); color: var(--danger); }
.bm-sep { height: 1px; background: var(--border-soft); margin: 4px 6px; }
.bm-tip {
  margin-top: auto;
  padding: 6px 8px 2px;
  font-size: 10.5px;
  line-height: 1.6;
  color: var(--text-faint);
}

.bm-enter-active, .bm-leave-active { transition: opacity .12s ease, transform .12s ease; }
.bm-enter-from, .bm-leave-to { opacity: 0; transform: translateY(6px); }

/* ---------- 展开面板：与应用同色系，圆角浮层 ---------- */
.mini-root.expanded {
  align-items: stretch;
  justify-content: flex-start;
  background: var(--bg-panel);
  padding: 0;
}
.mini-panel {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  background: var(--bg-panel);
  border-radius: 14px;
  overflow: hidden;
}

.mini-head {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-soft);
  background: var(--bg-sub);
  flex-shrink: 0;
}
.mini-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--success); box-shadow: 0 0 0 3px rgba(0, 180, 42, .15); }
.mini-head b { font-size: 13px; color: var(--text); font-weight: 600; }
.mini-tree {
  font-size: 11px; color: var(--text-dim); max-width: 130px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.mini-ops { margin-left: auto; display: flex; gap: 4px; }
.mini-ops button {
  width: 24px; height: 24px; border: none; border-radius: 6px; cursor: pointer;
  background: transparent; color: var(--text-dim); font-size: 14px; line-height: 1;
}
.mini-ops button:hover { background: var(--bg-subtle); color: var(--primary); }

.mini-list { flex: 1; overflow-y: auto; padding: 14px; background: var(--bg-panel); }
.mini-empty { color: var(--text-dim); font-size: 12.5px; text-align: center; margin-top: 60px; line-height: 1.9; }
.mini-empty .mini-sub { font-size: 11.5px; color: var(--text-faint); }

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
.mini-msg.user .mini-bubble { background: var(--primary); color: #fff; border-bottom-right-radius: 3px; }
.mini-msg.assistant .mini-bubble { background: var(--bg-subtle); color: var(--text); border-bottom-left-radius: 3px; }
.mini-bubble :deep(p) { margin: 0 0 8px; }
.mini-bubble :deep(p:last-child) { margin-bottom: 0; }
.mini-bubble :deep(code) { background: rgba(0, 0, 0, .07); padding: 1px 4px; border-radius: 4px; font-size: 12px; }
.mini-bubble :deep(pre) { background: #1f2329; color: #e6edf3; padding: 10px; border-radius: 8px; overflow-x: auto; font-size: 12px; }
.mini-bubble :deep(pre code) { background: none; color: inherit; padding: 0; }
.mini-bubble :deep(ul), .mini-bubble :deep(ol) { padding-left: 18px; margin: 6px 0; }
.mini-bubble :deep(.typing) { animation: blink 1s steps(2) infinite; }
@keyframes blink { 50% { opacity: 0; } }

.mini-input {
  display: flex; gap: 8px; align-items: flex-end;
  padding: 10px 12px;
  border-top: 1px solid var(--border-soft);
  background: var(--bg-sub);
  flex-shrink: 0;
}
.mini-input textarea {
  flex: 1; resize: none;
  border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-panel); color: var(--text);
  padding: 8px 10px; font-size: 13px; line-height: 1.5; font-family: inherit;
  outline: none; max-height: 90px;
}
.mini-input textarea:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(22, 93, 255, .12); }
.mini-send {
  height: 36px; padding: 0 14px; border: none; border-radius: 8px;
  background: var(--primary); color: #fff; font-size: 13px; cursor: pointer;
}
.mini-send:disabled { background: var(--text-faint); cursor: not-allowed; }
</style>
