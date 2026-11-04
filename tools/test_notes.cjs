/* 笔记功能回归：手动记录 / 划词收藏 / 刷新持久化 / 编辑 / 复制 / 删除 */
const puppeteer = require('puppeteer-core')

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const APP = 'http://localhost:5173/'
const API = 'http://localhost:8000'
const SHOT = 'C:/Users/liuzhijun/AppData/Local/Temp/bcc_notes_shot.png'

const log = (...a) => console.log('•', ...a)
const fail = (msg) => { console.error('✗ ' + msg); process.exitCode = 1 }

async function api(path, method = 'GET', body) {
  const res = await fetch(API + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined
  })
  if (!res.ok) throw new Error(`${path} -> ${res.status} ${await res.text()}`)
  const text = await res.text()
  try { return JSON.parse(text) } catch { return text }
}

async function seed() {
  const tree = await api('/api/tree/create', 'POST', { title: '笔记功能测试画布' })
  const rootId = tree.nodeList[0].nodeId
  // 走流式接口写入一条问答（mock 模式，秒回）
  const res = await fetch(`${API}/api/node/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ treeId: tree.treeId, nodeId: rootId, content: '什么是提示词工程？' })
  })
  await res.text()
  return { treeId: tree.treeId, nodeId: rootId }
}

;(async () => {
  const seeded = await seed()
  log('已准备画布', seeded.treeId)

  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage']
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 900 })

  page.on('console', (m) => { if (m.type() === 'error') console.log('  [console.error]', m.text()) })
  page.on('pageerror', (e) => fail('页面异常: ' + e.message))

  await page.goto(APP, { waitUntil: 'networkidle2' })
  await page.evaluate((id) => {
    localStorage.setItem('bcc:lastTreeId', id)
    localStorage.removeItem('bcc:notes')
  }, seeded.treeId)
  await page.reload({ waitUntil: 'networkidle2' })
  await page.waitForSelector('.chat-node', { timeout: 15000 })
  log('画布已加载')

  // 1. 入口按钮 → 面板展开
  await page.waitForSelector('.note-fab', { timeout: 5000 })
  const fabBadgeBefore = await page.$eval('.note-fab', el => el.querySelector('.note-fab-count')?.textContent || '')
  await page.click('.note-fab')
  await page.waitForSelector('.note-panel', { timeout: 3000 })
  log('面板展开 ✓（初始徽标: "' + fabBadgeBefore + '"）')
  const emptyText = await page.$eval('.note-panel', el => el.textContent.includes('还没有笔记'))
  if (!emptyText) fail('空状态文案缺失')

  await new Promise(r => setTimeout(r, 500))   // 等滑入动画结束
  const box = await page.$eval('.note-panel', el => {
    const r = el.getBoundingClientRect()
    return { x: r.x, w: r.width, tx: getComputedStyle(el).transform }
  })
  log('面板几何:', JSON.stringify(box))
  if (box.x < 0 || box.x + box.w > 1441) fail('面板未完全进入视口: ' + JSON.stringify(box))

  // 2. 手动输入一条
  await page.click('.np-compose textarea')
  await page.type('.np-compose textarea', '手动笔记：以后写提示词时可以复用的结构化模板')
  await page.click('.np-btn.primary')
  await page.waitForSelector('.np-item', { timeout: 3000 })
  let meta = await page.$eval('.np-item', el => el.textContent)
  if (!meta.includes('✍️ 手动记录')) fail('手动笔记来源标注不对: ' + meta)
  else log('手动记录 ✓ 来源标注「✍️ 手动记录」')

  // 2b. 消息级收藏：AI 回答整条 + 我的提问整条
  await page.hover('.msg.assistant .assistant-bubble')
  await page.click('.msg.assistant .msg-note-btn')
  await page.waitForFunction(() => document.querySelectorAll('.np-item').length === 2, { timeout: 3000 })
  const aiSrc = await page.$eval('.np-item', el => el.textContent)
  if (!aiSrc.includes('· AI')) fail('AI 消息收藏来源缺「AI」: ' + aiSrc)
  else log('整条 AI 回答收藏 ✓')

  await page.hover('.msg.user .user-bubble')
  await page.click('.msg.user .msg-note-btn')
  await page.waitForFunction(() => document.querySelectorAll('.np-item').length === 3, { timeout: 3000 })
  const mySrc = await page.$eval('.np-item', el => el.textContent)
  if (!mySrc.includes('· 我')) fail('我的提问收藏来源缺「我」: ' + mySrc)
  else log('整条我的提问收藏 ✓')

  // 3. 划词收藏（选中 AI 回答里的文字 → 面板 → 📝 收藏）
  //    用真实鼠标拖选，确保 selection / mouseup 与用户操作一致
  const bubble = await page.$('.assistant-bubble')
  const bb = await bubble.boundingBox()
  await page.mouse.move(bb.x + 10, bb.y + 14)
  await page.mouse.down()
  await page.mouse.move(bb.x + Math.min(bb.width - 10, 200), bb.y + 14, { steps: 14 })
  await page.mouse.up()
  const selInfo = await page.evaluate(() => (window.getSelection()?.toString() || '').slice(0, 40))
  log('拖选内容:', JSON.stringify(selInfo))
  await page.waitForSelector('.branch-pop', { timeout: 5000 })
  const popText = await page.$eval('.branch-pop-text', el => el.textContent.trim())
  log('划词面板弹出 ✓ 选中片段:', popText.slice(0, 30))

  await page.click('.pop-btn.note')
  await page.waitForFunction(
    () => document.querySelectorAll('.np-item').length === 4,
    { timeout: 4000 }
  )
  const firstItem = await page.$eval('.np-item', el => el.textContent)
  if (!firstItem.includes('📎') || !firstItem.includes('笔记功能测试画布')) {
    fail('划词收藏的来源标注不对: ' + firstItem)
  } else {
    log('划词收藏 ✓ 来源含画布名与节点名')
  }

  // 4. 刷新页面 → 持久化
  await page.reload({ waitUntil: 'networkidle2' })
  await page.waitForSelector('.note-fab', { timeout: 10000 })
  const badge = await page.$eval('.note-fab', el => el.querySelector('.note-fab-count')?.textContent || '')
  if (badge !== '4') fail(`刷新后徽标应为 4，实际 "${badge}"`)
  else log('刷新持久化 ✓ 徽标仍为 4')
  await page.click('.note-fab')
  await page.waitForSelector('.note-panel', { timeout: 3000 })
  await new Promise(r => setTimeout(r, 450))
  const afterReload = await page.$$eval('.np-item', els => els.length)
  if (afterReload !== 4) fail(`刷新后应有 4 条笔记，实际 ${afterReload}`)

  // 5. 编辑
  await page.click('.np-item .np-item-actions .np-mini:nth-child(2)')
  await page.waitForSelector('.np-item.editing textarea', { timeout: 3000 })
  await page.evaluate(() => {
    const ta = document.querySelector('.np-item.editing textarea')
    ta.value = ''
    ta.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await page.type('.np-item.editing textarea', '手动笔记（已编辑）：结构化提示词模板 v2')
  await page.click('.np-item.editing .np-mini.primary')
  await page.waitForFunction(
    () => !document.querySelector('.np-item.editing'),
    { timeout: 3000 }
  )
  const edited = await page.$eval('.np-item', el => el.textContent)
  if (!edited.includes('v2')) fail('编辑未生效: ' + edited)
  else log('编辑 ✓')

  // 6. 复制（降级路径也应能成功提示）
  await page.click('.np-item .np-item-actions .np-mini:nth-child(1)')
  await page.waitForFunction(
    () => [...document.querySelectorAll('.el-message')].some(e => e.textContent.includes('已复制')),
    { timeout: 3000 }
  )
  log('复制 ✓ 出现「已复制」提示')

  // 7. 删除（二次确认）
  await page.click('.np-item .np-mini.danger')
  await page.waitForSelector('.el-message-box__btns .el-button--primary', { timeout: 3000 })
  await page.click('.el-message-box__btns .el-button--primary')
  await page.waitForFunction(
    () => document.querySelectorAll('.np-item').length === 3,
    { timeout: 4000 }
  )
  log('删除 ✓ 剩 3 条')

  // 8. 搜索过滤
  await page.type('.np-search input', '不存在的关键词zzz')
  await page.waitForFunction(
    () => document.querySelector('.np-panel .np-empty, .note-panel .np-empty')?.textContent.includes('没有匹配'),
    { timeout: 3000 }
  )
  log('搜索空态 ✓')
  await page.click('.np-search-clear')

  // 截图（面板打开、含 1 条笔记）
  await page.screenshot({ path: SHOT })
  log('截图:', SHOT)

  await browser.close()
  log(process.exitCode ? '有失败项' : '全部通过')
})().catch(e => { console.error('✗ 异常:', e); process.exit(1) })
