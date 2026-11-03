import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'   // 深色模式变量（html.dark 生效）
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'
import './styles.css'
import App from './App.vue'

// 初始化主题（浅色 / 深色），Element Plus 通过 html.dark 启用深色变量
function applyTheme() {
  const t = localStorage.getItem('bcc:theme') || 'light'
  const el = document.documentElement
  el.setAttribute('data-theme', t)
  el.classList.toggle('dark', t === 'dark')
}
applyTheme()

const app = createApp(App)
app.use(createPinia())
app.use(ElementPlus)
app.mount('#app')
