/**
 * 端到端验证：桌面版设置（localStorage）能否跨重启保留。
 *
 * 背景：pywebview 默认 private_mode=True，WebView2 跑 InPrivate，
 * 关窗时 clear_user_data() 会 rmtree 用户数据目录，主题/背景/笔记全丢。
 * 本测试走真实操作流：启动源码版 → 点设置切深色 → 关应用 → 重启 → 读设置。
 *
 * 依赖：BCC_REMOTE_DEBUG_PORT 环境变量让后端开 CDP 端口（仅调试用）。
 */
const puppeteer = require('puppeteer-core')
const { spawn } = require('child_process')
const fs = require('fs')
const os = require('os')
const path = require('path')

const PY = 'C:/develop/Python/python.exe'
const ROOT = path.resolve(__dirname, '..')
const USE_EXE = process.argv[2] === 'exe'
const EXE = path.join(ROOT, 'dist-exe', 'BranchChatCanvas.exe')
const DATA = path.join(os.tmpdir(), USE_EXE ? 'bcc_persist_e2e_exe' : 'bcc_persist_e2e')
const PORT = 9339

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const log = (s) => console.log(s)
let failed = 0
const check = (ok, msg) => {
  if (ok) log(`✓ ${msg}`)
  else { failed++; log(`✗ ${msg}`) }
}

async function waitCDP(timeout = 120000) {
  const t0 = Date.now()
  while (Date.now() - t0 < timeout) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/version`)
      if (r.ok) return true
    } catch { /* 还没起来 */ }
    await sleep(800)
  }
  return false
}

function startApp() {
  const env = { ...process.env, BCC_DATA_DIR: DATA, BCC_REMOTE_DEBUG_PORT: String(PORT) }
  const cmd = USE_EXE ? EXE : PY
  const args = USE_EXE ? [] : [path.join(ROOT, 'backend', 'app_desktop.py')]
  return spawn(cmd, args, { cwd: ROOT, env, stdio: 'ignore' })
}

async function waitExit(proc, timeout = 30000) {
  const t0 = Date.now()
  while (Date.now() - t0 < timeout) {
    if (proc.exitCode !== null) return true
    await sleep(400)
  }
  return false
}

/** 连上 WebView2，返回主窗口 page（排除 ?mini=1 的悬浮球） */
async function connectMain() {
  const browser = await puppeteer.connect({
    browserURL: `http://127.0.0.1:${PORT}`, defaultViewport: null,
  })
  const pages = await browser.pages()
  let main = null
  const t0 = Date.now()
  while (!main && Date.now() - t0 < 40000) {
    for (const p of await browser.pages()) {
      const u = p.url()
      if (u.startsWith('http://127.0.0.1') && !u.includes('mini=1')) { main = p; break }
    }
    if (!main) await sleep(700)
  }
  return { browser, page: main }
}

async function readState(page) {
  return page.evaluate(() => ({
    theme: localStorage.getItem('bcc:theme'),
    attr: document.documentElement.getAttribute('data-theme'),
    cls: document.documentElement.classList.contains('dark'),
  }))
}

async function main() {
  // 干净起点
  fs.rmSync(DATA, { recursive: true, force: true })
  fs.mkdirSync(DATA, { recursive: true })

  // ---------- 第一次启动：切深色 ----------
  log('—— 第一次启动 ——')
  let proc = startApp()
  if (!(await waitCDP())) { log('✗ CDP 端口未就绪（后端可能启动失败）'); proc.kill(); process.exit(1) }
  const { page } = await connectMain()
  if (!page) { log('✗ 未找到主窗口'); proc.kill(); process.exit(1) }

  await page.waitForSelector('.toolbar', { timeout: 40000 })
  await sleep(1500)
  const before = await readState(page)
  log(`启动初始主题: ${JSON.stringify(before)}`)

  // 真实鼠标：悬浮设置按钮 → 点「深色主题」
  const hub = await page.$('.settings-hub')
  const hb = await hub.boundingBox()
  await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2)
  await page.waitForSelector('.shub-pop', { timeout: 8000 })
  await sleep(300)
  const clicked = await page.evaluate(() => {
    // 事件绑在 .si-label 文字上，不是 .shub-item 整行
    const el = [...document.querySelectorAll('.shub-pop .si-label')]
      .find((x) => x.innerText.includes('深色主题'))
    if (el) { el.click(); return true }
    return false
  })
  check(clicked, '顶部设置面板找到并点击「深色主题」')
  await sleep(1200)
  const after = await readState(page)
  check(after.theme === 'dark', `切换后 localStorage 写入 bcc:theme=dark（实际 ${after.theme}）`)
  check(after.attr === 'dark' || after.cls, `切换后页面已应用深色（data-theme=${after.attr}）`)

  // profile 是否落在数据目录
  const profileDir = path.join(DATA, 'webview')
  check(fs.existsSync(profileDir), `WebView2 profile 落在数据目录：${profileDir}`)
  const ebw = path.join(profileDir, 'EBWebView')
  check(fs.existsSync(ebw), 'EBWebView 子目录已生成（真实使用了固定 profile）')

  // 等 LevelDB 落盘，再走应用自己的退出路径
  await sleep(1800)
  try { await page.evaluate(() => window.pywebview.api.quit_app()) } catch { /* 进程自杀导致连接断开，正常 */ }
  const exited = await waitExit(proc)
  check(exited, '第一次实例已退出')
  if (!exited) proc.kill()
  await sleep(1500)

  // ---------- 第二次启动：设置应还在 ----------
  log('—— 第二次启动 ——')
  proc = startApp()
  if (!(await waitCDP())) { log('✗ 第二次启动 CDP 未就绪'); proc.kill(); process.exit(1) }
  const { page: page2 } = await connectMain()
  if (!page2) { log('✗ 第二次启动未找到主窗口'); proc.kill(); process.exit(1) }

  await page2.waitForSelector('.toolbar', { timeout: 40000 })
  await sleep(1500)
  const restored = await readState(page2)
  check(restored.theme === 'dark', `重启后 localStorage 仍是 dark（实际 ${restored.theme}）`)
  check(restored.attr === 'dark' || restored.cls,
    `重启后界面自动加载为深色（data-theme=${restored.attr}）`)

  // 再验证笔记/外观键也在同一 profile 里
  const keys = await page2.evaluate(() => Object.keys(localStorage))
  log(`重启后 localStorage 键: ${JSON.stringify(keys)}`)

  try { await page2.evaluate(() => window.pywebview.api.quit_app()) } catch { /* ignore */ }
  await waitExit(proc)
  proc.kill()

  log(failed === 0 ? '\n全部通过：设置可跨重启保留' : `\n${failed} 项失败`)
  process.exit(failed === 0 ? 0 : 1)
}

main().catch((e) => { console.error('测试异常:', e.message); process.exit(1) })
