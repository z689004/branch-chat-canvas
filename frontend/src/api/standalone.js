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
  profiles: [],
  activeId: null,
  openaiBaseUrl: 'https://api.deepseek.com',
  openaiApiKey: '',
  llmModel: 'deepseek-chat',
  ollamaBaseUrl: 'http://localhost:11434',
  ollamaModel: 'qwen2.5:7b'
}
const DEFAULT_BASE = { openai: 'https://api.deepseek.com', ollama: 'http://localhost:11434' }
const DEFAULT_MODEL = { openai: 'deepseek-chat', ollama: 'qwen2.5:7b' }

// ---------------- 密钥档案工具 ----------------

function maskKey(key) {
  if (!key) return ''
  return key.length > 8 ? `${key.slice(0, 4)}****${key.slice(-4)}` : '****'
}

function normalizeProfile(raw) {
  const r = raw || {}
  let provider = String(r.provider || 'openai').trim().toLowerCase()
  if (provider !== 'ollama') provider = 'openai'
  return {
    id: r.id || uid(),
    name: String(r.name || '').trim() || '未命名密钥',
    provider,
    baseUrl: String(r.baseUrl || DEFAULT_BASE[provider]).trim().replace(/\/+$/, ''),
    apiKey: String(r.apiKey || '').trim(),
    model: String(r.model || DEFAULT_MODEL[provider]).trim(),
    lastTest: r.lastTest && typeof r.lastTest === 'object' ? r.lastTest : null
  }
}

function publicProfile(p) {
  return {
    id: p.id, name: p.name, provider: p.provider,
    baseUrl: p.baseUrl, model: p.model,
    hasKey: !!p.apiKey, keyMasked: maskKey(p.apiKey),
    lastTest: p.lastTest || null
  }
}

function rawCfg() {
  let cfg = {}
  try { cfg = JSON.parse(localStorage.getItem(CFG_KEY) || '{}') } catch (e) { cfg = {} }
  return { ...DEFAULT_CFG, ...cfg }
}

function saveRaw(cfg) {
  localStorage.setItem(CFG_KEY, JSON.stringify(cfg))
  return cfg
}

/** 旧版「单一配置」自动迁移为第一个密钥档案 */
function migrateCfg(cfg) {
  if (Array.isArray(cfg.profiles) && cfg.profiles.length) return cfg
  const profiles = []
  if (cfg.openaiApiKey) {
    profiles.push(normalizeProfile({
      name: '云端模型（原有配置）',
      provider: 'openai',
      baseUrl: cfg.openaiBaseUrl,
      apiKey: cfg.openaiApiKey,
      model: cfg.llmModel
    }))
  }
  if (cfg.provider === 'ollama' || cfg.ollamaBaseUrl) {
    profiles.push(normalizeProfile({
      name: '本地 Ollama（原有配置）',
      provider: 'ollama',
      baseUrl: cfg.ollamaBaseUrl,
      model: cfg.ollamaModel
    }))
  }
  cfg.profiles = profiles
  cfg.activeId = profiles.length ? profiles[0].id : null
  return cfg
}

function activeProfile(cfg) {
  return cfg.profiles.find((p) => p.id === cfg.activeId) || cfg.profiles[0] || null
}

/** 供对话调用：把启用中的档案展开成旧的扁平字段 */
function effectiveCfg() {
  const cfg = migrateCfg(rawCfg())
  const active = activeProfile(cfg)
  if (active && active.provider === 'openai') {
    cfg.openaiBaseUrl = active.baseUrl
    cfg.openaiApiKey = active.apiKey
    cfg.llmModel = active.model
  } else if (active && active.provider === 'ollama') {
    cfg.ollamaBaseUrl = active.baseUrl
    cfg.ollamaModel = active.model
  }
  return cfg
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
  // 默认位置：金字塔布局 —— 子节点落在父节点下方一层，兄弟依次向右排开
  const siblings = tree.nodeList.filter((n) => n.parentId === payload.parentId)
  const psize = parent.size || {}
  const cardW = psize.w || 340
  const cardH = psize.h || 380
  const y = payload.y != null ? payload.y : parent.y + cardH + 150
  let x
  if (payload.x != null) x = payload.x
  else if (siblings.length) x = Math.max(...siblings.map((n) => n.x)) + cardW + 90
  else x = parent.x
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
  let cfg = migrateCfg(rawCfg())
  const active = activeProfile(cfg)
  return {
    provider: cfg.provider,
    profiles: cfg.profiles.map(publicProfile),
    activeId: cfg.activeId,
    activeName: active ? active.name : '',
    hasKey: !!(active && active.apiKey),
    keyMasked: maskKey(active ? active.apiKey : ''),
    openaiBaseUrl: cfg.openaiBaseUrl,
    llmModel: cfg.llmModel,
    ollamaBaseUrl: cfg.ollamaBaseUrl,
    ollamaModel: cfg.ollamaModel
  }
}

export function updateLlmConfig(patch) {
  const cfg = migrateCfg(rawCfg())
  for (const k of Object.keys(DEFAULT_CFG)) {
    if (patch[k] != null) cfg[k] = String(patch[k]).trim()
  }
  if (!['mock', 'openai', 'ollama'].includes(cfg.provider)) cfg.provider = 'mock'
  saveRaw(cfg)
  return getLlmConfig()
}

export function saveLlmProfile(payload) {
  const cfg = migrateCfg(rawCfg())
  const p = normalizeProfile(payload)
  const idx = cfg.profiles.findIndex((x) => x.id === p.id)
  if (idx >= 0) {
    if (!p.apiKey) p.apiKey = cfg.profiles[idx].apiKey // Key 留空表示沿用原值
    cfg.profiles[idx] = p
  } else {
    cfg.profiles.push(p)
  }
  cfg.activeId = p.id
  cfg.provider = p.provider
  saveRaw(cfg)
  return getLlmConfig()
}

export function deleteLlmProfile(id) {
  const cfg = migrateCfg(rawCfg())
  cfg.profiles = cfg.profiles.filter((p) => p.id !== id)
  if (cfg.activeId === id) {
    cfg.activeId = cfg.profiles.length ? cfg.profiles[0].id : null
    cfg.provider = cfg.profiles.length ? cfg.profiles[0].provider : 'mock'
  }
  saveRaw(cfg)
  return getLlmConfig()
}

export function activateLlmProfile(id) {
  const cfg = migrateCfg(rawCfg())
  const p = cfg.profiles.find((x) => x.id === id)
  if (p) {
    cfg.activeId = id
    cfg.provider = p.provider
    saveRaw(cfg)
  }
  return getLlmConfig()
}

/** 真实连通性测试：验证地址可达、Key 有效、模型可用（浏览器直连） */
export async function testLlm(payload = {}) {
  const cfg = migrateCfg(rawCfg())
  let p = payload.id ? cfg.profiles.find((x) => x.id === payload.id) : null
  if (!p) {
    p = normalizeProfile({
      provider: payload.provider || cfg.provider || 'openai',
      baseUrl: payload.baseUrl,
      apiKey: payload.apiKey,
      model: payload.model
    })
  }
  if (payload.apiKey) p = { ...p, apiKey: payload.apiKey }
  if (p.provider === 'mock' || (!payload.id && !payload.provider && cfg.provider === 'mock')) {
    return { ok: true, simulated: true, msg: '演示模式不会发起真实请求，无需测试连接' }
  }
  let result
  try {
    result = p.provider === 'ollama' ? await testOllama(p) : await testOpenAI(p)
  } catch (e) {
    result = { ok: false, error: corsHint(e) }
  }
  if (payload.id) {
    const target = cfg.profiles.find((x) => x.id === payload.id)
    if (target) {
      target.lastTest = {
        ok: !!result.ok,
        msg: result.msg || result.error || '',
        ts: now(),
        models: (result.models || []).slice(0, 12)
      }
      saveRaw(cfg)
    }
  }
  return result
}

async function testOpenAI(p) {
  if (!p.apiKey) return { ok: false, error: '未填写 API Key，无法测试' }
  const base = (p.baseUrl || '').replace(/\/+$/, '')
  const headers = { Authorization: `Bearer ${p.apiKey}` }
  const t0 = performance.now()
  let r = null
  try { r = await fetch(`${base}/models`, { headers }) } catch (e) { r = null }
  if (r) {
    if (r.status === 401 || r.status === 403) {
      return { ok: false, error: `鉴权失败（${r.status}）：API Key 无效、已过期或无权限` }
    }
    if (r.ok) {
      let ids = []
      try { ids = ((await r.json()).data || []).map((m) => m.id).filter(Boolean) } catch (e) { ids = [] }
      const ms = Math.round(performance.now() - t0)
      if (ids.length) {
        if (!ids.includes(p.model)) {
          return { ok: true, warning: true, latency: ms, models: ids.slice(0, 30),
            msg: `Key 有效（延迟 ${ms}ms，可访问 ${ids.length} 个模型），但列表里没有「${p.model}」，请核对模型名` }
        }
        return { ok: true, latency: ms, models: ids.slice(0, 30),
          msg: `Key 有效 · 延迟 ${ms}ms · 可访问 ${ids.length} 个模型 · 「${p.model}」可用` }
      }
      return { ok: true, latency: ms, msg: `Key 有效 · 延迟 ${ms}ms` }
    }
  }
  const resp = await fetch(`${base}/chat/completions`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: p.model, messages: [{ role: 'user', content: 'ping' }], max_tokens: 1, stream: false })
  })
  const ms = Math.round(performance.now() - t0)
  if (resp.status === 401 || resp.status === 403) {
    return { ok: false, error: `鉴权失败（${resp.status}）：API Key 无效或无权访问该模型` }
  }
  if (!resp.ok) return { ok: false, error: `请求失败（${resp.status}）${(await resp.text()).slice(0, 200)}` }
  let used = p.model
  try { used = (await resp.json()).model || p.model } catch (e) { /* ignore */ }
  return { ok: true, latency: ms, msg: `连接成功 · 延迟 ${ms}ms · 模型 ${used} 已响应` }
}

async function testOllama(p) {
  const base = (p.baseUrl || '').replace(/\/+$/, '')
  const t0 = performance.now()
  const resp = await fetch(`${base}/api/tags`)
  if (!resp.ok) {
    return { ok: false, error: `Ollama 返回 ${resp.status}：${(await resp.text()).slice(0, 150)}` }
  }
  let names = []
  try { names = ((await resp.json()).models || []).map((m) => m.name).filter(Boolean) } catch (e) { names = [] }
  const ms = Math.round(performance.now() - t0)
  if (names.length && !names.some((n) => n === p.model || n.split(':')[0] === p.model.split(':')[0])) {
    return { ok: true, warning: true, latency: ms, models: names.slice(0, 30),
      msg: `Ollama 已连接（延迟 ${ms}ms，本地 ${names.length} 个模型），但没有「${p.model}」，请先执行 ollama pull ${p.model}` }
  }
  return { ok: true, latency: ms, models: names.slice(0, 30),
    msg: `Ollama 已连接 · 延迟 ${ms}ms · 模型「${p.model}」${names.length ? '可用' : '（本地模型列表为空）'}` }
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
  const cfg = effectiveCfg()
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
