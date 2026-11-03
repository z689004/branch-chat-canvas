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

    /** 一键整理布局：深度优先，父节点居中于子节点之间 */
    tidyLayout() {
      const V_GAP = 470, H_GAP = 480
      let cursor = 0
      const place = (nodeId, depth) => {
        const node = this.nodeMap[nodeId]
        if (!node) return
        node.x = depth * H_GAP
        const kids = (this.childrenMap[nodeId] || [])
        if (!kids.length) {
          node.y = cursor
          cursor += V_GAP
          return
        }
        kids.forEach(k => place(k.nodeId, depth + 1))
        node.y = (this.nodeMap[kids[0].nodeId].y + this.nodeMap[kids[kids.length - 1].nodeId].y) / 2
      }
      this.roots.forEach(r => place(r.nodeId, 0))
      // 持久化所有坐标
      for (const n of this.nodes) {
        updateNodeApi({ treeId: this.treeId, nodeId: n.nodeId, x: n.x, y: n.y }).catch(() => {})
      }
    }
  }
})
