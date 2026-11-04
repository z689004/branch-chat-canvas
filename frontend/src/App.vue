<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useTreeStore } from './store/tree'
import {
  exportTree, importTree, getLlmConfig, updateLlmConfig, testLlm,
  saveLlmProfile, deleteLlmProfile, activateLlmProfile
} from './api'
import ChatNode from './components/ChatNode.vue'

const store = useTreeStore()
const { fitView, viewport, zoomIn, zoomOut, getSelectedNodes } = useVueFlow()

/** 适应视图：缩放到刚好装下全部节点，但最多放大到 100%，避免小画布被拉得过大 */
const fitAll = (padding = 0.25, duration = 300) =>
  fitView({ padding, duration, maxZoom: 1 })

const flowNodes = computed(() =>
  store.visibleNodes.map(n => ({
    id: n.nodeId,
    type: 'chat',
    position: { x: n.x, y: n.y },
    data: { nodeId: n.nodeId }
  }))
)

/** 连线按分支类型区分样式：精简（片段上下文）= 实线，完整（继承全对话）= 圆点虚线 */
const flowEdges = computed(() =>
  store.visibleNodes
    .filter(n => n.parentId && store.nodeMap[n.parentId])
    .map(n => {
      const full = n.contextMode === 'full'
      const color = full ? '#00b42a' : '#165dff'
      return {
        id: `e-${n.parentId}-${n.nodeId}`,
        source: n.parentId,
        target: n.nodeId,
        // 金字塔布局：连线从父节点底部出发，接到子节点顶部
        type: 'smoothstep',
        sourcePosition: 'bottom',
        targetPosition: 'top',
        animated: false,
        label: full ? '完整' : '精简',
        labelShowBg: true,
        labelBgPadding: [4, 2],
        labelBgBorderRadius: 4,
        labelStyle: { fill: color, fontSize: 10 },
        labelBgStyle: { fill: theme === 'dark' ? '#1f2125' : '#fff', fillOpacity: 0.92 },
        style: {
          stroke: color,
          strokeWidth: 2,
          strokeDasharray: full ? '6 4' : undefined
        },
        markerEnd: { type: 'arrowclosed', color }
      }
    })
)

function onDragStop({ node }) {
  store.savePos(node.id, node.position)
}

// ---------- 文本划选 → 悬浮分支面板 ----------
const branch = reactive({ visible: false, x: 0, y: 0, text: '', nodeId: '' })
let branchHideTimer = null

function scheduleBranchHide() {
  clearTimeout(branchHideTimer)
  branchHideTimer = setTimeout(() => { branch.visible = false }, 500)
}
function cancelBranchHide() {
  clearTimeout(branchHideTimer)
}

function onMouseUp(e) {
  if (e.target.closest('.branch-pop') || e.target.closest('.el-dialog')) return
  nextTick(() => {
    const sel = window.getSelection()
    const text = sel ? sel.toString().trim() : ''
    if (!text || text.length < 4) {
      // 已取消选中：面板保留 0.5 秒后消失
      if (branch.visible) scheduleBranchHide()
      return
    }
    const anchor = sel.anchorNode
    const el = anchor && (anchor.nodeType === 1 ? anchor : anchor.parentElement)
    const host = el && el.closest('[data-node-id]')
    if (!host) {
      if (branch.visible) scheduleBranchHide()
      return
    }
    cancelBranchHide()
    const range = sel.getRangeAt(0)
    const rect = range.getBoundingClientRect()
    branch.text = text
    branch.nodeId = host.dataset.nodeId
    branch.x = Math.min(rect.left + rect.width / 2, window.innerWidth - 260)
    // 面板显示在选区上方（高度约 76px）
    branch.y = Math.max(rect.top - 86, 60)
    branch.visible = true
  })
}

const AUTO_TIDY_KEY = 'bcc:autoTidy'
const autoTidy = ref(localStorage.getItem(AUTO_TIDY_KEY) !== '0')   // 默认开启

async function quickCreate(mode) {
  if (!branch.nodeId || !branch.text) return
  try {
    const title = branch.text.slice(0, 12)
    await store.createChild(branch.nodeId, branch.text, mode, title)
    branch.visible = false
    window.getSelection()?.removeAllRanges()
    // 新建分支后按金字塔重新排布（可关闭后自由摆放）
    if (autoTidy.value) store.tidyLayout(false)
    ElMessage.success(mode === 'simple' ? '已创建精简分支，去新节点继续追问吧' : '已创建完整分支，去新节点继续追问吧')
    nextTick(() => fitAll(0.25, 400))
  } catch (e) {
    ElMessage.error(e.message)
  }
}

// ---------- 画布操作 ----------
async function newTree() {
  try { await store.newTree(); ElMessage.success('新画布已创建'); nextTick(() => fitAll(0.3, 300)) }
  catch (e) { ElMessage.error(e.message) }
}
async function switchTree(treeId) {
  try { await store.loadTree(treeId); nextTick(() => fitAll(0.25, 300)) }
  catch (e) { ElMessage.error(e.message) }
}

async function downloadText(text, filename, mime) {
  // 桌面版（pywebview）：走原生"另存为"对话框（默认拦截网页下载）
  const pyApi = window.pywebview && window.pywebview.api
  if (pyApi && typeof pyApi.save_text === 'function') {
    try {
      const saved = await pyApi.save_text(filename, text)
      if (saved) ElMessage.success(`已保存到：${saved}`)
      else ElMessage.info('已取消保存')
    } catch (e) {
      ElMessage.error('保存失败：' + (e && e.message ? e.message : e))
    }
    return
  }
  // 浏览器 / 网页版：Blob 下载
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 3000)
}

async function doExport(format) {
  if (format === 'import') { pickImportFile(); return }
  if (!store.treeId) return
  try {
    const { text, filename } = await exportTree(store.treeId, format)
    const mime = format === 'json' ? 'application/json'
      : format === 'html' ? 'text/html'
        : format === 'mermaid' ? 'text/plain' : 'text/markdown'
    const safeTitle = (store.treeTitle || '分支对话树').replace(/[\\/:*?"<>|]/g, '_')
    const ext = filename.split('.').pop()
    downloadText(text, `${safeTitle}.${ext}`, mime)
    ElMessage.success('已导出')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

// ---------- 导入备份 ----------
const importInput = ref(null)
function pickImportFile() {
  importInput.value && importInput.value.click()
}
async function onImportFile(e) {
  const file = e.target.files && e.target.files[0]
  e.target.value = ''  // 允许重复选同一文件
  if (!file) return
  try {
    const text = await file.text()
    let data
    try { data = JSON.parse(text) } catch (err) {
      ElMessage.error('不是有效的 JSON 文件，请选择由本工具导出的 JSON 备份')
      return
    }
    const tree = await importTree(data)
    await store.loadTree(tree.treeId)
    nextTick(() => fitAll(0.25, 400))
    ElMessage.success(`已导入「${tree.title}」，共 ${tree.nodeList.length} 个节点`)
  } catch (err) {
    ElMessage.error(err.message || '导入失败')
  }
}

/** 导出单条分支（子树） */
function branchMarkdown(nodeId) {
  const lines = []
  const walk = (id, depth) => {
    const n = store.nodeMap[id]
    if (!n) return
    lines.push(`${'#'.repeat(Math.min(depth + 1, 6))} ${n.parentId ? '🌿 ' : '🌱 '}${n.title}`)
    const meta = [`上下文：${n.contextMode === 'full' ? '完整模式' : '精简模式'}`]
    if (n.selectedContext) meta.push(`选中片段：「${n.selectedContext.slice(0, 80)}」`)
    lines.push(`> ${meta.join(' ｜ ')}`)
    for (const m of n.messages || []) {
      lines.push(`${m.role === 'user' ? '**🙋 用户**' : '**🤖 AI**'}：${m.content}\n`)
    }
    lines.push('')
    ;(store.childrenMap[id] || []).forEach(k => walk(k.nodeId, depth + 1))
  }
  walk(nodeId, 0)
  return lines.join('\n')
}
function exportBranch(nodeId) {
  const n = store.nodeMap[nodeId]
  if (!n) return
  const safe = (n.title || '分支').replace(/[\\/:*?"<>|]/g, '_')
  downloadText(branchMarkdown(nodeId), `${safe}.md`, 'text/markdown')
  ElMessage.success('已导出该分支')
}

let lastClearAt = 0
async function clearCanvas() {
  if (!store.treeId) return
  if (Date.now() - lastClearAt < 3000) {
    ElMessage.warning('清空操作过于频繁，请稍候再试')
    return
  }
  const count = store.nodes.length
  try {
    await ElMessageBox.prompt(
      `将删除画布「${store.treeTitle || '未命名画布'}」上全部 ${count} 个节点及其对话记录，且不可恢复。确认请输入：清空`,
      '清空画布',
      {
        type: 'warning',
        confirmButtonText: '确认清空',
        cancelButtonText: '取消',
        inputPlaceholder: '在此输入：清空',
        inputPattern: /^清空$/,
        inputErrorMessage: '请输入「清空」两个字以确认删除'
      }
    )
  } catch (e) { return }
  try {
    await store.clearCanvas()
    lastClearAt = Date.now()
    ElMessage.success('画布已清空')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const welcomeQuestion = ref('')
async function startFromWelcome() {
  const q = welcomeQuestion.value.trim()
  if (!q) return
  welcomeQuestion.value = ''
  await newTree()
  const root = store.roots[0]
  if (root) await store.send(root.nodeId, q)
}

// ---------- 撤销 / 重做 ----------
async function doUndo() {
  if (!store.canUndo) { ElMessage.info('没有可撤销的操作'); return }
  await store.undo()
  ElMessage.success('已撤销')
}
async function doRedo() {
  if (!store.canRedo) { ElMessage.info('没有可重做的操作'); return }
  await store.redo()
  ElMessage.success('已重做')
}

// ---------- 节点：右键菜单 / 新建子分支 ----------
const ctx = reactive({ visible: false, x: 0, y: 0, nodeId: '' })
const ctxNode = computed(() => (ctx.nodeId ? store.nodeMap[ctx.nodeId] : null))

function openNodeMenu({ nodeId, x, y }) {
  ctx.nodeId = nodeId
  ctx.x = Math.min(x, window.innerWidth - 210)
  ctx.y = Math.min(y, window.innerHeight - 300)
  ctx.visible = true
}
function closeNodeMenu() { ctx.visible = false }

async function addChildTo(nodeId) {
  closeNodeMenu()
  try {
    await store.createChild(nodeId, '', 'full', '新分支')
    if (autoTidy.value) store.tidyLayout(false)
    ElMessage.success('已新建子分支')
    nextTick(() => fitAll(0.25, 300))
  } catch (e) { ElMessage.error(e.message) }
}

async function ctxDuplicate(withSubtree) {
  const id = ctx.nodeId
  closeNodeMenu()
  try {
    await store.duplicate(id, withSubtree)
    if (autoTidy.value) store.tidyLayout(false)
    ElMessage.success(withSubtree ? '已复制整条分支' : '已复制该节点')
    nextTick(() => fitAll(0.25, 300))
  } catch (e) { ElMessage.error(e.message) }
}
async function ctxToggleCollapse() {
  const n = ctxNode.value
  if (!n) return
  closeNodeMenu()
  await store.patchNode(n.nodeId, { isCollapsed: !n.isCollapsed })
  if (autoTidy.value) store.tidyLayout(false)
}
async function ctxDelete() {
  const n = ctxNode.value
  if (!n) return
  const total = store.subtreeIds(n.nodeId).length
  closeNodeMenu()
  try {
    await ElMessageBox.confirm(
      `将删除「${n.title}」${total > 1 ? `及其 ${total - 1} 个子孙节点` : ''}，且不可恢复。确认删除？`,
      '删除节点',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch (e) { return }
  try {
    const c = await store.removeNode(n.nodeId)
    ElMessage.success(`已删除 ${c} 个节点`)
  } catch (e) { ElMessage.error(e.message) }
}
function ctxStar() {
  const n = ctxNode.value
  if (!n) return
  store.toggleStar(n.nodeId)
  closeNodeMenu()
}

// ---------- 批量操作（Ctrl / Shift 多选） ----------
const selectedIds = computed(() => (getSelectedNodes?.value || []).map(n => n.id))
const showBatchBar = computed(() => selectedIds.value.length > 1)

async function batchDuplicate() {
  const ids = [...selectedIds.value]
  try {
    await store.duplicateMany(ids, true)
    if (autoTidy.value) store.tidyLayout(false)
    ElMessage.success(`已复制 ${ids.length} 个分支`)
  } catch (e) { ElMessage.error(e.message) }
}
async function batchDelete() {
  const ids = [...selectedIds.value]
  const total = new Set(ids.flatMap(id => store.subtreeIds(id))).size
  try {
    await ElMessageBox.confirm(
      `将删除选中的 ${ids.length} 个节点（含子孙共 ${total} 个），且不可恢复。确认删除？`,
      '批量删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch (e) { return }
  try {
    const c = await store.removeNodes(ids)
    ElMessage.success(`已删除 ${c} 个分支`)
  } catch (e) { ElMessage.error(e.message) }
}
function batchExport() {
  const ids = [...selectedIds.value]
  const text = ids.map(id => branchMarkdown(id)).join('\n\n---\n\n')
  downloadText(text, `对话分支-${ids.length}条.md`, 'text/markdown')
  ElMessage.success('已导出所选分支')
}
function clearSelection() {
  ;(getSelectedNodes?.value || []).forEach(n => { n.selected = false })
}

// ---------- 模型与密钥管理 ----------
const llmDialog = ref(false)
const llmInfo = reactive({
  provider: 'mock', profiles: [], activeId: '', activeName: '', hasKey: false, keyMasked: ''
})
const editing = ref(null)          // 新增/编辑中的档案（null = 不显示表单）
const testingKey = ref('')         // 正在测试的档案 id，或新建表单为 'new'
const testResults = reactive({})   // { [id|'new']: 测试结果 }
const llmSaving = ref(false)

const providerLabel = { mock: '🧪 演示模式', openai: '☁️ 云端 API', ollama: '🖥️ 本地 Ollama' }

function blankProfile(provider = 'openai') {
  return {
    id: '',
    name: '',
    provider: provider === 'ollama' ? 'ollama' : 'openai',
    baseUrl: provider === 'ollama' ? 'http://localhost:11434' : 'https://api.deepseek.com',
    apiKey: '',
    model: provider === 'ollama' ? 'qwen2.5:7b' : 'deepseek-chat'
  }
}

function applyLlmCfg(cfg) {
  Object.assign(llmInfo, {
    provider: cfg.provider,
    profiles: cfg.profiles || [],
    activeId: cfg.activeId || '',
    activeName: cfg.activeName || '',
    hasKey: cfg.hasKey,
    keyMasked: cfg.keyMasked || ''
  })
}

async function refreshLlm() {
  try { applyLlmCfg(await getLlmConfig()) } catch (e) { /* ignore */ }
}

async function openLlmDialog() {
  await refreshLlm()
  llmDialog.value = true
}

async function setProvider(p) {
  try {
    applyLlmCfg(await updateLlmConfig({ provider: p }))
    if (p !== 'mock' && !llmInfo.profiles.length) startEdit(blankProfile(p))
  } catch (e) { ElMessage.error(e.message) }
}

function startEdit(p) {
  // 编辑已有档案时不回显密钥，Key 输入留空表示保持不变
  editing.value = p && p.id
    ? { ...p, apiKey: '' }
    : blankProfile(p && p.provider ? p.provider : llmInfo.provider === 'ollama' ? 'ollama' : 'openai')
  delete testResults['new']
}

async function saveProfile() {
  if (!editing.value) return
  if (!editing.value.name.trim()) {
    ElMessage.warning('请给这个密钥起个名字，方便区分（例如「DeepSeek 主号」）')
    return
  }
  llmSaving.value = true
  try {
    applyLlmCfg(await saveLlmProfile(editing.value))
    editing.value = null
    ElMessage.success('密钥已保存并启用')
  } catch (e) {
    ElMessage.error(e.message)
  } finally { llmSaving.value = false }
}

async function removeProfile(p) {
  try {
    await ElMessageBox.confirm(
      `将删除密钥档案「${p.name}」，删除后使用该密钥的对话将无法继续生成。确认删除？`,
      '删除密钥', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch (e) { return }
  try {
    applyLlmCfg(await deleteLlmProfile(p.id))
    ElMessage.success('已删除')
  } catch (e) { ElMessage.error(e.message) }
}

async function useProfile(p) {
  try {
    applyLlmCfg(await activateLlmProfile(p.id))
    ElMessage.success(`已启用「${p.name}」`)
  } catch (e) { ElMessage.error(e.message) }
}

async function runTest(key, payload) {
  testingKey.value = key
  testResults[key] = null
  try {
    testResults[key] = await testLlm(payload)
  } catch (e) {
    testResults[key] = { ok: false, error: e.message }
  } finally {
    testingKey.value = ''
    await refreshLlm()          // 回写「上次测试」状态
  }
}
function testSaved(p) { runTest(p.id, { id: p.id }) }
function testDraft() { runTest('new', { ...editing.value }) }

/** 一键把该密钥的模型切换成 Key 实际可用的模型 */
async function pickModel(p, m) {
  try {
    applyLlmCfg(await saveLlmProfile({
      id: p.id, name: p.name, provider: p.provider, baseUrl: p.baseUrl, model: m
    }))
    ElMessage.success(`模型已切换为 ${m}`)
    await runTest(p.id, { id: p.id })
  } catch (e) { ElMessage.error(e.message) }
}

function testText(r) {
  if (!r) return ''
  if (r.simulated) return r.msg
  if (r.ok && r.warning) return `⚠️ ${r.msg}`
  if (r.ok) return `✅ ${r.msg}`
  return `❌ ${r.error}`
}
function testClass(r) {
  if (!r) return ''
  if (r.simulated) return 'dim'
  if (!r.ok) return 'fail'
  return r.warning ? 'warn' : 'ok'
}

// ---------- 画布辅助：小地图 / 网格 / 主题 / 缩放 ----------
const showMinimap = ref(true)
const GRID_KEY = 'bcc:showGrid'
const showGrid = ref(localStorage.getItem(GRID_KEY) !== '0')
const theme = ref(localStorage.getItem('bcc:theme') || 'light')

function toggleGrid() {
  showGrid.value = !showGrid.value
  localStorage.setItem(GRID_KEY, showGrid.value ? '1' : '0')
}
function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  localStorage.setItem('bcc:theme', theme.value)
  document.documentElement.setAttribute('data-theme', theme.value)
  document.documentElement.classList.toggle('dark', theme.value === 'dark')
}
function toggleMinimap() {
  showMinimap.value = !showMinimap.value
  nextTick(() => fitAll(0.25, 300))
}

/** 小地图按节点类型着色：根绿 / 分支蓝 / 报错红 / 空白灰 */
function miniColor(node) {
  const n = store.nodeMap[node.id]
  if (!n) return '#c9cdd4'
  if (!(n.messages || []).length) return '#c9cdd4'
  const last = [...n.messages].reverse().find(m => m.role === 'assistant')
  if (last && String(last.content).startsWith('⚠️')) return '#f53f3f'
  return n.parentId ? '#165dff' : '#00b42a'
}

const zoomPct = computed(() => Math.round((viewport?.value?.zoom || 1) * 100))
function onWheel(e) {
  if (!e.ctrlKey && !e.metaKey) return       // Ctrl / ⌘ + 滚轮 = 缩放，普通滚轮 = 平移画布
  e.preventDefault()
  if (e.deltaY < 0) zoomIn({ duration: 120 })
  else zoomOut({ duration: 120 })
}

const spaceDown = ref(false)
const editingTreeName = ref(false)
const treeNameDraft = ref('')
function startRenameTree() {
  treeNameDraft.value = store.treeTitle
  editingTreeName.value = true
}
async function saveRenameTree() {
  editingTreeName.value = false
  const t = treeNameDraft.value.trim()
  if (t && t !== store.treeTitle) {
    try { await store.renameTree(t) } catch (e) { ElMessage.error(e.message) }
  }
}
function tidyLayout() {
  store.tidyLayout()
  ElMessage.success('已按金字塔结构整理布局')
  nextTick(() => fitAll(0.2, 400))
}
function onAutoTidyChange(v) {
  localStorage.setItem(AUTO_TIDY_KEY, v ? '1' : '0')
  if (v) tidyLayout()
}

const isTyping = (e) => {
  const t = e.target
  return !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
}
function onKeydown(e) {
  if (e.key === 'Escape') {
    window.getSelection()?.removeAllRanges()
    branch.visible = false
    closeNodeMenu()
    return
  }
  const mod = e.ctrlKey || e.metaKey
  if (mod && e.key.toLowerCase() === 'z') {
    e.preventDefault()
    e.shiftKey ? doRedo() : doUndo()
    return
  }
  if (mod && e.key.toLowerCase() === 'y') {
    e.preventDefault()
    doRedo()
    return
  }
  if (isTyping(e)) return
  if (e.code === 'Space') { spaceDown.value = true; e.preventDefault(); return }
  if (e.key === 'f' || e.key === 'F') {
    e.preventDefault()
    fitAll(0.25, 300)
  }
}
function onKeyup(e) {
  if (e.code === 'Space') spaceDown.value = false
}

onMounted(() => {
  document.addEventListener('mouseup', onMouseUp)
  document.addEventListener('keydown', onKeydown)
  document.addEventListener('keyup', onKeyup)
  document.addEventListener('mousedown', onDocMouseDown)
  refreshLlm()
  store.init().then(() => nextTick(() => fitAll(0.3, 300)))
})
function onDocMouseDown(e) {
  if (!e.target.closest?.('.ctx-menu')) closeNodeMenu()
}
onBeforeUnmount(() => {
  document.removeEventListener('mouseup', onMouseUp)
  document.removeEventListener('keydown', onKeydown)
  document.removeEventListener('keyup', onKeyup)
  document.removeEventListener('mousedown', onDocMouseDown)
  cancelBranchHide()
})
</script>

<template>
  <div class="app">
    <header class="toolbar">
      <div class="logo">🌿 分支对话画布</div>

      <!-- 分组一：画布管理 -->
      <div class="tb-group">
        <el-select
          :model-value="store.treeId"
          size="small"
          style="width: 150px"
          placeholder="选择画布"
          @change="switchTree"
        >
          <el-option v-for="t in store.treeList" :key="t.treeId" :label="`${t.title} (${t.nodeCount})`" :value="t.treeId" />
        </el-select>
        <template v-if="store.treeId">
          <template v-if="editingTreeName">
            <input
              v-model="treeNameDraft"
              class="tree-name-input"
              @keydown.enter="saveRenameTree"
              @blur="saveRenameTree"
              v-focus
            />
          </template>
          <el-tooltip content="点击重命名画布" placement="bottom">
            <span class="tree-name" @click="startRenameTree">{{ store.treeTitle || '未命名画布' }} ✏️</span>
          </el-tooltip>
          <el-tooltip
            :content="store.saveStatus === 'saved'
              ? `改动已自动保存到本机${store.lastSavedAt ? '（' + store.lastSavedAt + '）' : ''}`
              : '有改动正在保存…'" placement="bottom"
          >
            <span class="save-state" :class="store.saveStatus">
              {{ store.saveStatus === 'saved' ? '已保存 ✓' : '未保存 ●' }}
            </span>
          </el-tooltip>
        </template>
        <el-button size="small" @click="newTree">＋ 新建画布</el-button>
      </div>

      <div class="tb-divider"></div>

      <!-- 分组二：布局与视图 -->
      <div class="tb-group">
        <el-tooltip content="新建分支后自动按金字塔排布；取消勾选可手动自由摆放" placement="bottom">
          <el-checkbox v-model="autoTidy" size="small" @change="onAutoTidyChange">自动整理</el-checkbox>
        </el-tooltip>
        <el-tooltip content="一键重排：根在顶部居中，逐层向下展开" placement="bottom">
          <el-button size="small" @click="tidyLayout">✨ 整理布局</el-button>
        </el-tooltip>
        <el-tooltip content="缩放到刚好装下全部节点（快捷键 F）" placement="bottom">
          <el-button size="small" @click="fitAll(0.25, 300)">适应视图</el-button>
        </el-tooltip>
        <el-tooltip content="显示 / 隐藏右下角小地图（可按类型着色、拖拽跳转）" placement="bottom">
          <el-button size="small" :type="showMinimap ? 'primary' : ''" plain @click="toggleMinimap">🗺️</el-button>
        </el-tooltip>
        <el-tooltip content="显示 / 隐藏画布网格" placement="bottom">
          <el-button size="small" :type="showGrid ? 'primary' : ''" plain @click="toggleGrid">▦</el-button>
        </el-tooltip>
        <el-tooltip :content="theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'" placement="bottom">
          <el-button size="small" plain @click="toggleTheme">{{ theme === 'dark' ? '☀️' : '🌙' }}</el-button>
        </el-tooltip>
      </div>

      <div class="spacer"></div>

      <!-- 分组三：操作（靠右） -->
      <div class="tb-group">
        <el-tooltip content="撤销上一步操作（Ctrl + Z）" placement="bottom">
          <el-button size="small" :disabled="!store.canUndo" @click="doUndo">↶</el-button>
        </el-tooltip>
        <el-tooltip content="重做被撤销的操作（Ctrl + Shift + Z）" placement="bottom">
          <el-button size="small" :disabled="!store.canRedo" @click="doRedo">↷</el-button>
        </el-tooltip>
        <el-dropdown @command="doExport">
          <el-button size="small">导出 ▾</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="markdown">📝 对话存档（Markdown）</el-dropdown-item>
              <el-dropdown-item command="html">🌐 网页快照（可打印成 PDF）</el-dropdown-item>
              <el-dropdown-item command="mermaid">🧩 结构图（Mermaid 导图）</el-dropdown-item>
              <el-dropdown-item command="json" divided>💾 JSON 备份</el-dropdown-item>
              <el-dropdown-item command="import">📥 导入备份…</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <input ref="importInput" type="file" accept=".json,application/json" style="display: none" @change="onImportFile" />
        <el-tooltip content="删除当前画布的全部节点与对话（需二次确认）" placement="bottom">
          <el-button size="small" type="danger" plain @click="clearCanvas">🗑️ 清空</el-button>
        </el-tooltip>
      </div>

      <div class="tb-divider"></div>

      <el-popover placement="bottom-end" width="300" trigger="click">
        <template #reference>
          <el-button size="small" plain>⌨️</el-button>
        </template>
        <div class="kbd-list">
          <div class="kbd-row"><span>适应视图</span><b>F</b></div>
          <div class="kbd-row"><span>撤销 / 重做</span><b>Ctrl + Z / Ctrl + Shift + Z</b></div>
          <div class="kbd-row"><span>缩放画布</span><b>Ctrl + 滚轮</b></div>
          <div class="kbd-row"><span>平移画布</span><b>空格 + 拖拽 / 滚轮</b></div>
          <div class="kbd-row"><span>框选节点</span><b>Shift + 拖拽</b></div>
          <div class="kbd-row"><span>多选节点</span><b>Ctrl + 点击</b></div>
          <div class="kbd-row"><span>节点菜单</span><b>右键卡片</b></div>
          <div class="kbd-row"><span>划词生分支</span><b>选中回答文字</b></div>
          <div class="kbd-row"><span>重命名节点</span><b>双击标题</b></div>
          <div class="kbd-row"><span>取消划选面板</span><b>Esc</b></div>
        </div>
      </el-popover>

      <el-tooltip content="管理多个密钥档案：添加 / 测试 / 切换当前使用的模型" placement="bottom">
        <el-button size="small" :type="llmInfo.provider === 'mock' ? 'warning' : 'success'" plain @click="openLlmDialog">
          {{ llmInfo.provider === 'mock' ? '🧪 演示模式' : (llmInfo.activeName || providerLabel[llmInfo.provider] || llmInfo.provider) }}
        </el-button>
      </el-tooltip>
    </header>

    <div class="canvas-wrap" :class="{ 'space-pan': spaceDown }" @wheel="onWheel">
      <VueFlow
        v-if="store.treeId"
        :nodes="flowNodes"
        :edges="flowEdges"
        :min-zoom="0.2"
        :max-zoom="2"
        :delete-key-code="null"
        :multi-selection-key-code="'Control'"
        :zoom-on-scroll="false"
        :pan-on-scroll="true"
        :pan-on-scroll-mode="'free'"
        :nodes-draggable="!spaceDown"
        @node-drag-stop="onDragStop"
      >
        <Background
          v-if="showGrid"
          :gap="32"
          :size="1"
          :pattern-color="theme === 'dark' ? '#4a4d55' : '#c9cdd4'"
        />
        <Controls :show-interactive="false" />
        <MiniMap
          v-if="showMinimap"
          pannable
          zoomable
          :node-color="miniColor"
          :node-stroke-width="2"
          :mask-color="theme === 'dark' ? 'rgba(23,23,26,0.72)' : 'rgb(240,240,240,0.7)'"
        />
        <template #node-chat="nodeProps">
          <ChatNode
            :node-id="nodeProps.id"
            @menu="openNodeMenu"
            @child-created="() => { if (autoTidy) store.tidyLayout(false); nextTick(() => fitAll(0.25, 300)) }"
          />
        </template>
      </VueFlow>

      <div v-else class="welcome">
        <div class="welcome-card">
          <h1>🌿 分支对话 AI 画布</h1>
          <p>在 AI 回答中划选任意一段文字，一键拉出独立的子对话分支，无限分叉、可视化探索。</p>
          <div class="welcome-input">
            <el-input
              v-model="welcomeQuestion"
              size="large"
              placeholder="输入你的第一个问题，开始一棵对话树…"
              @keydown.enter="startFromWelcome"
            />
            <el-button type="primary" size="large" @click="startFromWelcome">开始对话</el-button>
          </div>
          <div class="welcome-alt">
            <el-button text size="small" @click="newTree">或先创建一个空白画布</el-button>
          </div>
          <div class="welcome-tip">改动会自动保存 · 右键节点可快速新建分支 / 复制 / 折叠 / 导出</div>
        </div>
      </div>

      <!-- 缩放百分比 -->
      <div v-if="store.treeId" class="zoom-badge">
        <el-tooltip content="缩小（Ctrl + 滚轮向下）" placement="top">
          <span class="zoom-btn" @click="zoomOut({ duration: 150 })">－</span>
        </el-tooltip>
        <span class="zoom-val" @click="fitAll(0.25, 300)" title="点击适应视图">{{ zoomPct }}%</span>
        <el-tooltip content="放大（Ctrl + 滚轮向上）" placement="top">
          <span class="zoom-btn" @click="zoomIn({ duration: 150 })">＋</span>
        </el-tooltip>
      </div>

      <!-- 批量操作条：Ctrl / Shift 多选后出现 -->
      <transition name="fade">
        <div v-if="showBatchBar" class="batch-bar">
          <span class="batch-count">已选中 {{ selectedIds.length }} 个节点</span>
          <el-button size="small" @click="batchDuplicate">📋 批量复制</el-button>
          <el-button size="small" @click="batchExport">📝 导出所选</el-button>
          <el-button size="small" type="danger" plain @click="batchDelete">🗑️ 批量删除</el-button>
          <el-button size="small" text @click="clearSelection">取消选择</el-button>
        </div>
      </transition>
    </div>

    <!-- 划选后弹出的分支面板：直接选模式一键创建 -->
    <div
      v-if="branch.visible"
      class="branch-pop"
      :style="{ left: branch.x + 'px', top: branch.y + 'px' }"
    >
      <div class="branch-pop-text">📌 {{ branch.text }}</div>
      <div class="branch-pop-actions">
        <button class="pop-btn simple" title="仅用选中片段作为上下文" @click="quickCreate('simple')">⚡ 精简</button>
        <button class="pop-btn full" title="继承父节点全部对话历史" @click="quickCreate('full')">📚 完整</button>
      </div>
    </div>

    <!-- 节点右键菜单 -->
    <div
      v-if="ctx.visible && ctxNode"
      class="ctx-menu"
      :style="{ left: ctx.x + 'px', top: ctx.y + 'px' }"
    >
      <div class="ctx-menu-title">🌿 {{ ctxNode.title }}</div>
      <div class="ctx-item" @click="addChildTo(ctx.nodeId)">➕ 新增子分支</div>
      <div class="ctx-item" @click="ctxDuplicate(false)">📋 复制本节点</div>
      <div class="ctx-item" @click="ctxDuplicate(true)">🌳 复制整条分支</div>
      <div class="ctx-item" @click="ctxToggleCollapse">
        {{ ctxNode.isCollapsed ? '📂 展开该分支' : '📦 折叠该分支' }}
      </div>
      <div class="ctx-item" @click="ctxStar">{{ ctxNode.starred ? '★ 取消收藏' : '☆ 收藏节点' }}</div>
      <div class="ctx-item" @click="exportBranch(ctx.nodeId)">📝 导出此分支</div>
      <div class="ctx-item danger" @click="ctxDelete">🗑️ 删除节点（含子树）</div>
    </div>

    <!-- 模型与密钥管理：可添加多个 Key，随时切换启用 -->
    <el-dialog v-model="llmDialog" title="⚙️ 模型与密钥管理" width="780px">
      <el-alert v-if="llmInfo.provider === 'mock'" type="warning" :closable="false" show-icon
        title="当前为演示模式，回答是模拟内容。切换到「云端 API」或「本地 Ollama」并添加一个密钥即可接入真实大模型。" style="margin-bottom: 14px;" />
      <div class="mode-title">模型来源</div>
      <el-radio-group :model-value="llmInfo.provider" style="margin-bottom: 16px;" @change="setProvider">
        <el-radio-button value="mock">演示模式（免 Key）</el-radio-button>
        <el-radio-button value="openai">云端 API</el-radio-button>
        <el-radio-button value="ollama">本地 Ollama</el-radio-button>
      </el-radio-group>

      <template v-if="llmInfo.provider !== 'mock'">
        <div class="prof-head">
          <span class="mode-title" style="margin: 0;">密钥档案（{{ llmInfo.profiles.length }}）</span>
          <el-button size="small" type="primary" plain @click="startEdit(null)">➕ 新增密钥</el-button>
        </div>

        <div v-if="!llmInfo.profiles.length && !editing" class="prof-empty">
          还没有密钥档案，点右上角「新增密钥」添加第一个（可添加多个，随时切换）。
        </div>

        <div
          v-for="p in llmInfo.profiles" :key="p.id"
          class="prof-row" :class="{ active: p.id === llmInfo.activeId }"
        >
          <div class="prof-main">
            <div class="prof-name">
              <span class="prof-dot" :class="{ on: p.id === llmInfo.activeId }"></span>
              {{ p.name }}
              <span class="prof-tag">{{ p.provider === 'ollama' ? '本地' : '云端' }}</span>
              <span v-if="p.id === llmInfo.activeId" class="prof-tag on">启用中</span>
            </div>
            <div class="prof-meta">{{ p.baseUrl }} · 模型 {{ p.model }} · Key {{ p.keyMasked || '未填写' }}</div>
            <div v-if="p.lastTest" class="prof-test" :class="p.lastTest.ok ? 'ok' : 'fail'">
              {{ p.lastTest.ok ? '✅' : '❌' }} {{ p.lastTest.msg }}
              <span class="prof-ts">{{ p.lastTest.ts }}</span>
            </div>
            <div v-else class="prof-test dim">尚未测试</div>
            <div v-if="p.lastTest?.models?.length && !p.lastTest.models.includes(p.model)" class="model-chips">
              <span class="chips-label">该 Key 可用模型（点击切换）：</span>
              <el-tag
                v-for="m in p.lastTest.models" :key="m"
                size="small" class="model-chip" effect="plain" @click="pickModel(p, m)"
              >{{ m }}</el-tag>
            </div>
          </div>
          <div class="prof-ops">
            <el-button v-if="p.id !== llmInfo.activeId" size="small" @click="useProfile(p)">启用</el-button>
            <el-button size="small" :loading="testingKey === p.id" @click="testSaved(p)">测试</el-button>
            <el-button size="small" @click="startEdit(p)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="removeProfile(p)">删除</el-button>
          </div>
        </div>

        <!-- 新增 / 编辑表单 -->
        <div v-if="editing" class="prof-form">
          <div class="mode-title">{{ editing.id ? '编辑密钥档案' : '新增密钥档案' }}</div>
          <div class="form-row">
            <span class="form-label">名称</span>
            <el-input v-model="editing.name" size="small" placeholder="例如：DeepSeek 主号 / 豆包备用" />
          </div>
          <div class="form-row">
            <span class="form-label">类型</span>
            <el-radio-group v-model="editing.provider" size="small">
              <el-radio-button value="openai">云端 API</el-radio-button>
              <el-radio-button value="ollama">本地 Ollama</el-radio-button>
            </el-radio-group>
          </div>
          <div class="form-row">
            <span class="form-label">地址</span>
            <el-input v-model="editing.baseUrl" size="small"
              :placeholder="editing.provider === 'ollama' ? 'http://localhost:11434' : 'https://api.deepseek.com'" />
          </div>
          <div class="form-row">
            <span class="form-label">API Key</span>
            <el-input v-model="editing.apiKey" size="small" type="password" show-password
              :placeholder="editing.id && llmInfo.profiles.find(x => x.id === editing.id)?.keyMasked
                ? `已保存：${llmInfo.profiles.find(x => x.id === editing.id).keyMasked}（留空则不修改）`
                : '粘贴你的 API Key'" />
          </div>
          <div class="form-row">
            <span class="form-label">模型</span>
            <el-input v-model="editing.model" size="small"
              :placeholder="editing.provider === 'ollama' ? 'qwen2.5:7b' : 'deepseek-chat'" />
          </div>
          <div class="mode-desc">
            兼容 DeepSeek、豆包、通义、OpenAI 等任何 OpenAI 协议端点，改地址和模型名即可。
            密钥只保存在本机，不会上传到别处。
          </div>
          <div class="prof-form-ops">
            <el-button size="small" :loading="testingKey === 'new'" @click="testDraft">测试连接</el-button>
            <el-button size="small" type="primary" :loading="llmSaving" @click="saveProfile">保存并启用</el-button>
            <el-button size="small" @click="editing = null">取消</el-button>
          </div>
          <div v-if="testResults['new']" class="llm-test-result" :class="testClass(testResults['new'])">
            {{ testText(testResults['new']) }}
          </div>
          <div v-if="testResults['new']?.models?.length" class="model-chips">
            <span class="chips-label">该 Key 可用模型（点击填入）：</span>
            <el-tag
              v-for="m in testResults['new'].models" :key="m"
              size="small" class="model-chip" effect="plain" @click="editing.model = m"
            >{{ m }}</el-tag>
          </div>
        </div>
      </template>

      <template v-if="llmInfo.provider === 'mock'">
        <div class="mode-desc">演示模式无需任何配置，回答为模拟内容，用于体验划选分支等完整交互。</div>
      </template>

      <template #footer>
        <el-button @click="llmDialog = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
export default {
  directives: {
    focus: { mounted: (el) => el.focus() }
  }
}
</script>
