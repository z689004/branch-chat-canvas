import { defineStore } from 'pinia'
import {
  listTrees, createTree, getTree, createChildNode,
  updateNodeApi, deleteNodeApi, deleteTreeApi, renameTreeApi, sendQuestionStream
} from '../api'

const LAST_TREE_KEY = 'bcc:lastTreeId'

export const useTreeStore = defineStore('tree', {
  state: () => ({
    treeId: null,
    treeTitle: '',
    nodes: [],
    treeList: [],
    streamingNodeIds: [],
    loaded: false
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
    }
  },

  actions: {
    // ---------- 画布级 ----------
    async refreshTreeList() {
      try { this.treeList = await listTrees() } catch (e) { this.treeList = [] }
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
      const child = await createChildNode({
        treeId: this.treeId, parentId, selectedContext, contextMode, title
      })
      this.nodes.push(child)
      return child
    },

    async send(nodeId, content) {
      const node = this.nodeMap[nodeId]
      if (!node) return
      node.messages.push({ role: 'user', content })
      const assistantMsg = { role: 'assistant', content: '' }
      node.messages.push(assistantMsg)
      this.streamingNodeIds.push(nodeId)
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
      } catch (e) {
        assistantMsg.content = `⚠️ ${e.message}`
      } finally {
        this.streamingNodeIds = this.streamingNodeIds.filter(id => id !== nodeId)
      }
    },

    async patchNode(nodeId, patch) {
      const node = this.nodeMap[nodeId]
      if (node) Object.assign(node, patch)
      try {
        await updateNodeApi({ treeId: this.treeId, nodeId, ...patch })
      } catch (e) {
        console.warn('节点更新保存失败', e)
      }
    },

    savePos: (() => {
      let timer = null
      const pending = {}
      return function (nodeId, pos) {
        const node = this.nodeMap[nodeId]
        if (node) { node.x = pos.x; node.y = pos.y }
        pending[nodeId] = pos
        clearTimeout(timer)
        timer = setTimeout(() => {
          for (const [id, p] of Object.entries(pending)) {
            updateNodeApi({ treeId: this.treeId, nodeId: id, x: p.x, y: p.y })
              .catch(() => {})
          }
          Object.keys(pending).forEach(k => delete pending[k])
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
      try { await deleteNodeApi(this.treeId, nodeId) } catch (e) { console.warn(e) }
      this.nodes = this.nodes.filter(n => !doomed.has(n.nodeId))
      return doomed.size
    },

    /** 清空画布：删除整棵对话树 */
    async clearCanvas() {
      if (!this.treeId) return
      try { await deleteTreeApi(this.treeId) } catch (e) { console.warn(e) }
      localStorage.removeItem(LAST_TREE_KEY)
      this.treeId = null
      this.treeTitle = ''
      this.nodes = []
      await this.refreshTreeList()
    },

    async renameTree(title) {
      const t = (title || '').trim()
      if (!t || !this.treeId) return
      this.treeTitle = t
      await renameTreeApi(this.treeId, t)
      await this.refreshTreeList()
    },

    /** 金字塔布局：根节点顶部居中，逐层向下展开，父节点居中于其子节点上方 */
    tidyLayout() {
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
        updateNodeApi({ treeId: this.treeId, nodeId: n.nodeId, x: n.x, y: n.y }).catch(() => {})
      }
    }
  }
})
