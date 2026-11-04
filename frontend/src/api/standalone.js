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
    starred: false,
    createTime: t,
    updateTime: t
  }
}

const isDefaultTitle = (t) => [ROOT_TITLE_DEFAULT, CHILD_TITLE_DEFAULT, '新对话', '新分支'].includes(t)

// ---------------- 树级接口 ----------------

export async function listTrees() {
  const all = loadAll()
  return Object.values(all)
    .filter((t) => t && typeof t.treeId === 'string' && t.treeId)
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

/** 悬浮速记画布绑定：纯前端模式直接用 localStorage */
export async function getMiniTreeApi() {
  const tid = localStorage.getItem('bcc:miniTreeId') || ''
  if (!tid || !loadAll()[tid]) return { treeId: '', title: '' }
  const t = loadAll()[tid]
  return { treeId: tid, title: t.title || '悬浮速记' }
}

export async function setMiniTreeApi(treeId) {
  localStorage.setItem('bcc:miniTreeId', treeId || '')
  return { ok: true, treeId: treeId || '' }
}

export async function deleteTreeApi(treeId) {
  const all = loadAll()
  delete all[treeId]
  saveAll(all)
  return { ok: true }
}

/** 清空会话：删除全部分支与对话，只保留一个空白根会话 */
export async function clearTreeMessages(treeId) {
  const tree = readTree(treeId)
  const nodes = tree.nodeList || []
  const cleared = nodes.reduce((s, n) => s + (n.messages?.length || 0), 0)
  const roots = nodes.filter((n) => !n.parentId)
  if (roots.length) {
    const root = roots[0]
    root.messages = []
    root.selectedContext = ''
    root.title = '新对话'
    root.isCollapsed = false
    root.starred = false
    root.x = 0
    root.y = 0
    root.size = {}
    tree.nodeList = [root]
  } else {
    tree.nodeList = []
  }
  writeTree(tree)
  return { ok: true, cleared, removed: nodes.length - tree.nodeList.length }
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
  if (payload.size != null) node.size = { w: payload.size.w, h: payload.size.h }
  if (payload.starred != null) node.starred = !!payload.starred
  node.updateTime = now()
  writeTree(tree)
  return node
}

/** 复制节点；withSubtree=true 时连同整条分支一起复制 */
export async function duplicateNode(payload) {
  const tree = readTree(payload.treeId)
  const node = tree.nodeList.find((n) => n.nodeId === payload.nodeId)
  if (!node) throw new Error('节点不存在')
  const kidsIdx = {}
  for (const n of tree.nodeList) {
    if (n.parentId) (kidsIdx[n.parentId] ||= []).push(n)
  }
  const sameLevel = tree.nodeList.filter((n) => n.parentId === node.parentId)
  const cardW = (node.size || {}).w || 340
  const baseX = Math.max(...sameLevel.map((n) => n.x ?? 0), node.x ?? 0)
  const dx = baseX + cardW + 90 - (node.x ?? 0)
  let rootId = null
  const clone = (n, parentId, isRoot) => {
    const c = {
      ...n,
      nodeId: uid(),
      parentId,
      title: isRoot ? `${n.title || '新分支'} 副本` : n.title,
      messages: (n.messages || []).map((m) => ({ ...m })),
      x: (n.x ?? 0) + dx,
      y: n.y ?? 0,
      isCollapsed: false,
      createTime: now(),
      updateTime: now()
    }
    tree.nodeList.push(c)
    if (isRoot) rootId = c.nodeId
    if (payload.withSubtree) for (const k of kidsIdx[n.nodeId] || []) clone(k, c.nodeId, false)
    return c
  }
  clone(node, node.parentId, true)
  writeTree(tree)
  return { ok: true, nodeId: rootId, nodeList: JSON.parse(JSON.stringify(tree.nodeList)) }
}

/** 整树快照写入（撤销 / 重做） */
export async function saveTreeSnapshot(payload) {
  const tree = readTree(payload.treeId)
  if (Array.isArray(payload.nodeList)) {
    const seen = new Set()
    const cleaned = []
    for (const raw of payload.nodeList) {
      const n = { ...raw }
      if (!n.nodeId || seen.has(n.nodeId)) continue
      seen.add(n.nodeId)
      n.parentId = n.parentId || null
      n.title = n.title || '新对话'
      n.selectedContext = n.selectedContext || ''
      n.contextMode = n.contextMode === 'full' ? 'full' : 'simple'
      n.messages = Array.isArray(n.messages) ? n.messages : []
      n.x = n.x ?? 0
      n.y = n.y ?? 0
      n.isCollapsed = !!n.isCollapsed
      cleaned.push(n)
    }
    for (const n of cleaned) if (n.parentId && !seen.has(n.parentId)) n.parentId = null
    tree.nodeList = cleaned
  }
  if (payload.title) tree.title = payload.title
  writeTree(tree)
  return JSON.parse(JSON.stringify(tree))
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

// ---------------- 导出 / 导入 ----------------

const escHtml = (s) => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')

function nodeMapOf(tree) {
  const m = {}
  for (const n of tree.nodeList) m[n.nodeId] = n
  return m
}

function breadcrumb(map, node) {
  const chain = []
  let cur = node
  let guard = 0
  while (cur && guard < 200) {
    chain.push(cur.title || '未命名')
    cur = cur.parentId ? map[cur.parentId] : null
    guard += 1
  }
  return chain.reverse().join(' → ')
}

function walkMarkdown(tree, parentId, depth, lines, map) {
  const kids = tree.nodeList.filter((n) => n.parentId === parentId)
  for (const n of kids) {
    lines.push(`${'#'.repeat(Math.min(depth, 6))} ${n.parentId ? '🌿 ' : '🌱 '}${n.title}`)
    lines.push(`\`路径：${breadcrumb(map, n)}\``)
    const meta = [`上下文：${n.contextMode === 'full' ? '完整模式' : '精简模式'}`]
    if (n.starred) meta.push('⭐ 收藏')
    if (n.selectedContext) meta.push(`选中片段：「${n.selectedContext.slice(0, 80)}」`)
    lines.push('')
    lines.push(`> *${meta.join(' ｜ ')}*`)
    lines.push('')
    for (const m of n.messages || []) {
      if (m.role === 'user') {
        lines.push('**🙋 用户**')
        lines.push('')
        lines.push(m.content)
        lines.push('')
      } else {
        lines.push('**🤖 AI**')
        lines.push('')
        lines.push(String(m.content).split('\n').map((ln) => (ln.trim() ? `> ${ln}` : '>')).join('\n'))
        lines.push('')
      }
    }
    lines.push('---')
    lines.push('')
    walkMarkdown(tree, n.nodeId, depth + 1, lines, map)
  }
}

function mdOutline(tree) {
  const lines = []
  const emit = (parent, depth) => {
    for (const n of tree.nodeList.filter((x) => x.parentId === parent)) {
      lines.push(`${'  '.repeat(depth)}- ${n.title}`)
      emit(n.nodeId, depth + 1)
    }
  }
  emit(null, 0)
  return lines
}

/** 按节点真实坐标生成结构图 SVG */
function canvasSvg(tree) {
  if (!tree.nodeList.length) return ''
  const box = {}
  for (const n of tree.nodeList) {
    const s = n.size || {}
    box[n.nodeId] = [Number(n.x) || 0, Number(n.y) || 0, Number(s.w) || 340, Number(s.h) || 380]
  }
  const vals = Object.values(box)
  const xs = vals.map((b) => b[0]).concat(vals.map((b) => b[0] + b[2]))
  const ys = vals.map((b) => b[1]).concat(vals.map((b) => b[1] + b[3]))
  const pad = 60
  const minx = Math.min(...xs) - pad
  const miny = Math.min(...ys) - pad
  const bw = Math.max(Math.max(...xs) + pad - minx, 10)
  const bh = Math.max(Math.max(...ys) + pad - miny, 10)

  const parts = [
    `<svg class="canvas-map" viewBox="${minx.toFixed(0)} ${miny.toFixed(0)} ${bw.toFixed(0)} ${bh.toFixed(0)}" preserveAspectRatio="xMidYMin meet" role="img" aria-label="画布结构图">`,
    '<defs><marker id="arw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#b6bfcc"/></marker></defs>'
  ]
  for (const n of tree.nodeList) {
    if (!n.parentId || !box[n.parentId]) continue
    const [px, py, pw, ph] = box[n.parentId]
    const [cx, cy, cw] = box[n.nodeId]
    const x1 = px + pw / 2
    const y1 = py + ph
    const x2 = cx + cw / 2
    const mid = (y1 + cy) / 2
    parts.push(`<path d="M ${x1.toFixed(0)} ${y1.toFixed(0)} C ${x1.toFixed(0)} ${mid.toFixed(0)}, ${x2.toFixed(0)} ${mid.toFixed(0)}, ${x2.toFixed(0)} ${cy.toFixed(0)}" stroke="#b6bfcc" stroke-width="2.5" fill="none" marker-end="url(#arw)" opacity="0.85"/>`)
  }
  for (const n of tree.nodeList) {
    const [x, y, w, h] = box[n.nodeId]
    const isRoot = !n.parentId
    const color = isRoot ? '#00b42a' : '#3370ff'
    const title = String(n.title || '未命名')
    const limit = Math.max(6, Math.floor((w - 34) / 15))
    const label = title.length <= limit ? title : title.slice(0, limit - 1) + '…'
    parts.push(`<g><rect x="${x.toFixed(0)}" y="${y.toFixed(0)}" width="${w.toFixed(0)}" height="${h.toFixed(0)}" rx="12" fill="#fff" stroke="#dde2ea" stroke-width="1.5"/>`)
    parts.push(`<rect x="${x.toFixed(0)}" y="${y.toFixed(0)}" width="${w.toFixed(0)}" height="${Math.min(h, 8).toFixed(0)}" rx="4" fill="${color}" opacity="0.9"/>`)
    parts.push(`<text x="${(x + 18).toFixed(0)}" y="${(y + 42).toFixed(0)}" font-size="16" font-weight="600" fill="#1f2329">${escHtml(label)}</text>`)
    parts.push(`<text x="${(x + 18).toFixed(0)}" y="${(y + 70).toFixed(0)}" font-size="12" fill="#8a94a6">${isRoot ? '起始节点' : '分支节点'}</text></g>`)
  }
  parts.push('</svg>')
  return parts.join('')
}

function buildHtml(tree, exportedAt) {
  const map = nodeMapOf(tree)
  const parts = []
  const emit = (parentId) => {
    for (const n of tree.nodeList.filter((x) => x.parentId === parentId)) {
      const isRoot = !n.parentId
      const bits = [`上下文：${n.contextMode === 'full' ? '完整模式' : '精简模式'}`]
      if (n.starred) bits.push('⭐ 收藏')
      if (n.selectedContext) bits.push(`选中片段：「${escHtml(n.selectedContext.slice(0, 80))}」`)
      parts.push(`<section class="node${isRoot ? ' root' : ''}">`)
      parts.push('<div class="node-head">')
      parts.push(`<span class="badge${isRoot ? ' root' : ''}">${isRoot ? '起始' : '分支'}</span>`)
      parts.push(`<span class="node-title">${escHtml(n.title)}</span>`)
      parts.push(`<span class="path">${escHtml(breadcrumb(map, n))}</span>`)
      parts.push('</div>')
      parts.push(`<p class="ctx">${escHtml(bits.join(' ｜ '))}</p>`)
      for (const m of n.messages || []) {
        const isUser = m.role === 'user'
        parts.push(`<div class="msg${isUser ? '' : ' ai'}">`)
        parts.push(`<div class="who">${isUser ? '🙋 用户' : '🤖 AI'}</div>`)
        parts.push(`<div class="bubble">${escHtml(m.content)}</div>`)
        parts.push('</div>')
      }
      parts.push('</section>')
      emit(n.nodeId)
    }
  }
  emit(null)
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escHtml(tree.title)}</title>
<style>
  :root { --ink:#1f2329; --dim:#6b7280; --line:#e5e7eb; --root:#00b42a; --branch:#3370ff; --bg:#f7f8fa; }
  * { box-sizing: border-box; }
  body { margin:0; padding:40px 20px 80px; background:var(--bg); color:var(--ink);
        font:15px/1.75 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }
  .wrap { max-width:900px; margin:0 auto; }
  header { margin-bottom:28px; }
  h1 { font-size:26px; margin:0 0 10px; }
  .meta, footer { color:var(--dim); font-size:13px; }
  .node { background:#fff; border:1px solid var(--line); border-left:4px solid var(--branch);
          border-radius:10px; padding:16px 18px; margin:0 0 14px; box-shadow:0 1px 2px rgba(16,24,40,.04); }
  .node.root { border-left-color:var(--root); }
  .node-head { display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; margin-bottom:10px; }
  .badge { font-size:11px; padding:1px 7px; border-radius:20px; background:#eef2ff; color:var(--branch); }
  .badge.root { background:#e8f7ee; color:var(--root); }
  .node-title { font-weight:600; font-size:16px; }
  .path { color:var(--dim); font-size:12px; width:100%; }
  .ctx { color:var(--dim); font-size:12px; margin:0 0 10px; }
  .msg { margin:0 0 12px; }
  .who { font-size:12px; font-weight:600; color:var(--dim); margin-bottom:4px; }
  .bubble { white-space:pre-wrap; word-break:break-word; padding:10px 13px; border-radius:8px; background:#f5f6f8; }
  .ai .bubble { background:#f7fbff; border:1px solid #e8f0ff; }
  footer { text-align:center; margin-top:36px; }
  .map-wrap { background:#fff; border:1px solid var(--line); border-radius:12px; padding:18px 18px 10px; margin:0 0 26px; }
  .map-title { font-size:13px; color:var(--dim); margin:0 0 10px; }
  svg.canvas-map { width:100%; height:auto; max-height:640px; display:block; }
  .sec-title { font-size:13px; color:var(--dim); letter-spacing:.5px; margin:28px 0 14px; }
  @media print { body { background:#fff; padding:0; } .node { break-inside:avoid; box-shadow:none; } }
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>${escHtml(tree.title)}</h1>
  <div class="meta">分支对话树 ｜ 共 ${tree.nodeList.length} 个节点 ｜ 导出时间 ${escHtml(exportedAt)}</div>
</header>
<section class="map-wrap">
  <p class="map-title">画布结构 · ${tree.nodeList.length} 个节点</p>
  ${canvasSvg(tree)}
</section>
<div class="sec-title">对话内容</div>
${parts.join('\n')}
<footer>由「分支对话画布」导出 · ${escHtml(exportedAt)}</footer>
</div>
</body>
</html>`
}

export async function exportTree(treeId, format) {
  const tree = readTree(treeId)
  const stamp = now()
  if (format === 'json') {
    return { text: JSON.stringify(tree, null, 2), filename: `${tree.title}.json` }
  }
  if (format === 'mermaid') {
    const lines = ['mindmap']
    const label = (t) => String(t || '未命名').replace(/\n/g, ' ')
      .replace(/[()[\]:]/g, (c) => ({ '(': '（', ')': '）', '[': '【', ']': '】', ':': '：' }[c])).slice(0, 40)
    const emit = (n, depth) => {
      lines.push(`${'  '.repeat(depth)}${label(n.title)}`)
      for (const k of tree.nodeList.filter((x) => x.parentId === n.nodeId)) emit(k, depth + 1)
    }
    for (const r of tree.nodeList.filter((x) => !x.parentId)) emit(r, 1)
    return { text: lines.join('\n'), filename: `${tree.title}.mmd` }
  }
  if (format === 'html') {
    return { text: buildHtml(tree, stamp), filename: `${tree.title}.html` }
  }
  const lines = [
    `# ${tree.title}`,
    '',
    `> 分支对话树 ｜ 共 ${tree.nodeList.length} 个节点 ｜ 导出时间 ${stamp}`,
    '',
    '## 结构概览',
    '',
    ...mdOutline(tree),
    '',
    '---',
    ''
  ]
  walkMarkdown(tree, null, 1, lines, nodeMapOf(tree))
  return { text: lines.join('\n'), filename: `${tree.title}.md` }
}

/** 导入 JSON 备份为新画布（节点 id 重新分配，不覆盖现有数据） */
export async function importTree(payload) {
  const src = payload && payload.tree && typeof payload.tree === 'object' ? payload.tree : payload
  if (!src || typeof src !== 'object') throw new Error('备份文件格式不正确：不是有效的 JSON 对象')
  const nodes = src.nodeList
  if (!Array.isArray(nodes) || !nodes.length) throw new Error('备份文件格式不正确：缺少 nodeList')

  const idmap = {}
  for (const n of nodes) {
    if (!n || !n.nodeId) throw new Error('备份文件格式不正确：节点缺少 nodeId')
    idmap[n.nodeId] = uid()
  }
  const t = now()
  const tree = newTreeObj(`${String(src.title || '导入的画布').slice(0, 50)}（导入）`)
  tree.createTime = t
  tree.nodeList = nodes.map((n) => {
    const out = {
      nodeId: idmap[n.nodeId],
      parentId: n.parentId ? (idmap[n.parentId] || null) : null,
      title: String(n.title || '未命名节点').slice(0, 60),
      selectedContext: String(n.selectedContext || '').slice(0, 4000),
      contextMode: n.contextMode === 'full' ? 'full' : 'simple',
      messages: (Array.isArray(n.messages) ? n.messages : [])
        .filter((m) => m && (m.role === 'user' || m.role === 'assistant'))
        .map((m) => ({ role: m.role, content: String(m.content || '') })),
      x: Number(n.x) || 0,
      y: Number(n.y) || 0,
      isCollapsed: !!n.isCollapsed,
      starred: !!n.starred,
      createTime: n.createTime || t,
      updateTime: t
    }
    if (n.size && typeof n.size === 'object') {
      out.size = { w: Number(n.size.w) || 340, h: Number(n.size.h) || 380 }
    }
    return out
  })
  writeTree(tree)
  return tree
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
