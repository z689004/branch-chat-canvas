import { defineStore } from 'pinia'

const NOTES_KEY = 'bcc:notes'
const LIMIT = 500          // 单条笔记上限之外，再限制总条数，避免 localStorage 无限膨胀
const MAX_LEN = 20000      // 单条内容上限（字符）

const nowIso = () => new Date().toISOString()

const clean = (s) => String(s || '').replace(/\r\n/g, '\n').trim().slice(0, MAX_LEN)

function load() {
  try {
    const raw = localStorage.getItem(NOTES_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    if (!Array.isArray(arr)) return []
    return arr
      .filter(n => n && typeof n.id === 'string' && typeof n.content === 'string' && n.content.trim())
      .map(n => ({
        id: n.id,
        content: n.content,
        kind: n.kind === 'excerpt' ? 'excerpt' : 'manual',
        source: n.source && typeof n.source === 'object' ? n.source : null,
        createdAt: n.createdAt || nowIso(),
        updatedAt: n.updatedAt || n.createdAt || nowIso()
      }))
  } catch (e) {
    return []
  }
}

function makeId() {
  return 'note_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7)
}

/**
 * 笔记 / 收藏夹：独立于对话树，存本地 localStorage（桌面版与单文件版一致）。
 * 一条笔记 = 正文 + 可选来源快照（画布名 / 节点名 / 谁说的）。
 */
export const useNotesStore = defineStore('notes', {
  state: () => ({
    items: load(),
    panelOpen: false,
    keyword: '',
    lastAddedId: ''      // 用于面板里高亮刚收藏的那条
  }),

  getters: {
    /** 按时间倒序（新建的在前） */
    sorted: (s) => [...s.items].sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt))),
    /** 关键词过滤：正文 + 来源画布名 + 节点名 */
    filtered() {
      const kw = this.keyword.trim().toLowerCase()
      if (!kw) return this.sorted
      return this.sorted.filter(n => {
        const src = n.source || {}
        return n.content.toLowerCase().includes(kw)
          || String(src.treeTitle || '').toLowerCase().includes(kw)
          || String(src.nodeTitle || '').toLowerCase().includes(kw)
      })
    },
    count: (s) => s.items.length,
    excerptCount: (s) => s.items.filter(n => n.kind === 'excerpt').length
  },

  actions: {
    persist() {
      try {
        localStorage.setItem(NOTES_KEY, JSON.stringify(this.items.slice(0, LIMIT)))
      } catch (e) {
        // 配额满等异常：不阻塞用户，放弃本次持久化（内存中仍可用）
      }
    },

    /** 新增一条。source 形如 { treeId, treeTitle, nodeId, nodeTitle, role } */
    add(content, source = null) {
      const text = clean(content)
      if (!text) return null
      const ts = nowIso()
      const item = {
        id: makeId(),
        content: text,
        kind: source ? 'excerpt' : 'manual',
        source: source
          ? {
              treeId: source.treeId || '',
              treeTitle: source.treeTitle || '未命名画布',
              nodeId: source.nodeId || '',
              nodeTitle: source.nodeTitle || '未命名节点',
              role: source.role === 'user' ? 'user' : 'assistant'
            }
          : null,
        createdAt: ts,
        updatedAt: ts
      }
      this.items.unshift(item)
      this.lastAddedId = item.id
      this.persist()
      return item
    },

    update(id, content) {
      const text = clean(content)
      if (!text) return false
      const item = this.items.find(n => n.id === id)
      if (!item) return false
      item.content = text
      item.updatedAt = nowIso()
      this.persist()
      return true
    },

    remove(id) {
      const i = this.items.findIndex(n => n.id === id)
      if (i < 0) return false
      this.items.splice(i, 1)
      this.persist()
      return true
    },

    clearAll() {
      this.items = []
      this.lastAddedId = ''
      this.persist()
    },

    open() { this.panelOpen = true },
    close() { this.panelOpen = false },
    toggle() { this.panelOpen = !this.panelOpen }
  }
})
