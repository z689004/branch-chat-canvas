import { defineStore } from 'pinia'

/**
 * 外观配置：画布自定义背景 + 自定义配色（卡片底色 / 连线 / 文字 / 边框）。
 * 全部持久化在 localStorage（bcc:appearance），重启自动加载。
 * 深浅色主题仍由 bcc:theme + main.js 的 applyTheme 管理，两者互不干扰：
 * 背景图叠在主题底色之上（透明度可调），自定义配色关闭时全部回落到主题变量。
 */
const KEY = 'bcc:appearance'

const DEFAULT_COLORS = {
  card: '#ffffff',   // 卡片底色（浅色主题默认值）
  edge: '#165dff',   // 连线颜色
  text: '#1f2329',   // 卡片文字颜色
  border: '#e5e8eb'  // 卡片边框色
}

const DEFAULTS = {
  bgImage: '',        // dataURL；空 = 未启用自定义背景
  bgOpacity: 100,     // 背景不透明度 5-100
  colorsOn: false,    // 是否启用自定义配色
  colors: { ...DEFAULT_COLORS }
}

function clampOpacity(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return 100
  return Math.min(100, Math.max(5, Math.round(n)))
}

function load() {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return { bgImage: '', bgOpacity: 100, colorsOn: false, colors: { ...DEFAULT_COLORS } }
    const d = JSON.parse(raw) || {}
    return {
      bgImage: typeof d.bgImage === 'string' ? d.bgImage : '',
      bgOpacity: clampOpacity(d.bgOpacity),
      colorsOn: !!d.colorsOn,
      colors: { ...DEFAULT_COLORS, ...(d.colors || {}) }
    }
  } catch (e) {
    return { bgImage: '', bgOpacity: 100, colorsOn: false, colors: { ...DEFAULT_COLORS } }
  }
}

export const useAppearanceStore = defineStore('appearance', {
  state: () => ({ ...load() }),
  getters: {
    hasBg: (s) => !!s.bgImage,
    /** 连线颜色：自定义配色开启时返回自定义色，否则 null（用默认蓝/绿区分上下文模式） */
    edgeColor: (s) => (s.colorsOn ? s.colors.edge : null)
  },
  actions: {
    /** 落盘；返回 false 表示写失败（一般是背景图太大超出 localStorage 配额） */
    persist() {
      try {
        localStorage.setItem(KEY, JSON.stringify({
          bgImage: this.bgImage, bgOpacity: this.bgOpacity,
          colorsOn: this.colorsOn, colors: this.colors
        }))
        return true
      } catch (e) {
        return false
      }
    },
    /** 把自定义配色写到 :root 的节点级 CSS 变量；关闭时移除，回落主题变量 */
    applyColors() {
      const root = document.documentElement
      if (this.colorsOn) {
        root.style.setProperty('--node-bg', this.colors.card)
        root.style.setProperty('--node-border', this.colors.border)
        root.style.setProperty('--node-text', this.colors.text)
      } else {
        root.style.removeProperty('--node-bg')
        root.style.removeProperty('--node-border')
        root.style.removeProperty('--node-text')
      }
    },
    /** 设置背景图（dataURL）；保存失败会回滚并返回 false */
    setBgImage(dataUrl) {
      const old = this.bgImage
      this.bgImage = dataUrl || ''
      if (!this.persist()) {
        this.bgImage = old
        return false
      }
      return true
    },
    setBgOpacity(v) {
      this.bgOpacity = clampOpacity(v)
      this.persist()
    },
    setColorsOn(on) {
      this.colorsOn = !!on
      this.persist()
      this.applyColors()
    },
    setColor(key, val) {
      if (!(key in DEFAULT_COLORS) || !val) return
      this.colors[key] = val
      this.persist()
      this.applyColors()
    },
    resetColors() {
      this.colors = { ...DEFAULT_COLORS }
      this.colorsOn = false
      this.persist()
      this.applyColors()
    },
    init() {
      this.applyColors()
    }
  }
})
