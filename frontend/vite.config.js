import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { viteSingleFile } from 'vite-plugin-singlefile'

// mode=standalone → 产出单个 HTML 文件（无需后端，双击即可用 / 任意静态托管）
// 默认（development / production）→ 走 FastAPI 后端
export default defineConfig(({ mode }) => {
  const web = mode === 'standalone'
  return {
    plugins: web ? [vue(), viteSingleFile()] : [vue()],
    base: web ? './' : '/',
    server: {
      port: 5173,
      proxy: { '/api': 'http://localhost:8000' }
    },
    build: web
      ? {
          outDir: 'dist-web',
          emptyOutDir: true,
          assetsInlineLimit: 100000000,
          chunkSizeWarningLimit: 5000
        }
      : { outDir: 'dist', chunkSizeWarningLimit: 1500 }
  }
})
