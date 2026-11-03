<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useTreeStore } from './store/tree'
import {
  exportTree, getLlmConfig, updateLlmConfig, testLlm,
  saveLlmProfile, deleteLlmProfile, activateLlmProfile
} from './api'
import ChatNode from './components/ChatNode.vue'

const store = useTreeStore()
const { fitView } = useVueFlow()

const flowNodes = computed(() =>
  store.visibleNodes.map(n => ({
    id: n.nodeId,
    type: 'chat',
    position: { x: n.x, y: n.y },
    data: { nodeId: n.nodeId }
  }))
)

const flowEdges = computed(() =>
  store.visibleNodes
    .filter(n => n.parentId && store.nodeMap[n.parentId])
    .map(n => ({
      id: `e-${n.parentId}-${n.nodeId}`,
      source: n.parentId,
      target: n.nodeId,
      // 金字塔布局：连线从父节点底部出发，接到子节点顶部
      type: 'smoothstep',
      sourcePosition: 'bottom',
      targetPosition: 'top',
      animated: false,
      style: { stroke: '#a8b3c5', strokeWidth: 2 },
      markerEnd: { type: 'arrowclosed', color: '#a8b3c5' }
    }))
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
      // 已取消选中：面板保留 1.5 秒后消失
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
    if (autoTidy.value) store.tidyLayout()
    ElMessage.success(mode === 'simple' ? '已创建精简分支，去新节点继续追问吧' : '已创建完整分支，去新节点继续追问吧')
    nextTick(() => fitView({ padding: 0.25, duration: 400 }))
  } catch (e) {
    ElMessage.error(e.message)
  }
}

// ---------- 画布操作 ----------
async function newTree() {
  try { await store.newTree(); ElMessage.success('新画布已创建'); nextTick(() => fitView({ padding: 0.3, duration: 300 })) }
  catch (e) { ElMessage.error(e.message) }
}
async function switchTree(treeId) {
  try { await store.loadTree(treeId); nextTick(() => fitView({ padding: 0.25, duration: 300 })) }
  catch (e) { ElMessage.error(e.message) }
}
async function doExport(format) {
  if (!store.treeId) return
  try {
    const { text, filename } = await exportTree(store.treeId, format)
    const mime = format === 'json' ? 'application/json'
      : format === 'mermaid' ? 'text/plain' : 'text/markdown'
    const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }))
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 3000)
    ElMessage.success('已导出')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function clearCanvas() {
  if (!store.treeId) return
  try {
    await ElMessageBox.confirm(
      '将删除当前画布的全部节点与对话记录，且不可恢复。确认清空？',
      '清空画布',
      { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' }
    )
  } catch (e) { return }
  try {
    await store.clearCanvas()
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

// ---------- 画布辅助 ----------
const showMinimap = ref(true)
const editingTreeName = ref(false)
const treeNameDraft = ref('')

function toggleMinimap() {
  showMinimap.value = !showMinimap.value
  nextTick(() => fitView({ padding: 0.25, duration: 300 }))
}
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
  nextTick(() => fitView({ padding: 0.2, duration: 400 }))
}
function onAutoTidyChange(v) {
  localStorage.setItem(AUTO_TIDY_KEY, v ? '1' : '0')
  if (v) tidyLayout()
}
function onKeydown(e) {
  if (e.key === 'Escape') {
    window.getSelection()?.removeAllRanges()
    branch.visible = false
  }
}

onMounted(() => {
  document.addEventListener('mouseup', onMouseUp)
  document.addEventListener('keydown', onKeydown)
  refreshLlm()
  store.init().then(() => nextTick(() => fitView({ padding: 0.3, duration: 300 })))
})
onBeforeUnmount(() => {
  document.removeEventListener('mouseup', onMouseUp)
  document.removeEventListener('keydown', onKeydown)
  cancelBranchHide()
})
</script>

<template>
  <div class="app">
    <header class="toolbar">
      <div class="logo">🌿 分支对话画布</div>
      <el-select
        :model-value="store.treeId"
        size="small"
        style="width: 170px"
        placeholder="选择画布"
        @change="switchTree"
      >
        <el-option v-for="t in store.treeList" :key="t.treeId" :label="`${t.title} (${t.nodeCount})`" :value="t.treeId" />
      </el-select>
      <!-- 画布名称：可点击编辑 -->
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
      </template>
      <el-button size="small" @click="newTree">＋ 新建画布</el-button>
      <div class="tb-divider"></div>
      <el-tooltip content="选中 AI 回答文本 → 弹出按钮，新建子对话分支" placement="bottom">
        <span class="hint-tag">💡 划词创建分支</span>
      </el-tooltip>
      <div class="spacer"></div>
      <el-tooltip content="新建分支后自动按金字塔排布；取消勾选可手动自由摆放" placement="bottom">
        <el-checkbox v-model="autoTidy" size="small" style="margin-right: 4px;" @change="onAutoTidyChange">自动整理</el-checkbox>
      </el-tooltip>
      <el-tooltip content="把节点整理成金字塔对话树：根在顶部居中，逐层向下展开" placement="bottom">
        <el-button size="small" @click="tidyLayout">✨ 整理布局</el-button>
      </el-tooltip>
      <el-button size="small" @click="fitView({ padding: 0.25, duration: 300 })">适应视图</el-button>
      <el-tooltip content="显示 / 隐藏右下角小地图" placement="bottom">
        <el-button size="small" :type="showMinimap ? 'primary' : ''" plain @click="toggleMinimap">🗺️ 小地图</el-button>
      </el-tooltip>
      <div class="tb-divider"></div>
      <el-tooltip content="删除当前画布的全部节点与对话" placement="bottom">
        <el-button size="small" type="danger" plain @click="clearCanvas">🗑️ 清空</el-button>
      </el-tooltip>
      <el-dropdown @command="doExport">
        <el-button size="small">导出 ▾</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="markdown">📝 对话树 Markdown</el-dropdown-item>
            <el-dropdown-item command="mermaid">🧩 Mermaid 导图代码</el-dropdown-item>
            <el-dropdown-item command="json">💾 JSON（备份）</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <div class="tb-divider"></div>
      <el-tooltip content="管理多个密钥档案：添加 / 测试 / 切换当前使用的模型" placement="bottom">
        <el-button size="small" :type="llmInfo.provider === 'mock' ? 'warning' : 'success'" plain @click="openLlmDialog">
          {{ llmInfo.provider === 'mock' ? '🧪 演示模式' : (llmInfo.activeName || providerLabel[llmInfo.provider] || llmInfo.provider) }}
        </el-button>
      </el-tooltip>
    </header>

    <div class="canvas-wrap">
      <VueFlow
        v-if="store.treeId"
        :nodes="flowNodes"
        :edges="flowEdges"
        :min-zoom="0.2"
        :max-zoom="2"
        :delete-key-code="null"
        @node-drag-stop="onDragStop"
      >
        <Background :gap="20" />
        <Controls />
        <MiniMap v-if="showMinimap" pannable zoomable />
        <template #node-chat="nodeProps">
          <ChatNode :node-id="nodeProps.id" />
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
        </div>
      </div>
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
