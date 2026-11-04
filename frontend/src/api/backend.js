// 后端模式：所有数据走 FastAPI（backend/）
const BASE = ''

async function request(url, options = {}) {
  const resp = await fetch(BASE + url, {
    headers: { 'Content-Type': 'application/json' },
    ...options
  })
  if (!resp.ok) {
    let msg = `请求失败(${resp.status})`
    try { msg = (await resp.json()).detail || msg } catch (e) { /* ignore */ }
    throw new Error(msg)
  }
  return resp.json()
}

export const listTrees = () => request('/api/tree/list')
export const createTree = (title) =>
  request('/api/tree/create', { method: 'POST', body: JSON.stringify({ title }) })
export const getTree = (treeId) => request(`/api/tree/get?treeId=${encodeURIComponent(treeId)}`)
export const createChildNode = (payload) =>
  request('/api/node/create-child', { method: 'POST', body: JSON.stringify(payload) })
export const updateNodeApi = (payload) =>
  request('/api/node/update', { method: 'PUT', body: JSON.stringify(payload) })
export const deleteNodeApi = (treeId, nodeId) =>
  request(`/api/node/delete?treeId=${encodeURIComponent(treeId)}&nodeId=${encodeURIComponent(nodeId)}`, { method: 'DELETE' })
export const deleteTreeApi = (treeId) =>
  request(`/api/tree/delete?treeId=${encodeURIComponent(treeId)}`, { method: 'DELETE' })
/** 清空画布：保留节点结构，只清除所有节点的对话记录 */
export const clearTreeMessages = (treeId) =>
  request('/api/tree/clear-messages', { method: 'POST', body: JSON.stringify({ treeId }) })
export const renameTreeApi = (treeId, title) =>
  request('/api/tree/update', { method: 'PUT', body: JSON.stringify({ treeId, title }) })
/** 复制节点；withSubtree=true 时连同整条分支一起复制，返回新的完整节点列表 */
export const duplicateNode = (payload) =>
  request('/api/node/duplicate', { method: 'POST', body: JSON.stringify(payload) })
/** 整树快照写入（撤销 / 重做） */
export const saveTreeSnapshot = (payload) =>
  request('/api/tree/snapshot', { method: 'POST', body: JSON.stringify(payload) })

const EXT = { markdown: 'md', mermaid: 'mmd', json: 'json', html: 'html' }

/** 导出：取回文本，由前端统一下载 */
export async function exportTree(treeId, format) {
  const resp = await fetch(`${BASE}/api/tree/export?treeId=${encodeURIComponent(treeId)}&format=${format}`)
  if (!resp.ok) throw new Error(`导出失败(${resp.status})`)
  return { text: await resp.text(), filename: `对话树-${treeId}.${EXT[format] || 'txt'}` }
}

/** 导入 JSON 备份为新画布，返回新树 */
export const importTree = (payload) =>
  request('/api/tree/import', { method: 'POST', body: JSON.stringify(payload) })

export const getLlmConfig = () => request('/api/llm/config')
export const updateLlmConfig = (patch) =>
  request('/api/llm/config', { method: 'POST', body: JSON.stringify(patch) })
export const saveLlmProfile = (payload) =>
  request('/api/llm/profile', { method: 'POST', body: JSON.stringify(payload) })
export const deleteLlmProfile = (id) =>
  request(`/api/llm/profile/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const activateLlmProfile = (id) =>
  request(`/api/llm/profile/${encodeURIComponent(id)}/activate`, { method: 'POST', body: '{}' })
export const testLlm = (payload) =>
  request('/api/llm/test', { method: 'POST', body: JSON.stringify(payload || {}) })

/**
 * SSE 流式提问：onChunk 逐段回调 AI 回答片段，返回完整回答。
 */
export async function sendQuestionStream(treeId, nodeId, content, onChunk) {
  const resp = await fetch(`${BASE}/api/node/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ treeId, nodeId, content })
  })
  if (!resp.ok || !resp.body) {
    let msg = `请求失败(${resp.status})`
    try { msg = (await resp.json()).detail || msg } catch (e) { /* ignore */ }
    throw new Error(msg)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''
  let finalAnswer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop()
    for (const part of parts) {
      const line = part.trim()
      if (!line.startsWith('data:')) continue
      let evt
      try { evt = JSON.parse(line.slice(5).trim()) } catch (e) { continue }
      if (evt.type === 'chunk') { finalAnswer += evt.content; onChunk && onChunk(evt.content) }
      else if (evt.type === 'error') throw new Error(evt.message)
      else if (evt.type === 'done') return evt.answer || finalAnswer
    }
  }
  return finalAnswer
}
