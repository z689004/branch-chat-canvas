/* 快速对话：划选文字 → 生成子分支 → 会话切到分支
 * 覆盖：
 *   1. 面板内文字可选中（user-select 已放开）
 *   2. 选中后浮出「精简 / 完整」入口
 *   3. 点精简 → 后端多出一个子节点，父节点正确
 *   4. 面板切到子分支（路径条 + 选中内容作为上下文），并记住节点
 *   5. 在分支里提问 → 落到子节点上（不会被 ensureAlive 冲回根会话）
 *   6. 「回到主会话」回到根节点
 * 前置：后端 :8000、前端 dev :5173 已启动；会临时改写 meta miniTreeId 与模型配置，结束恢复
 */
const puppeteer = require('../frontend/node_modules/puppeteer-core')
const path = require('path')
const os = require('os')

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const APP = 'http://localhost:5173/?mini=1'
const API = 'http://localhost:8000'
const SHOT = path.join(os.tmpdir(), 'bcc_mini_branch.png')

let failed = 0
const log = (...a) => console.log('•', ...a)
const ok = (m) => console.log('✓', m)
const fail = (m) => { failed++; console.error('✗', m) }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function api(p, method = 'GET', body) {
  const res = await fetch(API + p, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined
  })
  if (!res.ok) throw new Error(`${p} -> ${res.status} ${await res.text()}`)
  return res.json()
}

const MOCK_PYWEBVIEW = () => {
  const noop = async () => true
  window.pywebview = {
    api: {
      toggle_mini: noop, toggle_main: noop, open_main: noop, show_ball: noop,
      quit_app: noop, get_ball_pos: async () => ({ x: 0, y: 0 }),
      move_ball: () => {}, end_drag: async () => {},
      expand_menu: async () => {}, collapse_menu: async () => {}
    }
  }
}

;(async () => {
  const orig = await api('/api/tree/mini')
  const origCfg = await api('/api/llm/config')
  let seed = null
  let browser = null

  try {
    if (origCfg.provider !== 'mock') {
      await api('/api/llm/config', 'POST', { provider: 'mock' })
      log(`临时切换模型为 mock（原 ${origCfg.provider}）`)
    }

    // 一块「速记」画布 + 一段可划选的回答
    seed = await api('/api/tree/create', 'POST', { title: '分支测试速记' })
    const rootId = seed.nodeList.find((n) => !n.parentId).nodeId
    await (await fetch(`${API}/api/node/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ treeId: seed.treeId, nodeId: rootId, content: '这里讲的是什么' })
    })).text()
    await api('/api/tree/mini', 'POST', { treeId: seed.treeId })

    browser = await puppeteer.launch({
      executablePath: EDGE,
      headless: 'new',
      args: ['--no-sandbox', '--disable-gpu']
    })
    const page = await browser.newPage()
    await page.setViewport({ width: 420, height: 620 })
    await page.evaluateOnNewDocument(MOCK_PYWEBVIEW)
    await page.goto(APP, { waitUntil: 'networkidle2' })
    await page.waitForSelector('.mini-ball', { timeout: 15000 })
    await sleep(500)

    await page.click('.mini-ball')
    await page.waitForSelector('.mini-panel', { timeout: 10000 })
    await sleep(700)

    // ---------- 1. 文字可选 ----------
    const sel = await page.$eval('.mini-bubble', (el) => {
      const cs = getComputedStyle(el)
      return cs.userSelect || cs.webkitUserSelect
    })
    if (sel === 'text') ok('对话内容可选中（user-select: text）')
    else fail(`气泡仍是 user-select: ${sel}`)

    // ---------- 2. 真实鼠标拖拽划选 → 浮层 ----------
    // 完全模拟真实用户流程：点球展开（会留下光标残留）→ 在回答气泡上按住拖动
    const bb = await page.evaluate(() => {
      const els = [...document.querySelectorAll('.mini-msg.assistant .mini-bubble')]
      const el = els[els.length - 1]
      const b = el.getBoundingClientRect()
      return { x: b.x, y: b.y, w: b.width, h: b.height }
    })
    const dragY = Math.min(bb.y + 60, bb.y + bb.h - 20)
    await page.mouse.move(bb.x + bb.w - 24, dragY)
    await page.mouse.down()
    for (let i = 1; i <= 12; i++) await page.mouse.move(bb.x + bb.w - 24 - i * 12, dragY)
    await page.mouse.up()
    await sleep(400)
    const selText = await page.evaluate(() => (window.getSelection() || '').toString().trim())
    if (selText.length >= 4) ok('真实拖拽划选成功：' + JSON.stringify(selText.slice(0, 14)))
    else fail('真实拖拽没有选中文字（选中 ' + JSON.stringify(selText) + '）')
    const pop = await page.$('.mini-sel-pop')
    if (pop) ok('选中后浮出建分支入口')
    else fail('选中后没有出现浮层')
    const quoted = pop ? await page.$eval('.mini-sel-pop', (el) => el.innerText.replace(/\s+/g, ' ')) : ''
    log('浮层内容:', quoted)

    // ---------- 3. 点「精简」建分支 ----------
    const before = await api('/api/tree/get?treeId=' + seed.treeId)
    await page.evaluate(() => {
      const btn = document.querySelectorAll('.mini-sel-pop .sp-btn')[0]
      if (btn) btn.click()
    })
    await sleep(1200)

    const after = await api('/api/tree/get?treeId=' + seed.treeId)
    const added = after.nodeList.filter((n) => !before.nodeList.some((o) => o.nodeId === n.nodeId))
    if (added.length === 1) ok('后端新增 1 个子节点')
    else fail(`新增节点数 ${added.length}，应为 1`)
    const child = added[0]
    if (child && child.parentId === rootId) ok('子节点挂在当前会话下')
    else fail(`父节点错误：${child && child.parentId}`)
    if (child && child.selectedContext && child.selectedContext.length >= 4) ok('选中内容已作为分支上下文')
    else fail('selectedContext 为空')
    if (child && child.contextMode === 'simple') ok('精简模式生效')
    else fail(`contextMode = ${child && child.contextMode}`)

    // ---------- 4. 面板切到分支 ----------
    const crumb = await page.$('.mini-crumb')
    if (crumb) ok('面板显示分支路径条')
    else fail('没有切到子分支（缺少路径条）')
    const storedNode = await page.evaluate(() => localStorage.getItem('bcc:miniNodeId'))
    if (child && storedNode === child.nodeId) ok('当前节点已记住为新分支')
    else fail(`localStorage 节点不一致：${storedNode}`)
    const ctxShown = await page.evaluate(() => {
      const q = document.querySelector('.mini-quote')
      return q ? q.innerText.trim() : ''
    })
    if (ctxShown.length >= 4) ok('空会话里展示了选中的上下文')
    else log('（上下文块未显示，可能有历史消息）')

    // ---------- 5. 在分支里提问（跨过 1.2s 校验节流，确认不会回根） ----------
    await sleep(1500)
    await page.type('.mini-input textarea', '沿着这段继续讲')
    await page.click('.mini-send')
    for (let i = 0; i < 60; i++) {
      await sleep(300)
      const t = await page.evaluate(() => {
        const b = [...document.querySelectorAll('.mini-msg.assistant .mini-bubble')]
        return b.length ? b[b.length - 1].innerText.trim() : ''
      })
      if (t && !t.includes('▍')) break
    }
    const fresh = await api('/api/tree/get?treeId=' + seed.treeId)
    const childNow = fresh.nodeList.find((n) => n.nodeId === (child && child.nodeId))
    if (childNow && childNow.messages.length === 2) ok('提问落到子分支节点（2 条消息）')
    else fail(`子节点消息数 ${childNow ? childNow.messages.length : 'N/A'}`)
    const rootNow = fresh.nodeList.find((n) => n.nodeId === rootId)
    if (rootNow && rootNow.messages.length === 2) ok('根会话没有被污染')
    else fail(`根节点消息数变成 ${rootNow && rootNow.messages.length}`)
    const stillCrumb = !!(await page.$('.mini-crumb'))
    if (stillCrumb) ok('提问后仍停在分支上')
    else fail('提问后被打回根会话')

    await page.screenshot({ path: SHOT })

    // ---------- 6. 回到主会话 ----------
    await page.evaluate(() => {
      const b = document.querySelector('.mini-crumb button')
      if (b) b.click()
    })
    await sleep(500)
    if (!(await page.$('.mini-crumb'))) ok('「回到主会话」退出分支')
    else fail('点击后仍在分支上')
    const back = await page.evaluate(() => localStorage.getItem('bcc:miniNodeId'))
    if (back === rootId) ok('节点指针回到根会话')
    else fail(`回根后节点指针为 ${back}`)
  } catch (e) {
    fail('脚本异常：' + (e && e.message))
  } finally {
    if (browser) await browser.close()
    try { await api('/api/tree/mini', 'POST', { treeId: orig.treeId || '' }) } catch (e) { /* ignore */ }
    try {
      if (origCfg.provider !== 'mock') await api('/api/llm/config', 'POST', { provider: origCfg.provider })
    } catch (e) { /* ignore */ }
    if (seed) { try { await api('/api/tree/delete?treeId=' + seed.treeId, 'DELETE') } catch (e) { /* ignore */ } }
    console.log(failed ? `\n${failed} 项失败` : '\n全部通过')
    process.exit(failed ? 1 : 0)
  }
})()
