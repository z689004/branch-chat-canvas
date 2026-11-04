/* 设置中心回归：工具栏设置按钮 / hover 悬浮面板 / 响应式折叠 / 主题与画布背景 / 持久化 */
const puppeteer = require('puppeteer-core')
const fs = require('fs')
const os = require('os')
const path = require('path')

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const APP = 'http://localhost:5173/'
const API = 'http://localhost:8000'
const SHOT = path.join(os.tmpdir(), 'bcc_settings_shot.png')

// 1x1 红色 PNG，用于背景图上传
const PNG_B64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='

const log = (...a) => console.log('•', ...a)
const fail = (msg) => { console.error('✗ ' + msg); process.exitCode = 1 }

async function api(path_, method = 'GET', body) {
  const res = await fetch(API + path_, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined
  })
  if (!res.ok) throw new Error(`${path_} -> ${res.status} ${await res.text()}`)
  return res.json()
}

;(async () => {
  // 准备一棵带对话的画布（根 + 一个子分支，保证有连线可验证颜色）
  const tree = await api('/api/tree/create', 'POST', { title: '设置中心测试画布' })
  const rootId = tree.nodeList[0].nodeId
  await (await fetch(`${API}/api/node/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ treeId: tree.treeId, nodeId: rootId, content: '什么是提示词工程？' })
  })).text()
  await api('/api/node/create-child', 'POST', {
    treeId: tree.treeId, parentId: rootId, selectedContext: '提示词', contextMode: 'simple', title: '子分支'
  })

  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage']
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 900 })
  page.on('pageerror', (e) => fail('页面异常: ' + e.message))

  await page.goto(APP, { waitUntil: 'networkidle2' })
  await page.evaluate((id) => {
    localStorage.setItem('bcc:lastTreeId', id)
    localStorage.removeItem('bcc:appearance')
    localStorage.setItem('bcc:theme', 'light')
  }, tree.treeId)
  await page.reload({ waitUntil: 'networkidle2' })
  await page.waitForSelector('.chat-node', { timeout: 15000 })
  log('画布已加载')

  // 1. 设置按钮存在
  const hubBtn = await page.$('.settings-hub')
  if (!hubBtn) fail('工具栏没有 ⚙️ 设置按钮')
  else log('✓ 工具栏设置按钮存在')

  // 2. 悬浮按钮 → 面板弹出（宽屏：双列面板，非 compact）
  await page.hover('.settings-hub')
  await page.waitForSelector('.shub-pop', { timeout: 3000 })
  const wideCompact = await page.$eval('.shub-pop', (el) => el.classList.contains('compact'))
  if (wideCompact) fail('宽屏下面板不该是 compact 折叠态')
  else log('✓ hover 弹出悬浮面板（宽屏双列）')

  const popText = await page.$eval('.shub-pop', (el) => el.innerText)
  for (const opt of ['自动整理布局', '显示网格', '显示小地图', '深色主题', '主题与画布背景', '模型与密钥', '悬浮球设置']) {
    if (!popText.includes(opt)) fail(`面板缺少选项：${opt}`)
  }
  log('✓ 面板选项齐全（视图 4 项 + 外观/更多入口）')

  // 3. 面板开关可用：关掉小地图（画布上小地图应消失）
  const hasMiniBefore = await page.$('.vue-flow__minimap')
  await page.evaluate(() => {
    const items = [...document.querySelectorAll('.shub-pop .shub-item')]
    const it = items.find((x) => x.innerText.includes('显示小地图'))
    it.querySelector('.el-switch').click()
  })
  await new Promise((r) => setTimeout(r, 600))
  const hasMiniAfter = await page.$('.vue-flow__minimap')
  if (hasMiniBefore && hasMiniAfter) fail('面板关闭小地图未生效')
  else log('✓ 面板开关生效（小地图已隐藏）')

  // 4. 响应式：窗口缩小 → 收纳为单列下拉列表
  await page.setViewport({ width: 900, height: 700 })
  await new Promise((r) => setTimeout(r, 400))
  await page.hover('.settings-hub')
  await page.waitForSelector('.shub-pop', { timeout: 3000 })
  const narrowCompact = await page.$eval('.shub-pop', (el) => el.classList.contains('compact'))
  if (!narrowCompact) fail('窄窗口下面板没有收纳成下拉列表（compact）')
  else log('✓ 窗口缩小后选项自动收纳成单列下拉列表')

  // 4b. 收纳态：低频按钮隐藏、入口进面板、设置按钮仍可见可点
  const hubVisible = await page.$eval('.settings-hub', (el) => {
    const r = el.getBoundingClientRect()
    return r.width > 0 && r.right <= window.innerWidth && r.left >= 0
  })
  if (!hubVisible) fail('窄窗口下 ⚙️ 设置按钮被裁剪')
  else log('✓ 窄窗口下设置按钮仍完整可见')
  const clearBtnHidden = await page.$eval('.tb-optional', (el) => getComputedStyle(el).display === 'none')
  if (!clearBtnHidden) fail('收纳态下低频按钮（清空对话等）未被隐藏')
  else log('✓ 收纳态下低频按钮已隐藏（入口收进面板）')
  const popText2 = await page.$eval('.shub-pop', (el) => el.innerText)
  if (!popText2.includes('清空对话') || !popText2.includes('删除画布')) fail('收纳态面板缺少清空/删除入口')
  else log('✓ 被收纳按钮的入口已出现在面板「更多」中')
  await page.setViewport({ width: 1440, height: 900 })
  await new Promise((r) => setTimeout(r, 400))

  // 5. 打开「主题与画布背景」对话框，上传本地背景图
  await page.hover('.settings-hub')
  await page.waitForSelector('.shub-pop', { timeout: 3000 })
  await page.evaluate(() => {
    const items = [...document.querySelectorAll('.shub-pop .shub-entry')]
    const it = items.find((x) => x.innerText.includes('主题与画布背景'))
    it.click()
  })
  await page.waitForSelector('.el-dialog:has(.bg-row), .el-dialog', { timeout: 3000 })
  await new Promise((r) => setTimeout(r, 400))

  const pngFile = path.join(os.tmpdir(), 'bcc_test_bg.png')
  fs.writeFileSync(pngFile, Buffer.from(PNG_B64, 'base64'))
  const fileInput = await page.$('input[type=file][accept="image/*"]')
  await fileInput.uploadFile(pngFile)
  await page.waitForSelector('.canvas-wrap.has-bg .canvas-bg', { timeout: 5000 })
  log('✓ 背景图上传成功，画布背景层已挂载')

  // 6. 背景透明度调节（点击滑轨 30% 处）
  const sliderBox = await page.$eval('.bg-opacity-row .el-slider__runway', (el) => {
    const r = el.getBoundingClientRect()
    return { x: r.left + r.width * 0.3, y: r.top + r.height / 2 }
  })
  await page.mouse.click(sliderBox.x, sliderBox.y)
  await new Promise((r) => setTimeout(r, 500))
  const opacity = await page.$eval('.canvas-bg', (el) => parseFloat(el.style.opacity))
  if (!(opacity > 0 && opacity < 0.8)) fail(`背景透明度调节异常：opacity=${opacity}`)
  else log(`✓ 背景透明度可调（当前 ${Math.round(opacity * 100)}%）`)

  // 7. 深色主题兼容：切到深色，背景仍在
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.el-dialog .el-radio-button')]
    const b = btns.find((x) => x.innerText.includes('深色'))
    b.click()
  })
  await new Promise((r) => setTimeout(r, 400))
  const darkOk = await page.evaluate(() => document.documentElement.getAttribute('data-theme') === 'dark')
  const bgStill = await page.$('.canvas-wrap.has-bg .canvas-bg')
  if (!darkOk) fail('对话框切深色主题未生效')
  else if (!bgStill) fail('切深色后自定义背景丢失')
  else log('✓ 深色主题与自定义背景兼容共存')

  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.el-dialog .el-dialog__footer .el-button')]
    btns.find((x) => x.innerText.includes('完成')).click()
  })
  await new Promise((r) => setTimeout(r, 300))
  await page.screenshot({ path: SHOT })
  log('已截图', SHOT)

  // 8. 注入自定义配色（等价持久化状态）→ 重启加载
  await page.evaluate(() => {
    const cfg = JSON.parse(localStorage.getItem('bcc:appearance') || '{}')
    cfg.colorsOn = true
    cfg.colors = { card: '#123456', edge: '#ff0000', text: '#00cc00', border: '#ff00ff' }
    localStorage.setItem('bcc:appearance', JSON.stringify(cfg))
  })
  await page.reload({ waitUntil: 'networkidle2' })
  await page.waitForSelector('.chat-node', { timeout: 15000 })

  const cardBg = await page.$eval('.chat-node', (el) => getComputedStyle(el).backgroundColor)
  if (!cardBg.includes('18, 52, 86')) fail(`自定义卡片底色未生效：${cardBg}`)
  else log('✓ 自定义卡片底色生效（#123456）')

  const cardBorder = await page.$eval('.chat-node', (el) => getComputedStyle(el).borderColor)
  if (!cardBorder.includes('255, 0, 255')) fail(`自定义边框色未生效：${cardBorder}`)
  else log('✓ 自定义边框色生效（#ff00ff）')

  const edgeStroke = await page.$eval('.vue-flow__edge-path', (el) => getComputedStyle(el).stroke)
  if (!/rgb\(255,\s*0,\s*0\)|#ff0000|red/i.test(edgeStroke || '')) fail(`自定义连线颜色未生效：${edgeStroke}`)
  else log('✓ 自定义连线颜色生效（#ff0000）')

  // 9. 持久化：重启后主题 / 背景 / 配色全部自动恢复
  const persisted = await page.evaluate(() => {
    const cfg = JSON.parse(localStorage.getItem('bcc:appearance') || '{}')
    return {
      theme: document.documentElement.getAttribute('data-theme'),
      hasBg: !!document.querySelector('.canvas-wrap.has-bg .canvas-bg'),
      bgOpacity: cfg.bgOpacity,
      colorsOn: cfg.colorsOn
    }
  })
  if (persisted.theme !== 'dark') fail('重启后主题未恢复')
  else if (!persisted.hasBg) fail('重启后背景图未恢复')
  else if (!persisted.colorsOn) fail('重启后自定义配色未恢复')
  else log('✓ 重启后主题 / 背景 / 配色全部自动恢复')

  // 10. 关闭自定义配色 → 回落主题默认
  await page.hover('.settings-hub')
  await page.waitForSelector('.shub-pop', { timeout: 3000 })
  await page.evaluate(() => {
    const items = [...document.querySelectorAll('.shub-pop .shub-entry')]
    items.find((x) => x.innerText.includes('主题与画布背景')).click()
  })
  await new Promise((r) => setTimeout(r, 400))
  await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.el-dialog .sh-dialog-desc')]
    const head = rows.find((x) => x.innerText.includes('启用自定义配色'))
    head.querySelector('.el-switch').click()
  })
  await new Promise((r) => setTimeout(r, 400))
  const fallbackBg = await page.$eval('.chat-node', (el) => getComputedStyle(el).backgroundColor)
  const nodeBgVar = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue('--node-bg'))
  if (nodeBgVar.trim() !== '') fail('关闭配色后 --node-bg 变量未清除')
  else if (fallbackBg.includes('18, 52, 86')) fail(`关闭配色后卡片底色未回落主题默认：${fallbackBg}`)
  else log('✓ 关闭自定义配色后回落主题默认')

  // 11. 画布交互未破坏：连线 / 节点 / 网格背景层
  const edgeCount = await page.$$eval('.vue-flow__edge-path', (els) => els.length)
  const nodeCount = await page.$$eval('.chat-node', (els) => els.length)
  if (edgeCount < 1 || nodeCount < 1) fail(`画布交互异常：${nodeCount} 节点 / ${edgeCount} 连线`)
  else log(`✓ 画布交互正常（${nodeCount} 节点 / ${edgeCount} 连线）`)

  await browser.close()
  log('测试完成')
})().catch((e) => { console.error('✗ 测试崩溃:', e); process.exit(1) })
