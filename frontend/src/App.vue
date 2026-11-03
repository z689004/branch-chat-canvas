<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useTreeStore } from './store/tree'
import { exportTree, getLlmConfig, updateLlmConfig, testLlm, isStandalone } from './api'
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

// ---------- 模型设置 ----------
const llmDialog = ref(false)
const llmForm = reactive({
  provider: 'mock',
  openaiBaseUrl: 'https://api.deepseek.com',
  openaiApiKey: '',
  llmModel: 'deepseek-chat',
  ollamaBaseUrl: 'http://localhost:11434',
  ollamaModel: 'qwen2.5:7b'
})
const llmInfo = reactive({ provider: 'mock', keyMasked: '', hasKey: false })
const llmSaving = ref(false)
const llmTesting = ref(false)
const llmTestResult = ref(null)

const providerLabel = { mock: '🧪 演示模式', openai: '☁️ 云端 API', ollama: '🖥️ 本地 Ollama' }

async function openLlmDialog() {
  llmTestResult.value = null
  try {
    const cfg = await getLlmConfig()
    Object.assign(llmInfo, { provider: cfg.provider, keyMasked: cfg.keyMasked, hasKey: cfg.hasKey })
    Object.assign(llmForm, {
      provider: cfg.provider,
      openaiBaseUrl: cfg.openaiBaseUrl,
      openaiApiKey: '',
      llmModel: cfg.llmModel,
      ollamaBaseUrl: cfg.ollamaBaseUrl,
      ollamaModel: cfg.ollamaModel
    })
  } catch (e) { /* ignore */ }
  llmDialog.value = true
}

async function saveLlmConfig() {
  llmSaving.value = true
  try {
    const patch = { provider: llmForm.provider }
    if (llmForm.provider === 'openai') {
      patch.openaiBaseUrl = llmForm.openaiBaseUrl
      patch.llmModel = llmForm.llmModel
      if (llmForm.openaiApiKey.trim()) patch.openaiApiKey = llmForm.openaiApiKey.trim()
    } else if (llmForm.provider === 'ollama') {
      patch.ollamaBaseUrl = llmForm.ollamaBaseUrl
      patch.ollamaModel = llmForm.ollamaModel
    }
    const cfg = await updateLlmConfig(patch)
    Object.assign(llmInfo, { provider: cfg.provider, keyMasked: cfg.keyMasked, hasKey: cfg.hasKey })
    ElMessage.success('模型配置已保存，立即生效')
  } catch (e) {
    ElMessage.error(e.message)
  } finally { llmSaving.value = false }
}

async function runLlmTest() {
  llmTesting.value = true
  llmTestResult.value = null
  try {
    llmTestResult.value = await testLlm()
  } catch (e) {
    llmTestResult.value = { ok: false, error: e.message }
  } finally { llmTesting.value = false }
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
      <el-tooltip content="配置大模型 / 填入自己的 API Key" placement="bottom">
        <el-button size="small" :type="llmInfo.provider === 'mock' ? 'warning' : 'success'" plain @click="openLlmDialog">
          {{ providerLabel[llmInfo.provider] || llmInfo.provider }}
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

    <!-- 模型设置对话框 -->
    <el-dialog v-model="llmDialog" title="⚙️ 模型设置" width="520px">
      <el-alert v-if="llmInfo.provider === 'mock'" type="warning" :closable="false" show-icon
        title="当前为演示模式，回答是模拟内容。选择云端 API 并填入自己的 Key 即可接入真实大模型。" style="margin-bottom: 14px;" />
      <div class="mode-title">模型来源</div>
      <el-radio-group v-model="llmForm.provider" style="margin-bottom: 16px;">
        <el-radio-button value="mock">演示模式（免 Key）</el-radio-button>
        <el-radio-button value="openai">云端 API</el-radio-button>
        <el-radio-button value="ollama">本地 Ollama</el-radio-button>
      </el-radio-group>

      <template v-if="llmForm.provider === 'openai'">
        <div class="mode-title">API 地址（OpenAI 兼容协议）</div>
        <el-input v-model="llmForm.openaiBaseUrl" placeholder="https://api.deepseek.com" style="margin-bottom: 12px;" />
        <div class="mode-title">API Key</div>
        <el-input v-model="llmForm.openaiApiKey" type="password" show-password
          :placeholder="llmInfo.hasKey ? `已保存：${llmInfo.keyMasked}（留空则不修改）` : '粘贴你的 API Key'"
          style="margin-bottom: 12px;" />
        <div class="mode-title">模型名称</div>
        <el-input v-model="llmForm.llmModel" placeholder="deepseek-chat / deepseek-reasoner / douban-..." style="margin-bottom: 6px;" />
        <div class="mode-desc">兼容 DeepSeek、豆包、通义、OpenAI 等任何 OpenAI 协议端点，改地址和模型名即可。Key 保存在本机后端，不会上传到别处。</div>
      </template>

      <template v-if="llmForm.provider === 'ollama'">
        <div class="mode-title">Ollama 地址</div>
        <el-input v-model="llmForm.ollamaBaseUrl" placeholder="http://localhost:11434" style="margin-bottom: 12px;" />
        <div class="mode-title">模型名称</div>
        <el-input v-model="llmForm.ollamaModel" placeholder="qwen2.5:7b" />
      </template>

      <template v-if="llmForm.provider === 'mock'">
        <div class="mode-desc">演示模式无需任何配置，回答为模拟内容，用于体验划选分支等完整交互。</div>
      </template>

      <div v-if="llmTestResult" class="llm-test-result" :class="llmTestResult.ok ? 'ok' : 'fail'">
        {{ llmTestResult.ok ? `✅ 连接成功，模型返回：${llmTestResult.sample}` : `❌ ${llmTestResult.error}` }}
      </div>

      <template #footer>
        <el-button :loading="llmTesting" @click="runLlmTest">测试连接</el-button>
        <el-button type="primary" :loading="llmSaving" @click="saveLlmConfig">保存</el-button>
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
