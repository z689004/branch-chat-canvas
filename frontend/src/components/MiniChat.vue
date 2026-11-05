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
      :style="ballBgStyle"
      title="左键打开快速对话，按住可拖动，右键更多操作"
      @pointerdown.left.prevent.stop="onBallDown"
      @contextmenu.prevent.stop="openMenu"
    ></button>

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
      <header class="mini-head" title="按住拖动面板" @pointerdown="onHeadDown">
        <span class="mini-dot"></span>
        <b>快速对话</b>
        <span class="mini-tree">{{ treeTitle || '正在准备…' }}</span>
        <div class="mini-ops">
          <button title="在主窗口打开" @click="openMain">⤢</button>
          <button title="收起为悬浮球" @click="collapse">—</button>
        </div>
      </header>

      <!-- 处在子分支时给一条可回溯的路径条 -->
      <div v-if="!cur.isRoot" class="mini-crumb">
        <span class="mini-crumb-t" :title="cur.title">🌿 {{ cur.title }}</span>
        <button @click="goRoot">回到主会话</button>
      </div>

      <div ref="listEl" class="mini-list" @mouseup="onSelectEnd" @scroll="hideSelPop">
        <div v-if="!messages.length" class="mini-empty">
          <template v-if="!cur.isRoot">
            <p>🌿 新分支已建立</p>
            <p v-if="cur.ctx" class="mini-quote">{{ cur.ctx }}</p>
            <p class="mini-sub">{{ cur.mode === 'full' ? '已继承原会话的完整对话，直接提问即可' : 'AI 会以这段选中的内容为上下文回答' }}</p>
          </template>
          <template v-else>
            <p>💬 直接提问，AI 会接着这个画布继续聊</p>
            <p class="mini-sub">选中文字可以生成子分支</p>
          </template>
        </div>
        <div v-for="(m, i) in messages" :key="i" class="mini-msg" :class="m.role">
          <div class="mini-bubble" v-html="renderMd(m.content) || (m.role === 'assistant' && sending && i === messages.length - 1 ? '<span class=typing>▍</span>' : '')"></div>
        </div>
      </div>

      <!-- 划选文字后浮出的建分支入口（mousedown.prevent 保住选区，否则点击即丢失） -->
      <transition name="sp">
        <div
          v-if="selPop.visible"
          class="mini-sel-pop"
          :style="{ left: selPop.x + 'px', top: selPop.y + 'px' }"
          @mousedown.prevent
          @contextmenu.prevent.stop
        >
          <button class="sp-btn" title="仅用选中片段作为上下文" @click="makeBranch('simple')">⚡ 精简</button>
          <button class="sp-btn" title="继承当前会话的全部对话" @click="makeBranch('full')">📚 完整</button>
        </div>
      </transition>

      <div class="mini-input">
        <textarea
          ref="inputEl"
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

    <!-- 自由缩放手柄：四边 + 四角，任意方向都能拉。
         必须放在 .mini-panel 之外——panel 有 border-radius + overflow:hidden，
         会把贴角的元素裁掉，导致四个角几乎点不到。 -->
    <template v-if="expanded">
      <div class="mini-grip n"  title="拖动调整高度" @pointerdown.prevent.stop="onResizeDown($event, 'n')"></div>
      <div class="mini-grip s"  title="拖动调整高度" @pointerdown.prevent.stop="onResizeDown($event, 's')"></div>
      <div class="mini-grip w"  title="拖动调整宽度" @pointerdown.prevent.stop="onResizeDown($event, 'w')"></div>
      <div class="mini-grip e"  title="拖动调整宽度" @pointerdown.prevent.stop="onResizeDown($event, 'e')"></div>
      <div class="mini-grip nw" title="拖动自由缩放" @pointerdown.prevent.stop="onResizeDown($event, 'nw')"></div>
      <div class="mini-grip ne" title="拖动自由缩放" @pointerdown.prevent.stop="onResizeDown($event, 'ne')"></div>
      <div class="mini-grip sw" title="拖动自由缩放" @pointerdown.prevent.stop="onResizeDown($event, 'sw')"></div>
      <div class="mini-grip se" title="拖动自由缩放" @pointerdown.prevent.stop="onResizeDown($event, 'se')"></div>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, nextTick, onMounted } from 'vue'
import MarkdownIt from 'markdown-it'
import { createTree, getTree, sendQuestionStream, getMiniTreeApi, setMiniTreeApi, ensureRootNodeApi, createChildNode } from '../api'
// 球图标走源码打包（带哈希入 dist/assets），不再依赖 public/ —— 避免被构建清理误删
import ballIcon from '../assets/icon-ball.png'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
const renderMd = (s) => md.render(s || '')

// 球背景：应用图标 contain 铺满 + 同款渐变兜底（内联完整覆盖，避免类里 background 简写重置 size/position）
const ballBgStyle = {
  backgroundImage: `url(${ballIcon}), linear-gradient(145deg, #0FB47E, #067D5A)`,
  backgroundSize: 'contain, cover',
  backgroundPosition: 'center, center',
  backgroundRepeat: 'no-repeat, no-repeat'
}

const MINI_KEY = 'bcc:miniTreeId'
// 当前停在哪个节点（划选建分支后会停到子分支上，重启也接着这条分支聊）
const MINI_NODE_KEY = 'bcc:miniNodeId'
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
const inputEl = ref(null)
const treeId = ref('')
const treeTitle = ref('')
// 当前会话节点（可能是根会话，也可能是划选生成的子分支）
const cur = ref({ isRoot: true, title: '', ctx: '', mode: 'simple' })
// 划选浮层
const selPop = reactive({ visible: false, x: 0, y: 0, text: '' })
let nodeId = ''
let lastTree = null

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

// ---------------- 面板拖动 / 自由缩放 ----------------
// 真正的位移/缩放由后端线程跟随鼠标完成（光标移出窗口也能连续缩放），
// 前端只负责"按下时发起、松开时收尾"。

const RESIZE_CURSORS = {
  n: 'ns-resize', s: 'ns-resize', w: 'ew-resize', e: 'ew-resize',
  nw: 'nwse-resize', se: 'nwse-resize', ne: 'nesw-resize', sw: 'nesw-resize'
}

function beginPanelOp(mode, axis) {
  const a = api()
  if (!a || !a.begin_panel_drag) return
  document.documentElement.style.setProperty(
    '--panel-cursor',
    mode === 'move' ? 'grabbing' : (RESIZE_CURSORS[axis] || 'nwse-resize')
  )
  document.documentElement.classList.add('panel-resizing')
  try { a.begin_panel_drag(mode, axis) } catch (err) { /* ignore */ }
}

function endPanelOp() {
  document.documentElement.classList.remove('panel-resizing')
}

/** 按下标题栏：拖动整个面板（头部按钮区域不触发） */
function onHeadDown(e) {
  if (e.button !== 0) return
  if (e.target.closest('button')) return
  e.preventDefault()
  beginPanelOp('move', '')
}

/** 按下缩放手柄：dir = n / s / e / w / ne / nw / se / sw */
function onResizeDown(e, dir) {
  if (e.button !== 0) return
  beginPanelOp('resize', dir)
}

// ---------------- 右键菜单项 ----------------
async function quickChat() {
  menuOpen.value = false
  expanded.value = true
  const a = api()
  if (a && a.toggle_mini) await a.toggle_mini(true)
  // 关键：清掉点球时留下的光标/选区残留——
  // 否则 Chromium 会把下一次拖选挂在不可选区里的旧锚点上，表现为"怎么拖都选不中"
  try { window.getSelection()?.removeAllRanges() } catch (e) { /* ignore */ }
  // 打开面板即校正：用户可能在主界面把速记画布删了
  try { await ensureAlive(true) } catch (e) { /* 后端未就绪 */ }
  scrollBottom()
}

async function menuOpenMain() {
  await closeMenu()
  try { await ensureAlive() } catch (e) { /* ignore */ }
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
  try { await ensureAlive() } catch (e) { /* ignore */ }
  const a = api()
  if (a && a.open_main) await a.open_main(treeId.value)
  await collapse()
}

/** 绑定画布；画布还在但会话节点被删光时补一个空白根节点
 *  （快速对话以根节点为对话载体，节点没了就发不出消息）
 *  返回 true 表示补过节点 */
async function bindOrRepair(tree) {
  const list = tree.nodeList || []
  if (list.some((n) => !n.parentId)) {
    bindTree(tree)
    return false
  }
  try {
    const fixed = await ensureRootNodeApi(tree.treeId)
    bindTree(fixed)
    return true
  } catch (e) {
    bindTree(tree) // 补不上就按原样绑定，发送时会给出提示
    return false
  }
}

/** 取用/创建「悬浮速记」画布，并取它的根节点作为对话载体
 *  查找顺序：本地存储 → 后端口径（悬浮球窗口与主窗口存储可能隔离，重启后读不到）→ 新建
 *  这样每次启动复用同一块画布，不会每次开程序都多出一个空白画布
 *  force=true 时丢弃当前绑定重新走一遍（画布被删后自愈用） */
async function ensureTree(force = false) {
  if (force) resetTree()
  if (treeId.value && nodeId) return
  const id = localStorage.getItem(MINI_KEY) || ''
  if (id) {
    try {
      const t = await getTree(id)
      localStorage.setItem(MINI_KEY, t.treeId)
      await bindOrRepair(t)
      return
    } catch (e) {
      // 只在「画布确实不存在」时作废指针；后端暂时不可用不要误删
      if (isMissingTree(e)) localStorage.removeItem(MINI_KEY)
    }
  }
  try {
    const bound = await getMiniTreeApi()
    if (bound && bound.treeId) {
      const t = await getTree(bound.treeId)
      localStorage.setItem(MINI_KEY, t.treeId)
      await bindOrRepair(t)
      return
    }
  } catch (e) { /* 后端未就绪时忽略 */ }
  const created = await createTree(MINI_TITLE)
  localStorage.setItem(MINI_KEY, created.treeId)
  try { await setMiniTreeApi(created.treeId) } catch (e) { /* ignore */ }
  bindTree(created)
}

/** 后端在画布不存在时抛的固定文案（detail="对话树不存在"） */
const isMissingTree = (e) => /对话树不存在|画布不存在/.test((e && e.message) || '')
/** 画布还在、只是会话节点被删（detail="节点不存在"）——要和画布丢失分开处理 */
const isMissingNode = (e) => /节点不存在/.test((e && e.message) || '')

let lastCheckAt = 0

/** 清空当前绑定（不删后端数据），让 ensureTree 重新挑一块画布 */
function resetTree() {
  treeId.value = ''
  treeTitle.value = ''
  nodeId = ''
  lastTree = null
  cur.value = { isRoot: true, title: '', ctx: '', mode: 'simple' }
  messages.value = []
  lastCheckAt = 0
  localStorage.removeItem(MINI_NODE_KEY)
  hideSelPop()
}

/** 发消息 / 打开面板前确认画布还在。
 *  在软件里手动删掉速记画布后，旧 treeId 会一直报「对话树不存在」，
 *  这里检测到失效就自动新建一块，让快速对话始终可用。 */
const STALE_NOTICE = '⚠️ 原来的速记会话已被删除，已自动新建一个，直接提问即可。'

async function ensureAlive(force = false) {
  // 绑定已经不完整（画布或节点被删）→ 自愈，并给一句说明
  if (!treeId.value || !nodeId) {
    const hadBinding = !!(treeId.value || localStorage.getItem(MINI_KEY))
    await ensureTree(true)
    if (hadBinding && nodeId) messages.value = [{ role: 'assistant', content: STALE_NOTICE }]
    return
  }
  if (!force && Date.now() - lastCheckAt < 1200) return // 连续操作只校验一次
  lastCheckAt = Date.now()
  try {
    const t = await getTree(treeId.value)
    // 顺带同步主窗口那边新增的内容；会话被删光时这里会自动补一个根节点
    const repaired = await bindOrRepair(t)
    if (repaired) messages.value = [{ role: 'assistant', content: STALE_NOTICE }]
  } catch (e) {
    if (!isMissingTree(e)) return // 网络/后端异常：保持原样，交给发送流程报错
    resetTree()
    await ensureTree(true)
    if (nodeId) messages.value = [{ role: 'assistant', content: STALE_NOTICE }]
  }
}

/** 绑定画布，并尽量停在「当前节点」上
 *  —— 划选生成子分支后，后续的 ensureAlive 不能把会话冲回根节点
 *  preferId: 指定要停的节点（切到新分支 / 回到主会话时用） */
function bindTree(tree, preferId = '') {
  lastTree = tree
  treeId.value = tree.treeId
  treeTitle.value = tree.title
  const list = tree.nodeList || []
  const want = preferId || nodeId || localStorage.getItem(MINI_NODE_KEY) || ''
  const target = list.find((n) => n.nodeId === want)
    || list.find((n) => !n.parentId)
    || list[0]
  nodeId = target ? target.nodeId : ''
  if (nodeId) localStorage.setItem(MINI_NODE_KEY, nodeId)
  cur.value = target
    ? {
        isRoot: !target.parentId,
        title: target.title || '未命名会话',
        ctx: target.selectedContext || '',
        mode: target.contextMode || 'simple'
      }
    : { isRoot: true, title: '', ctx: '', mode: 'simple' }
  messages.value = (target && target.messages ? target.messages : []).map((m) => ({
    role: m.role, content: m.content
  }))
  selPop.visible = false
}

// ---------------- 划选文字 → 生成子分支 ----------------

const hideSelPop = () => { selPop.visible = false }

/** 松手后看有没有选中对话内容；有就给「精简 / 完整」两个建分支入口 */
function onSelectEnd(e) {
  if (e.target.closest('.mini-sel-pop')) return
  nextTick(() => {
    const sel = window.getSelection()
    const text = sel ? sel.toString().trim() : ''
    if (!text || text.length < 4) { hideSelPop(); return }
    const anchor = sel.anchorNode
    const el = anchor && (anchor.nodeType === 1 ? anchor : anchor.parentElement)
    if (!el || !el.closest('.mini-bubble')) { hideSelPop(); return } // 只在对话气泡里生效
    const rect = sel.getRangeAt(0).getBoundingClientRect()
    const W = 168
    const H = 32
    selPop.text = text
    selPop.x = Math.max(8, Math.min(rect.left + rect.width / 2 - W / 2, window.innerWidth - W - 8))
    // 优先显示在选区上方，放不下就落回下方
    selPop.y = rect.top - H - 8 >= 6
      ? rect.top - H - 8
      : Math.min(rect.bottom + 8, window.innerHeight - H - 6)
    selPop.visible = true
  })
}

/** 以选中片段为上下文建子分支，并把快速对话切到这条分支上 */
async function makeBranch(mode) {
  const text = selPop.text
  if (!text || !nodeId) return
  selPop.visible = false
  window.getSelection()?.removeAllRanges()
  const parentId = nodeId
  try {
    const child = await createChildNode({
      treeId: treeId.value,
      parentId,
      selectedContext: text,
      contextMode: mode,
      title: text.replace(/\s+/g, ' ').trim().slice(0, 12) || '新分支'
    })
    // 父节点可能刚在主界面被删：重新取一遍树再绑定，取不到就直接用返回的节点
    let t = null
    try { t = await getTree(treeId.value) } catch (e) { t = null }
    if (t && (t.nodeList || []).some((n) => n.nodeId === child.nodeId)) {
      bindTree(t, child.nodeId)
    } else {
      nodeId = child.nodeId
      cur.value = {
        isRoot: false,
        title: child.title || '新分支',
        ctx: text,
        mode
      }
      messages.value = []
      localStorage.setItem(MINI_NODE_KEY, child.nodeId)
    }
    nextTick(() => { if (inputEl.value) inputEl.value.focus() })
  } catch (e) {
    messages.value.push({
      role: 'assistant',
      content: `⚠️ 新建分支失败：${e.message || '请稍后重试'}`
    })
  }
}

/** 回到这块画布的主会话（根节点） */
function goRoot() {
  if (!lastTree) return
  const root = (lastTree.nodeList || []).find((n) => !n.parentId)
  if (!root) return
  bindTree(lastTree, root.nodeId)
  hideSelPop()
}

async function send() {
  const content = draft.value.trim()
  if (!content || sending.value) return
  draft.value = ''
  await sendContent(content)
}

async function sendContent(content, retried = false, notice = '') {
  // 发送前确认画布还在（被删过就自动重建，不再直接报「对话树不存在」）
  await ensureAlive()
  if (!nodeId) {
    draft.value = content
    messages.value.push({ role: 'assistant', content: '⚠️ 暂时无法准备速记画布，请稍后重试。' })
    return
  }
  const userBubble = { role: 'user', content }
  const ai = reactive({ role: 'assistant', content: '' })
  messages.value.push(userBubble, ai)
  sending.value = true
  scrollBottom()
  let rebuilt = false
  try {
    await sendQuestionStream(treeId.value, nodeId, content, (chunk) => {
      ai.content += chunk
      scrollBottom()
    })
  } catch (e) {
    if (isMissingNode(e) && !retried) {
      // 画布还在，只是承载对话的卡片被删了 → 就地补一张根会话并重发，画布本身不动
      rebuilt = true
      try {
        const t = await getTree(treeId.value)
        const repaired = await bindOrRepair(t)
        if (nodeId && repaired) {
          const tip = '⚠️ 原来的速记会话被删除了，已自动新建一个并重新发送。'
          messages.value = [{ role: 'assistant', content: tip }]
          sendContent(content, true, tip)
        } else if (nodeId) {
          // 补的时候根节点已经在了（比如主界面刚新建过）：直接重发
          messages.value = []
          sendContent(content, true, '')
        } else {
          draft.value = content
          messages.value = [{
            role: 'assistant',
            content: '⚠️ 速记会话被删了，自动新建失败，请稍后再试。'
          }]
        }
      } catch (err) {
        draft.value = content
        messages.value = [{
          role: 'assistant',
          content: '⚠️ 速记会话被删了，自动新建失败，请稍后再试。'
        }]
      }
    } else if (isMissingTree(e) && !retried) {
      // 整块画布在发送瞬间被删：重建一块，把这条问题原样重发一次，用户无感
      rebuilt = true
      resetTree()
      try { await ensureTree(true) } catch (err) { /* ignore */ }
      if (nodeId) {
        const tip = '⚠️ 这块速记画布刚被删除，已自动新建一块并重新发送。'
        messages.value = [{ role: 'assistant', content: tip }]
        sendContent(content, true, tip) // 不 await：交给下一轮完成收尾
      } else {
        draft.value = content
        messages.value = [{
          role: 'assistant',
          content: '⚠️ 这块速记画布刚被删除，自动新建失败，请稍后再试。'
        }]
      }
    } else if (!ai.content) {
      ai.content = `⚠️ ${e.message || '请求失败'}`
    } else {
      ai.content += `\n\n⚠️ ${e.message || '请求中断'}`
    }
  } finally {
    // 走了重建分支时，发送状态与落库对齐交给下一轮负责，避免提前解锁输入
    if (!rebuilt) {
      sending.value = false
      scrollBottom()
      // 与后端落库内容对齐（后端会把本轮问答写入节点）
      try {
        const t = await getTree(treeId.value)
        // 模型调用失败时后端落库的是空回答，直接 bindTree 会把 ⚠️ 提示冲掉
        const errText = String(ai.content || '').startsWith('⚠️') ? ai.content : ''
        bindTree(t)
        // 重建后重发的那一轮：把「已自动新建」的说明补回顶部，别被落库内容冲掉
        if (notice) messages.value.unshift({ role: 'assistant', content: notice })
        if (errText) {
          const last = [...messages.value].reverse().find((m) => m.role === 'assistant')
          if (last && !String(last.content || '').trim()) last.content = errText
          else if (!last) messages.value.push({ role: 'assistant', content: errText })
        }
        scrollBottom()
      } catch (e) { /* ignore */ }
    }
  }
}

/** 窗口被后端收回成球尺寸（如菜单被外部点击关闭）时，同步收起菜单视图 */
function onWinResize() {
  if (menuOpen.value && window.innerWidth <= 120 && window.innerHeight <= 120) {
    menuOpen.value = false
  }
}

function onKeyDown(e) {
  if (e.key === 'Escape') {
    if (selPop.visible) { hideSelPop(); return }
    if (menuOpen.value) closeMenu()
  }
}

/** 任何按下都先把旧选区清掉：点过球 / 标题栏等不可选区后，Chromium 会把
 *  下一次拖选挂在旧锚点上，表现为"在气泡里怎么拖都选不中"，先清空即可避免 */
function onShieldDown(e) {
  const t = e.target
  if (t && t.closest && t.closest('textarea, input')) return // 输入框里的选区交给原生行为
  try { window.getSelection()?.removeAllRanges() } catch (err) { /* ignore */ }
}

onMounted(async () => {
  // 供后端在"点菜单外部"时回调，收起菜单视图
  window.__closeBallMenu = () => { menuOpen.value = false }
  // 后端结束拖动/缩放后回调（光标离开窗口时前端收不到 pointerup）
  window.__panelDragEnd = () => endPanelOp()
  window.addEventListener('pointerup', endPanelOp)
  window.addEventListener('pointercancel', endPanelOp)
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('resize', onWinResize)
  window.addEventListener('mousedown', onShieldDown, true)
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
  /* 图标由内联 style 注入（源码打包），这里保留渐变兜底：窗口尺寸瞬间异常时也不露白 */
  background: linear-gradient(145deg, #0FB47E, #067D5A);
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
  position: relative;
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
  cursor: grab;
  user-select: none;
}
.mini-head:active { cursor: grabbing; }

/* ---------- 自由缩放手柄（贴住窗口边缘，超出圆角部分不可见） ---------- */
.mini-grip { position: absolute; z-index: 5; }

/* 四边：边中段可拉（两端让给角落手柄） */
.mini-grip.n  { left: 16px; right: 16px; top: 0;    height: 6px; cursor: ns-resize; }
.mini-grip.s  { left: 16px; right: 16px; bottom: 0; height: 6px; cursor: ns-resize; }
.mini-grip.w  { top: 48px; bottom: 16px; left: 0;   width: 6px;  cursor: ew-resize; }
.mini-grip.e  { top: 48px; bottom: 16px; right: 0;  width: 6px;  cursor: ew-resize; }

/* 四角：自由缩放 */
.mini-grip.nw { left: 0;   top: 0;    width: 14px; height: 14px; cursor: nwse-resize; }
.mini-grip.ne { right: 0;  top: 0;    width: 14px; height: 14px; cursor: nesw-resize; }
.mini-grip.sw { left: 0;   bottom: 0; width: 14px; height: 14px; cursor: nesw-resize; }
.mini-grip.se { right: 0;  bottom: 0; width: 14px; height: 14px; cursor: nwse-resize; }

/* 右下角给一个隐约的斜纹提示，告诉用户这里能拉 */
.mini-grip.se::after {
  content: '';
  position: absolute; right: 3px; bottom: 3px;
  width: 8px; height: 8px;
  border-right: 2px solid var(--border);
  border-bottom: 2px solid var(--border);
  border-bottom-right-radius: 3px;
  opacity: .55;
  transition: opacity .15s ease;
}
.mini-grip.se:hover::after { opacity: .95; }
.mini-grip:hover { background: var(--bg-subtle); }

/* 拖动/缩放期间全局光标，避免掠过其他元素时光标乱跳 */
:global(html.panel-resizing), :global(html.panel-resizing *) {
  cursor: var(--panel-cursor, grabbing) !important;
  user-select: none !important;
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
.mini-quote {
  margin: 8px 0; padding: 8px 10px;
  font-size: 12px; line-height: 1.6; text-align: left;
  color: var(--text-sub);
  background: var(--bg-subtle);
  border-left: 3px solid var(--success);
  border-radius: 0 8px 8px 0;
  max-height: 96px; overflow: hidden;
}

/* 子分支路径条：告诉用户现在在哪，并提供一键回主会话 */
.mini-crumb {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 14px;
  background: rgba(0, 180, 42, .07);
  border-bottom: 1px solid var(--border-soft);
  flex-shrink: 0;
}
.mini-crumb-t {
  flex: 1; min-width: 0;
  font-size: 11.5px; color: var(--success);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.mini-crumb button {
  border: none; background: transparent; cursor: pointer;
  font-size: 11.5px; color: var(--primary); padding: 2px 4px; border-radius: 5px;
  font-family: inherit;
}
.mini-crumb button:hover { background: var(--bg-subtle); }

/* 划选浮层：紧贴选区，两个建分支入口 */
.mini-sel-pop {
  position: absolute;
  z-index: 60;
  display: flex; gap: 4px;
  padding: 4px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 9px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, .16);
  user-select: none;
}
.sp-btn {
  border: none; border-radius: 6px; cursor: pointer;
  padding: 5px 9px; font-size: 12px; line-height: 1;
  background: transparent; color: var(--text-sub);
  font-family: inherit; white-space: nowrap;
}
.sp-btn:hover { background: var(--bg-subtle); color: var(--primary); }
.sp-btn:active { transform: scale(.96); }
.sp-enter-active, .sp-leave-active { transition: opacity .12s ease, transform .12s ease; }
.sp-enter-from, .sp-leave-to { opacity: 0; transform: translateY(4px); }

/* 划选时高亮跟随主题色 */
.mini-bubble ::selection, .mini-bubble::selection {
  background: rgba(22, 93, 255, .22);
}

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
