/**
 * 纯前端模式：无需任何后端服务，双击网页即可使用。
 * - 所有对话树保存在浏览器 localStorage
 * - AI 由浏览器直接调用 OpenAI 兼容 API / 本地 Ollama / 演示模式
 */

const TREES_KEY = 'bcc:trees'
const CFG_KEY = 'bcc:llmConfig'
const ROOT_TITLE_DEFAULT = '根对话'
const CHILD_TITLE_DEFAULT = '新分支'

const SYSTEM_PROMPT =
  '你是「分支对话画布」中的 AI 助手。用户在无限画布上围绕某个主题以树状分支的方式与你讨论，' +
  '子分支往往基于从父级回答中划选的一段文字进行追问。' +
  '请用简体中文、结构清晰的 Markdown 回答，紧扣用户给出的上下文，简洁、准确、有深度。'

const DEFAULT_CFG = {
  provider: 'mock',
  openaiBaseUrl: 'https://api.deepseek.com',
  openaiApiKey: '',
  llmModel: 'deepseek-chat',
  ollamaBaseUrl: 'http://localhost:11434',
  ollamaModel: 'qwen2.5:7b'
}

// ---------------- 基础工具 ----------------

function uid() {
  try {
    if (globalThis.crypto?.randomUUID) return crypto.randomUUID().replace(/-/g, '')
  } catch (e) { /* ignore */ }
  return Math.random().toString(16).slice(2) + Date.now().toString(16)
}

function now() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function loadAll() {
  try { return JSON.parse(localStorage.getItem(TREES_KEY) || '{}') } catch (e) { return {} }
}
function saveAll(all) {
  localStorage.setItem(TREES_KEY, JSON.stringify(all))
}
function readTree(treeId) {
  const t = loadAll()[treeId]
  if (!t) throw new Error('画布不存在')
  return t
}
function writeTree(tree) {
  tree.updateTime = now()
  const all = loadAll()
  all[tree.treeId] = tree
  saveAll(all)
}

function newTreeObj(title) {
  const t = now()
  return {
    treeId: `tree-${uid().slice(0, 12)}`,
    title: title || '未命名画布',
    nodeList: [],
    createTime: t,
    updateTime: t
  }
}

function newNode(parentId, title, selectedContext = '', contextMode = 'simple', x = 0, y = 0) {
  const t = now()
  return {
    nodeId: uid(),
    parentId,
    title,
    selectedContext,
    contextMode,
    messages: [],
    x,
    y,
    isCollapsed: false,
    createTime: t,
    updateTime: t
  }
}

const isDefaultTitle = (t) => [ROOT_TITLE_DEFAULT, CHILD_TITLE_DEFAULT, '新对话', '新分支'].includes(t)

// ---------------- 树级接口 ----------------

export async function listTrees() {
  const all = loadAll()
  return Object.values(all)
    .map((t) => ({
      treeId: t.treeId,
      title: t.title || '未命名画布',
      nodeCount: (t.nodeList || []).length,
      updateTime: t.updateTime || ''
    }))
    .sort((a, b) => (b.updateTime || '').localeCompare(a.updateTime || ''))
}

export async function createTree(title) {
  const tree = newTreeObj(title)
  const root = newNode(null, ROOT_TITLE_DEFAULT, '', 'simple', 0, 0)
  tree.nodeList.push(root)
  writeTree(tree)
  return tree
}

export async function getTree(treeId) {
  return JSON.parse(JSON.stringify(readTree(treeId)))
}

export async function renameTreeApi(treeId, title) {
  const tree = readTree(treeId)
  tree.title = title
  writeTree(tree)
  return { ok: true, title }
}

export async function deleteTreeApi(treeId) {
  const all = loadAll()
  delete all[treeId]
  saveAll(all)
  return { ok: true }
}

// ---------------- 节点级接口 ----------------

export async function createChildNode(payload) {
  const tree = readTree(payload.treeId)
  const parent = tree.nodeList.find((n) => n.nodeId === payload.parentId)
  if (!parent) throw new Error('父节点不存在')
  const idx = tree.nodeList.filter((n) => n.parentId === payload.parentId).length
  const x = payload.x != null ? payload.x : parent.x + 460
  const y = payload.y != null ? payload.y : parent.y + idx * 280 - (idx > 0 ? 140 : 0)
  const child = newNode(
    payload.parentId,
    payload.title || CHILD_TITLE_DEFAULT,
    payload.selectedContext || '',
    payload.contextMode === 'full' ? 'full' : 'simple',
    x, y
  )
  tree.nodeList.push(child)
  writeTree(tree)
  return child
}

export async function updateNodeApi(payload) {
  const tree = readTree(payload.treeId)
  const node = tree.nodeList.find((n) => n.nodeId === payload.nodeId)
  if (!node) throw new Error('节点不存在')
  if (payload.title != null) node.title = payload.title
  if (payload.isCollapsed != null) node.isCollapsed = payload.isCollapsed
  if (payload.contextMode === 'simple' || payload.contextMode === 'full') node.contextMode = payload.contextMode
  if (payload.x != null) node.x = payload.x
  if (payload.y != null) node.y = payload.y
  node.updateTime = now()
  writeTree(tree)
  return node
}

export async function deleteNodeApi(treeId, nodeId) {
  const tree = readTree(treeId)
  const doomed = new Set([nodeId])
  let changed = true
  while (changed) {
    changed = false
    for (const n of tree.nodeList) {
      if (doomed.has(n.parentId) && !doomed.has(n.nodeId)) { doomed.add(n.nodeId); changed = true }
    }
  }
  tree.nodeList = tree.nodeList.filter((n) => !doomed.has(n.nodeId))
  writeTree(tree)
  return { ok: true, deleted: doomed.size }
}

// ---------------- 导出 ----------------

function walkMarkdown(tree, parentId, depth, lines) {
  const kids = tree.nodeList.filter((n) => n.parentId === parentId)
  for (const n of kids) {
    lines.push(`${'#'.repeat(Math.min(depth, 6))} ${n.parentId ? '🌿 ' : '🌱 '}${n.title}`)
    const meta = [`上下文：${n.contextMode === 'full' ? '完整模式' : '精简模式'}`]
    if (n.selectedContext) meta.push(`选中片段：「${n.selectedContext.slice(0, 80)}」`)
    lines.push(`> ${meta.join(' ｜ ')}`)
    for (const m of n.messages || []) {
      lines.push(`${m.role === 'user' ? '**🙋 用户**' : '**🤖 AI**'}：${m.content}\n`)
    }
    lines.push('')
    walkMarkdown(tree, n.nodeId, depth + 1, lines)
  }
}

export async function exportTree(treeId, format) {
  const tree = readTree(treeId)
  if (format === 'json') {
    return { text: JSON.stringify(tree, null, 2), filename: `${tree.title}.json` }
  }
  if (format === 'mermaid') {
    const lines = ['graph TD']
    const idmap = {}
    tree.nodeList.forEach((n, i) => {
      const nid = `n${i}`
      idmap[n.nodeId] = nid
      lines.push(`    ${nid}["${(n.title || '').replace(/"/g, "'")}"]`)
    })
    for (const n of tree.nodeList) {
      if (n.parentId && idmap[n.parentId]) lines.push(`    ${idmap[n.parentId]} --> ${idmap[n.nodeId]}`)
    }
    return { text: lines.join('\n'), filename: `${tree.title}.mmd` }
  }
  const lines = [`# ${tree.title}（分支对话树）`, '']
  walkMarkdown(tree, null, 1, lines)
  return { text: lines.join('\n'), filename: `${tree.title}.md` }
}

// ---------------- 模型配置 ----------------

export function getLlmConfig() {
  let cfg = {}
  try { cfg = JSON.parse(localStorage.getItem(CFG_KEY) || '{}') } catch (e) { cfg = {} }
  const merged = { ...DEFAULT_CFG, ...cfg }
  const key = merged.openaiApiKey || ''
  return {
    provider: merged.provider,
    openaiBaseUrl: merged.openaiBaseUrl,
    llmModel: merged.llmModel,
    ollamaBaseUrl: merged.ollamaBaseUrl,
    ollamaModel: merged.ollamaModel,
    hasKey: !!key,
    keyMasked: key ? (key.length > 8 ? `${key.slice(0, 4)}****${key.slice(-4)}` : '****') : ''
  }
}

export function updateLlmConfig(patch) {
  let cfg = {}
  try { cfg = JSON.parse(localStorage.getItem(CFG_KEY) || '{}') } catch (e) { cfg = {} }
  const merged = { ...DEFAULT_CFG, ...cfg }
  for (const k of Object.keys(DEFAULT_CFG)) {
    if (patch[k] != null) merged[k] = String(patch[k]).trim()
  }
  if (!['mock', 'openai', 'ollama'].includes(merged.provider)) merged.provider = 'mock'
  localStorage.setItem(CFG_KEY, JSON.stringify(merged))
  return getLlmConfig()
}

function fullConfig() {
  let cfg = {}
  try { cfg = JSON.parse(localStorage.getItem(CFG_KEY) || '{}') } catch (e) { cfg = {} }
  return { ...DEFAULT_CFG, ...cfg }
}

export async function testLlm() {
  try {
    let sample = ''
    await streamChat([{ role: 'user', content: '请只回复两个字：成功' }], (c) => { sample += c })
    return { ok: true, sample: sample.slice(0, 60) }
  } catch (e) {
    return { ok: false, error: e.message }
  }
}

// ---------------- 大模型调用（浏览器直连） ----------------

function corsHint(err) {
  const m = String(err && err.message ? err.message : err)
  if (/Failed to fetch|NetworkError|Load failed/i.test(m)) {
    return '浏览器直连失败：可能是网络不通，或该 API 不允许跨域（CORS）访问。可换用 DeepSeek 官方地址，或改用后端模式运行。'
  }
  return m
}

async function readStream(resp, onDelta) {
  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''
  let answer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop()
    for (const raw of lines) {
      const line = raw.trim()
      if (!line) continue
      if (line.startsWith('data:')) {
        const data = line.slice(5).trim()
        if (data === '[DONE]') return answer
        try {
          const delta = JSON.parse(data)?.choices?.[0]?.delta?.content
          if (delta) { answer += delta; onDelta(delta) }
        } catch (e) { /* 忽略半包 */ }
      } else {
        // Ollama 的 NDJSON
        try {
          const obj = JSON.parse(line)
          const c = obj?.message?.content
          if (c) { answer += c; onDelta(c) }
          if (obj?.done) return answer
        } catch (e) { /* ignore */ }
      }
    }
  }
  return answer
}

async function streamOpenAI(messages, cfg, onDelta) {
  if (!cfg.openaiApiKey) throw new Error('未配置 API Key，请点击右上角「模型设置」填入密钥')
  const base = (cfg.openaiBaseUrl || '').replace(/\/+$/, '')
  const resp = await fetch(`${base}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${cfg.openaiApiKey}`
    },
    body: JSON.stringify({ model: cfg.llmModel, messages, stream: true })
  })
  if (resp.status === 401 || resp.status === 403) throw new Error(`鉴权失败(${resp.status})，请检查 API Key 是否正确`)
  if (!resp.ok) {
    let detail = ''
    try { detail = (await resp.text()).slice(0, 200) } catch (e) { /* ignore */ }
    throw new Error(`请求失败(${resp.status}) ${detail}`)
  }
  return readStream(resp, onDelta)
}

async function streamOllama(messages, cfg, onDelta) {
  const base = (cfg.ollamaBaseUrl || '').replace(/\/+$/, '')
  const resp = await fetch(`${base}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: cfg.ollamaModel, messages, stream: true })
  })
  if (!resp.ok) throw new Error(`本地 Ollama 请求失败(${resp.status})，请确认 Ollama 已启动并允许跨域（OLLAMA_ORIGINS=*）`)
  return readStream(resp, onDelta)
}

async function streamMock(messages, onDelta) {
  let question = ''
  let context = ''
  for (const m of messages) {
    if (m.role !== 'user') continue
    if (m.content.startsWith('【关注片段】') || m.content.startsWith('以下是选中的原文片段')) context = m.content
    else question = m.content
  }
  const answer = `> 🧪 **演示模式回答**（未配置大模型，返回模拟内容，交互流程与真实模型完全一致）

**你的问题：** ${question || '（空）'}

**当前上下文片段：** ${context ? context.replace(/\n/g, ' ').slice(0, 120) : '（本节点无选中片段）'}

### 回答结构示例

1. **概念澄清** —— 这里会先解释问题涉及的核心概念；
2. **举例说明** —— 用一个具体例子帮助理解；
3. **延伸追问** —— 可以在本回答中**划选任意一段文字**，点弹出按钮创建子分支，继续深挖。

### 接入真实大模型

点击右上角「🧪 演示模式」→ 选择「云端 API」→ 填入 DeepSeek / 豆包 / OpenAI 等的 API Key → 测试连接 → 保存，即可立即生效。`
  for (let i = 0; i < answer.length; i += 3) {
    const piece = answer.slice(i, i + 3)
    onDelta(piece)
    await new Promise((r) => setTimeout(r, 12))
  }
  return answer
}

async function streamChat(messages, onDelta) {
  const cfg = fullConfig()
  try {
    if (cfg.provider === 'openai') return await streamOpenAI(messages, cfg, onDelta)
    if (cfg.provider === 'ollama') return await streamOllama(messages, cfg, onDelta)
    return await streamMock(messages, onDelta)
  } catch (e) {
    throw new Error(corsHint(e))
  }
}

// ---------------- 上下文构造 ----------------

function buildMessages(tree, node, question) {
  const mode = node.contextMode || 'simple'
  if (mode === 'full') {
    const byId = Object.fromEntries(tree.nodeList.map((n) => [n.nodeId, n]))
    const chain = []
    let cur = node
    while (cur) { chain.push(cur); cur = byId[cur.parentId] }
    const msgs = [{ role: 'system', content: SYSTEM_PROMPT }]
    for (const anc of chain.reverse()) {
      if (anc.selectedContext) msgs.push({ role: 'user', content: `【关注片段】${anc.selectedContext}` })
      msgs.push(...(anc.messages || []))
    }
    msgs.push({ role: 'user', content: question })
    return msgs
  }
  const msgs = [{ role: 'system', content: SYSTEM_PROMPT }]
  if (node.selectedContext) {
    msgs.push({ role: 'user', content: `以下是选中的原文片段：\n「${node.selectedContext}」\n\n请基于这段内容回答我接下来的问题。` })
    msgs.push({ role: 'assistant', content: '好的，我会围绕这段内容来回答你的问题。' })
  }
  msgs.push({ role: 'user', content: question })
  return msgs
}

/**
 * 流式提问：onChunk 逐段回调，返回完整回答；同时把消息写回本地存储。
 */
export async function sendQuestionStream(treeId, nodeId, content, onChunk) {
  const tree = readTree(treeId)
  const node = tree.nodeList.find((n) => n.nodeId === nodeId)
  if (!node) throw new Error('节点不存在')
  const messages = buildMessages(tree, node, content)
  const answer = await streamChat(messages, (c) => onChunk && onChunk(c))
  // 写回存储（当前轮的 user/assistant 消息）
  const fresh = readTree(treeId)
  const target = fresh.nodeList.find((n) => n.nodeId === nodeId)
  if (target) {
    target.messages.push({ role: 'user', content })
    target.messages.push({ role: 'assistant', content: answer })
    if (isDefaultTitle(target.title)) target.title = content.slice(0, 20)
    target.updateTime = now()
    writeTree(fresh)
  }
  return answer
}
