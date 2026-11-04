<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { useAppearanceStore } from '../store/appearance'

/**
 * 顶部工具栏「⚙️ 设置」按钮 + 悬浮面板 + 主题/画布背景对话框。
 *
 * 悬浮面板：鼠标悬浮按钮时弹出（Teleport 到 body，避免被 toolbar 的
 * overflow:hidden 裁掉）。响应式：窗口足够宽时是双列设置面板；
 * 画布窗口缩小、工具栏空间不足时自动收纳成单列下拉列表。
 */
const props = defineProps({
  theme: { type: String, default: 'light' },        // 'light' | 'dark'
  autoTidy: Boolean,
  showGrid: Boolean,
  showMinimap: Boolean
})
const emit = defineEmits([
  'set-theme', 'set-auto-tidy', 'toggle-grid', 'toggle-minimap', 'open-llm', 'open-ball',
  'clear-chat', 'delete-canvas'
])

const app = useAppearanceStore()
app.init()

// ---------- 悬浮面板：hover 展开 / 延迟收起 ----------
const btnRef = ref(null)
const pop = reactive({ visible: false, right: 0, top: 0 })
let hideTimer = null

function openPop() {
  clearTimeout(hideTimer)
  if (pop.visible) return
  const r = btnRef.value.getBoundingClientRect()
  pop.right = Math.max(8, window.innerWidth - r.right)
  pop.top = r.bottom + 6
  pop.visible = true
}
function scheduleHide() {
  clearTimeout(hideTimer)
  hideTimer = setTimeout(() => { pop.visible = false }, 280)
}
function cancelHide() { clearTimeout(hideTimer) }

// ---------- 响应式：宽面板 ↔ 单列下拉列表 ----------
// 空间不足时除了收起面板形态，还把工具栏低频按钮（清空/删除/密钥/托盘等）
// 隐藏掉（.tb-optional），保证 ⚙️ 设置按钮本身始终可见可点。
const compact = ref(false)
let toolbarEl = null
let ro = null
let compactOnAt = 0

function updateCompact() {
  if (!toolbarEl) return
  const w = window.innerWidth
  if (compact.value) {
    // 已收纳：宽度明显高于收纳阈值才恢复，避免临界宽度来回抖动
    if (w > compactOnAt + 60) compact.value = false
  } else {
    const overflowed = toolbarEl.scrollWidth > toolbarEl.clientWidth + 1
    if (overflowed || w < 1180) {
      compact.value = true
      compactOnAt = w
    }
  }
  toolbarEl.classList.toggle('compact-mode', compact.value)
}

onMounted(() => {
  toolbarEl = document.querySelector('.toolbar')
  if (window.ResizeObserver && toolbarEl) {
    ro = new ResizeObserver(updateCompact)
    ro.observe(toolbarEl)
  }
  window.addEventListener('resize', updateCompact)
  updateCompact()
})
onBeforeUnmount(() => {
  if (ro) ro.disconnect()
  window.removeEventListener('resize', updateCompact)
  clearTimeout(hideTimer)
})

// ---------- 主题 / 画布背景对话框 ----------
const themeDialog = ref(false)

function openThemeDialog() {
  themeDialog.value = true
  pop.visible = false
}

// ---------- 背景图上传（本地压缩后存 localStorage） ----------
const bgInput = ref(null)
const bgBusy = ref(false)

function pickBg() { bgInput.value && bgInput.value.click() }

/** 大图压到最长边 1920 的 JPEG，控制 localStorage 占用 */
function compressImage(file, maxEdge = 1920, quality = 0.85) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      try {
        const scale = Math.min(1, maxEdge / Math.max(img.width, img.height))
        const w = Math.max(1, Math.round(img.width * scale))
        const h = Math.max(1, Math.round(img.height * scale))
        const cv = document.createElement('canvas')
        cv.width = w
        cv.height = h
        cv.getContext('2d').drawImage(img, 0, 0, w, h)
        resolve(cv.toDataURL('image/jpeg', quality))
      } catch (e) {
        reject(e)
      } finally {
        URL.revokeObjectURL(url)
      }
    }
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('图片解析失败')) }
    img.src = url
  })
}

async function onBgFile(e) {
  const file = e.target.files && e.target.files[0]
  e.target.value = ''  // 允许重复选同一文件
  if (!file) return
  if (!/^image\//.test(file.type)) {
    ElMessage.error('请选择图片文件（PNG / JPG / WebP 等）')
    return
  }
  if (file.size > 20 * 1024 * 1024) {
    ElMessage.error('图片太大了（超过 20MB），请先压缩再上传')
    return
  }
  bgBusy.value = true
  try {
    const dataUrl = await compressImage(file)
    if (!dataUrl) throw new Error('图片解析失败')
    if (app.setBgImage(dataUrl)) {
      ElMessage.success('背景图已应用，可在下方调节透明度')
    } else {
      ElMessage.error('保存失败：压缩后仍超出本地存储上限，请换小一点的图片')
    }
  } catch (err) {
    ElMessage.error(err.message || '背景图处理失败')
  } finally {
    bgBusy.value = false
  }
}

function removeBg() {
  app.setBgImage('')
  ElMessage.info('已恢复默认画布背景')
}

// ---------- 配色 ----------
const COLOR_ITEMS = [
  { key: 'card', label: '卡片底色' },
  { key: 'edge', label: '连线颜色' },
  { key: 'text', label: '文字颜色' },
  { key: 'border', label: '边框色' }
]

function onColorChange(key, val) {
  if (val) app.setColor(key, val)
}

function resetColors() {
  app.resetColors()
  ElMessage.success('已恢复默认配色（跟随深浅色主题）')
}
</script>

<template>
  <div class="settings-hub" @mouseenter="openPop" @mouseleave="scheduleHide">
    <!-- 定位锚点用原生元素：组件 ref 拿到的是实例而非 DOM -->
    <span ref="btnRef" class="settings-hub-anchor">
      <el-button size="small" plain title="设置：视图 / 主题 / 画布背景">⚙️ 设置</el-button>
    </span>

    <!-- 悬浮面板：Teleport 到 body，避免被工具栏 overflow:hidden 裁剪 -->
    <Teleport to="body">
      <div
        v-if="pop.visible"
        class="shub-pop"
        :class="{ compact }"
        :style="{ right: pop.right + 'px', top: pop.top + 'px' }"
        @mouseenter="cancelHide"
        @mouseleave="scheduleHide"
      >
        <div class="shub-sec-title">视图</div>
        <div class="shub-grid">
          <div class="shub-item">
            <span class="si-label" @click="emit('set-auto-tidy', !autoTidy)">自动整理布局</span>
            <el-switch size="small" :model-value="autoTidy" @change="(v) => emit('set-auto-tidy', v)" />
          </div>
          <div class="shub-item">
            <span class="si-label" @click="emit('toggle-grid')">显示网格</span>
            <el-switch size="small" :model-value="showGrid" @change="emit('toggle-grid')" />
          </div>
          <div class="shub-item">
            <span class="si-label" @click="emit('toggle-minimap')">显示小地图</span>
            <el-switch size="small" :model-value="showMinimap" @change="emit('toggle-minimap')" />
          </div>
          <div class="shub-item">
            <span class="si-label" @click="emit('set-theme', theme === 'dark' ? 'light' : 'dark')">
              深色主题
            </span>
            <el-switch size="small" :model-value="theme === 'dark'"
              @change="emit('set-theme', theme === 'dark' ? 'light' : 'dark')" />
          </div>
        </div>

        <div class="shub-sec-title">外观</div>
        <div class="shub-grid">
          <div class="shub-item shub-entry" @click="openThemeDialog">
            <span class="si-ico">🎨</span>
            <span class="si-label">主题与画布背景…</span>
          </div>
        </div>

        <div class="shub-sec-title">更多</div>
        <div class="shub-grid">
          <div class="shub-item shub-entry" @click="emit('open-llm'); pop.visible = false">
            <span class="si-ico">🤖</span>
            <span class="si-label">模型与密钥…</span>
          </div>
          <div class="shub-item shub-entry" @click="emit('open-ball'); pop.visible = false">
            <span class="si-ico">🎈</span>
            <span class="si-label">悬浮球设置…</span>
          </div>
          <!-- 工具栏空间不足被收纳起来的低频按钮（仅收纳态显示） -->
          <template v-if="compact">
            <div class="shub-item shub-entry" @click="emit('clear-chat'); pop.visible = false">
              <span class="si-ico">🧹</span>
              <span class="si-label">清空对话</span>
            </div>
            <div class="shub-item shub-entry" @click="emit('delete-canvas'); pop.visible = false">
              <span class="si-ico">🗑️</span>
              <span class="si-label">删除画布</span>
            </div>
          </template>
        </div>

        <div class="shub-foot">所有配置自动保存在本机，重启后自动恢复</div>
      </div>
    </Teleport>

    <!-- 主题 / 画布背景 对话框 -->
    <el-dialog v-model="themeDialog" title="🎨 主题与画布背景" width="560px">
      <div class="sh-dialog-sec">
        <div class="sh-dialog-title">主题</div>
        <el-radio-group :model-value="theme" @change="(t) => emit('set-theme', t)">
          <el-radio-button value="light">☀️ 浅色</el-radio-button>
          <el-radio-button value="dark">🌙 深色</el-radio-button>
        </el-radio-group>
        <div class="sh-dialog-desc">深浅色主题与自定义背景、配色互相兼容，可随时切换。</div>
      </div>

      <div class="sh-dialog-sec">
        <div class="sh-dialog-title">画布背景</div>
        <div class="bg-row">
          <template v-if="app.hasBg">
            <div class="bg-thumb" :style="{ backgroundImage: `url(${app.bgImage})` }"></div>
            <div class="bg-ops">
              <el-button size="small" :loading="bgBusy" @click="pickBg">更换图片</el-button>
              <el-button size="small" type="danger" plain @click="removeBg">移除背景</el-button>
            </div>
          </template>
          <template v-else>
            <div class="bg-empty">未设置自定义背景，当前使用主题默认底色。</div>
            <el-button size="small" type="primary" plain :loading="bgBusy" @click="pickBg">
              🖼️ 上传本地图片
            </el-button>
          </template>
        </div>
        <input ref="bgInput" type="file" accept="image/*" style="display: none" @change="onBgFile" />
        <div class="bg-opacity-row">
          <span class="bg-opacity-label">背景透明度</span>
          <el-slider
            :model-value="app.bgOpacity"
            :min="5" :max="100" :step="5"
            :disabled="!app.hasBg"
            style="flex: 1; margin: 0 12px;"
            @update:model-value="(v) => app.setBgOpacity(v)"
          />
          <span class="bg-opacity-val">{{ app.bgOpacity }}%</span>
        </div>
        <div class="sh-dialog-desc">图片会自动压缩后保存在本机（不上传任何服务器）；调低透明度可让背景不抢内容。</div>
      </div>

      <div class="sh-dialog-sec">
        <div class="sh-dialog-title">自定义配色</div>
        <div class="sh-dialog-desc" style="margin-bottom: 6px;">
          <el-switch size="small" :model-value="app.colorsOn" @change="(v) => app.setColorsOn(v)" />
          <span style="margin-left: 8px;">启用自定义配色（关闭时跟随深浅色主题默认值）</span>
        </div>
        <div v-for="it in COLOR_ITEMS" :key="it.key" class="color-row">
          <span class="color-label">{{ it.label }}</span>
          <el-color-picker :model-value="app.colors[it.key]" @update:model-value="(v) => onColorChange(it.key, v)" />
          <span class="color-val">{{ app.colors[it.key] }}</span>
        </div>
        <div class="color-ops">
          <el-button size="small" @click="resetColors">恢复默认配色</el-button>
        </div>
        <div class="sh-dialog-desc">配色实时生效，只作用于节点卡片与连线，不影响其他界面。</div>
      </div>

      <template #footer>
        <el-button type="primary" @click="themeDialog = false">完成</el-button>
      </template>
    </el-dialog>
  </div>
</template>
