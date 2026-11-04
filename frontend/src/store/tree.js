import { defineStore } from 'pinia'
import {
  listTrees, createTree, getTree, createChildNode,
  updateNodeApi, deleteNodeApi, deleteTreeApi, clearTreeMessages, renameTreeApi,
  sendQuestionStream, duplicateNode, saveTreeSnapshot
} from '../api'

const LAST_TREE_KEY = 'bcc:lastTreeId'
const HISTORY_LIMIT = 40

const clone = (v) => JSON.parse(JSON.stringify(v))

export const useTreeStore = defineStore('tree', {
  state: () => ({
    treeId: null,
    treeTitle: '',
    nodes: [],
    treeList: [],
    streamingNodeIds: [],
    loaded: false,
    // 保存状态：saved 已保存 / unsaved 未保存（有改动待落库）
    saveStatus: 'saved',
    lastSavedAt: '',
    pending: 0,
    // 撤销 / 重做历史（整树快照）
    past: [],
    future: []
  }),

  getters: {
    nodeMap: (s) => Object.fromEntries(s.nodes.map(n => [n.nodeId, n])),
    childrenMap: (s) => {
      const m = {}
      for (const n of s.nodes) {
        if (!n.parentId) continue
        ;(m[n.parentId] ||= []).push(n)
      }
      return m
    },
    roots() { return this.nodes.filter(n => !n.parentId) },
    /** 可见节点：折叠节点隐藏其整棵子树 */
    visibleNodes() {
      const vis = new Set()
      const walk = (id) => {
        vis.add(id)
        const node = this.nodeMap[id]
        if (node && !node.isCollapsed) {
          ;(this.childrenMap[id] || []).forEach(k => walk(k.nodeId))
        }
      }
      this.roots.forEach(r => walk(r.nodeId))
      return this.nodes.filter(n => vis.has(n.nodeId))
    },
    canUndo: (s) => s.past.length > 0,
    canRedo: (s) => s.future.length > 0,
    /** 收集某节点的整棵子树 id（含自身） */
    subtreeIds: (s) => (nodeId) => {
      const ids = new Set([nodeId])
      let changed = true
      while (changed) {
        changed = false
        for (const n of s.nodes) {
          if (ids.has(n.parentId) && !ids.has(n.nodeId)) { ids.add(n.nodeId); changed = true }
        }
      }
      return [...ids]
    }
  },

  actions: {
    // ---------- 保存状态 / 撤销重做基础 ----------
    touch() {
      this.pending += 1
      this.saveStatus = 'unsaved'
    },
    settled() {
      this.pending = Math.max(0, this.pending - 1)
      if (this.pending === 0) {
        this.saveStatus = 'saved'
        const d = new Date()
        const p = (n) => String(n).padStart(2, '0')
        this.lastSavedAt = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
      }
    },
    snapshot() {
      return { title: this.treeTitle, nodeList: clone(this.nodes) }
    },
    /** 在任何改动之前调用：把当前状态压入撤销栈 */
    commit() {
      if (!this.treeId) return
      this.past.push(this.snapshot())
      if (this.past.length > HISTORY_LIMIT) this.past.shift()
      this.future = []
    },
    async applySnapshot(snap, { persist = true } = {}) {
      this.nodes = clone(snap.nodeList || [])
      if (snap.title != null) this.treeTitle = snap.title
      if (!persist) return
      this.touch()
      try {
        await saveTreeSnapshot({ treeId: this.treeId, title: this.treeTitle, nodeList: this.nodes })
        await this.refreshTreeList()
      } catch (e) {
        console.warn('快照落库失败', e)
      } finally {
        this.settled()
      }
    },
    async undo() {
      if (!this.past.length) return false
      this.future.push(this.snapshot())
      const snap = this.past.pop()
      await this.applySnapshot(snap)
      return true
    },
    async redo() {
      if (!this.future.length) return false
      this.past.push(this.snapshot())
      const snap = this.future.pop()
      await this.applySnapshot(snap)
      return true
    },

    // ---------- 画布级 ----------
    async refreshTreeList() {
      try {
        const list = await listTrees()
        // 过滤掉没有 treeId 的脏数据（历史上配置文件曾被误列进画布列表）
        this.treeList = (list || []).filter(t => t && typeof t.treeId === 'string' && t.treeId)
      } catch (e) { this.treeList = [] }
    },

    async init() {
      await this.refreshTreeList()
      const last = localStorage.getItem(LAST_TREE_KEY)
      if (last && this.treeList.some(t => t.treeId === last)) {
        await this.loadTree(last)
      }
      this.loaded = true
    },

    async loadTree(treeId) {
      const tree = await getTree(treeId)
      this.treeId = tree.treeId
      this.treeTitle = tree.title
      this.nodes = tree.nodeList
      this.past = []
      this.future = []
      this.saveStatus = 'saved'
      this.lastSavedAt = ''
      localStorage.setItem(LAST_TREE_KEY, tree.treeId)
      await this.refreshTreeList()
    },

    async newTree(question = '') {
      const tree = await createTree(null)
      await this.loadTree(tree.treeId)
      if (question.trim()) {
        const root = this.roots[0]
        if (root) await this.send(root.nodeId, question.trim())
      }
      return tree.treeId
    },

    // ---------- 节点级 ----------
    async createChild(parentId, selectedContext, contextMode = 'simple', title = null) {
      this.commit()
      this.touch()
      try {
        const child = await createChildNode({
          treeId: this.treeId, parentId, selectedContext, contextMode, title
        })
        this.nodes.push(child)
        return child
      } finally {
        this.settled()
      }
    },

    async send(nodeId, content) {
      const node = this.nodeMap[nodeId]
      if (!node) return
      this.commit()
      node.messages.push({ role: 'user', content })
      const assistantMsg = { role: 'assistant', content: '' }
      node.messages.push(assistantMsg)
      this.streamingNodeIds.push(nodeId)
      this.touch()
      try {
        const answer = await sendQuestionStream(this.treeId, nodeId, content, (chunk) => {
          assistantMsg.content += chunk
        })
        assistantMsg.content = answer || assistantMsg.content
        // 同步后端自动生成的标题
        const fresh = await getTree(this.treeId)
        const freshNode = fresh.nodeList.find(n => n.nodeId === nodeId)
        if (freshNode) {
          node.title = freshNode.title
          node.messages = freshNode.messages
        }
        await this.refreshTreeList()
      } catch (e) {
        assistantMsg.content = `⚠️ ${e.message}`
      } finally {
        this.streamingNodeIds = this.streamingNodeIds.filter(id => id !== nodeId)
        this.settled()
      }
    },

    async patchNode(nodeId, patch) {
      const node = this.nodeMap[nodeId]
      if (!node) return
      // 仅结构性 / 视觉性变更进入撤销栈，避免流式输入刷屏
      const structural = ['title', 'isCollapsed', 'contextMode', 'starred', 'size'].some(k => k in patch)
      if (structural) this.commit()
      Object.assign(node, patch)
      this.touch()
      try {
        await updateNodeApi({ treeId: this.treeId, nodeId, ...patch })
      } catch (e) {
        console.warn('节点更新保存失败', e)
      } finally {
        this.settled()
      }
    },

    savePos: (() => {
      let timer = null
      const pending = {}
      return function (nodeId, pos) {
        const node = this.nodeMap[nodeId]
        if (node) { node.x = pos.x; node.y = pos.y }
        pending[nodeId] = pos
        this.touch()
        clearTimeout(timer)
        timer = setTimeout(() => {
          const jobs = Object.entries(pending).map(([id, p]) =>
            updateNodeApi({ treeId: this.treeId, nodeId: id, x: p.x, y: p.y }).catch(() => {})
          )
          Object.keys(pending).forEach(k => delete pending[k])
          Promise.all(jobs).then(() => { this.settled() })
        }, 400)
      }
    })(),

    async removeNode(nodeId) {
      // 收集子孙
      const doomed = new Set([nodeId])
      let changed = true
      while (changed) {
        changed = false
        for (const n of this.nodes) {
          if (doomed.has(n.parentId) && !doomed.has(n.nodeId)) {
            doomed.add(n.nodeId); changed = true
          }
        }
      }
      this.commit()
      this.touch()
      try { await deleteNodeApi(this.treeId, nodeId) } catch (e) { console.warn(e) }
      this.nodes = this.nodes.filter(n => !doomed.has(n.nodeId))
      this.settled()
      return doomed.size
    },

    /** 批量删除：自动跳过「祖先也在选中集合里」的节点 */
    async removeNodes(ids) {
      const set = new Set(ids)
      const topLevel = ids.filter(id => {
        const n = this.nodeMap[id]
        return n && !set.has(n.parentId)
      })
      if (!topLevel.length) return 0
      this.commit()
      this.touch()
      let removed = 0
      try {
        for (const id of topLevel) {
          try {
            const r = await deleteNodeApi(this.treeId, id)
            removed += (r && r.deleted) || 1
          } catch (e) { console.warn(e) }
        }
        const fresh = await getTree(this.treeId)
        this.nodes = fresh.nodeList
        await this.refreshTreeList()
      } finally {
        this.settled()
      }
      return removed
    },

    /** 复制节点：withSubtree=true 时连同整条分支一起复制 */
    async duplicate(nodeId, withSubtree = false) {
      this.commit()
      this.touch()
      try {
        const res = await duplicateNode({ treeId: this.treeId, nodeId, withSubtree })
        if (res && Array.isArray(res.nodeList)) this.nodes = res.nodeList
        else {
          const fresh = await getTree(this.treeId)
          this.nodes = fresh.nodeList
        }
        await this.refreshTreeList()
        return res && res.nodeId
      } finally {
        this.settled()
      }
    },

    async duplicateMany(ids, withSubtree = false) {
      const set = new Set(ids)
      const topLevel = ids.filter(id => {
        const n = this.nodeMap[id]
        return n && !set.has(n.parentId)
      })
      if (!topLevel.length) return 0
      this.commit()
      this.touch()
      try {
        for (const id of topLevel) {
          try { await duplicateNode({ treeId: this.treeId, nodeId: id, withSubtree }) } catch (e) { console.warn(e) }
        }
        const fresh = await getTree(this.treeId)
        this.nodes = fresh.nodeList
        await this.refreshTreeList()
      } finally {
        this.settled()
      }
      return topLevel.length
    },

    async toggleStar(nodeId) {
      const n = this.nodeMap[nodeId]
      if (!n) return
      await this.patchNode(nodeId, { starred: !n.starred })
      return !n.starred
    },

    /** 清空会话：删除全部分支与对话，只留一个空白根会话（可撤销） */
    async clearMessages() {
      if (!this.treeId) return 0
      this.commit()
      this.touch()
      try {
        const res = await clearTreeMessages(this.treeId)
        const fresh = await getTree(this.treeId)
        this.nodes = fresh.nodeList
        await this.refreshTreeList()
        return res?.cleared || 0
      } finally {
        this.settled()
      }
    },

    /** 删除画布：整棵树从磁盘移除，回到欢迎页 */
    async deleteCanvas() {
      if (!this.treeId) return
      try { await deleteTreeApi(this.treeId) } catch (e) { console.warn(e) }
      localStorage.removeItem(LAST_TREE_KEY)
      this.treeId = null
      this.treeTitle = ''
      this.nodes = []
      this.past = []
      this.future = []
      await this.refreshTreeList()
    },

    async renameTree(title) {
      const t = (title || '').trim()
      if (!t || !this.treeId) return
      this.commit()
      this.treeTitle = t
      this.touch()
      try {
        await renameTreeApi(this.treeId, t)
        await this.refreshTreeList()
      } finally {
        this.settled()
      }
    },

    /** 金字塔布局：根节点顶部居中，逐层向下展开，父节点居中于其子节点上方
     *  pushHistory=false 用于「自动整理」这类伴随动作，避免多出一条撤销记录 */
    tidyLayout(pushHistory = true) {
      const H_GAP = 90          // 同层相邻子树的水平间距
      const V_GAP = 150         // 层与层之间的垂直间距
      const ROOT_GAP = 120      // 多根之间的间距
      const DEF_W = 340, DEF_H = 380, COLLAPSED_H = 76
      const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))
      const sizeOf = (n) => ({
        w: clamp(Number(n?.size?.w) || DEF_W, 260, 1200),
        h: n?.isCollapsed ? COLLAPSED_H : clamp(Number(n?.size?.h) || DEF_H, 240, 1600)
      })

      const vis = new Set(this.visibleNodes.map(n => n.nodeId))
      if (!vis.size) return
      const kidsOf = (id) => (this.childrenMap[id] || []).filter(k => vis.has(k.nodeId))

      // 1) 计算深度，并按每层最高卡片推导每层的 y
      const depth = {}
      const markDepth = (id, d) => {
        depth[id] = d
        kidsOf(id).forEach(k => markDepth(k.nodeId, d + 1))
      }
      const roots = this.roots.filter(r => vis.has(r.nodeId))
      roots.forEach(r => markDepth(r.nodeId, 0))

      const levelH = []
      for (const id of vis) {
        const d = depth[id]
        levelH[d] = Math.max(levelH[d] || 0, sizeOf(this.nodeMap[id]).h)
      }
      const levelY = []
      let y = 0
      for (let d = 0; d < levelH.length; d++) {
        levelY[d] = y
        y += (levelH[d] || DEF_H) + V_GAP
      }

      // 2) 自底向上递归：叶子占自身宽度，父节点居中于子节点跨度之上
      //    返回 { w: 子树占用宽度, ids: 子树全部节点 }
      const place = (id, left) => {
        const node = this.nodeMap[id]
        const s = sizeOf(node)
        const kids = kidsOf(id)
        node.y = levelY[depth[id]]

        if (!kids.length) {
          node.x = left
          return { w: s.w, ids: [id] }
        }

        let cursor = left
        let firstCenter = 0, lastCenter = 0
        const ids = [id]
        kids.forEach((k, i) => {
          const r = place(k.nodeId, cursor)
          ids.push(...r.ids)
          const kn = this.nodeMap[k.nodeId]
          const center = kn.x + sizeOf(kn).w / 2
          if (i === 0) firstCenter = center
          lastCenter = center
          cursor += r.w + H_GAP
        })

        const kidsSpan = cursor - H_GAP - left          // 子节点总跨度
        const subW = Math.max(s.w, kidsSpan)            // 子树占用宽度
        const shift = (subW - kidsSpan) / 2             // 父比孩子宽时，孩子整体居中
        if (shift > 0.5) {
          for (const kidId of ids) {
            if (kidId !== id) this.nodeMap[kidId].x += shift
          }
          firstCenter += shift
          lastCenter += shift
        }
        node.x = (firstCenter + lastCenter) / 2 - s.w / 2
        return { w: subW, ids }
      }

      let cursor = 0
      roots.forEach(r => {
        const res = place(r.nodeId, cursor)
        cursor += res.w + ROOT_GAP
      })

      // 3) 取整并整体归零（左上角从 0 开始），再持久化
      let minX = Infinity, minY = Infinity
      for (const id of vis) {
        const n = this.nodeMap[id]
        n.x = Math.round(n.x)
        n.y = Math.round(n.y)
        minX = Math.min(minX, n.x)
        minY = Math.min(minY, n.y)
      }
      for (const id of vis) {
        const n = this.nodeMap[id]
        n.x -= minX
        n.y -= minY
      }
      if (pushHistory) this.commit()
      this.touch()
      const jobs = [...vis].map(id => {
        const n = this.nodeMap[id]
        return updateNodeApi({ treeId: this.treeId, nodeId: n.nodeId, x: n.x, y: n.y }).catch(() => {})
      })
      Promise.all(jobs).then(() => this.settled())
    }
  }
})
