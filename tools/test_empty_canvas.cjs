/* 空画布回归：画布里的对话被全部删除后
 *   1. 主界面必须给出「新建一个对话」的入口（不能只有空白画布）
 *   2. 点它就地补回一张根会话，画布 id / 名字都不变
 * 前置：后端 :8000、前端 dev :5173 已启动
 */
const puppeteer = require('../frontend/node_modules/puppeteer-core')
const path = require('path')
const os = require('os')

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const APP = 'http://localhost:5173/'
const API = 'http://localhost:8000'
const SHOT = path.join(os.tmpdir(), 'bcc_empty_canvas.png')

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

;(async () => {
  let seed = null
  let browser = null
  try {
    // 一块有内容的画布，然后把它唯一的节点删掉，模拟用户「把对话都删了」
    seed = await api('/api/tree/create', 'POST', { title: '空画布回归' })
    const rootId = seed.nodeList.find((n) => !n.parentId).nodeId
    await api(`/api/node/delete?treeId=${seed.treeId}&nodeId=${rootId}`, 'DELETE')
    const empty = await api(`/api/tree/get?treeId=${seed.treeId}`)
    if ((empty.nodeList || []).length === 0) ok('前置：画布节点已清空')
    else fail(`前置失败，还有 ${empty.nodeList.length} 个节点`)

    browser = await puppeteer.launch({
      executablePath: EDGE,
      headless: 'new',
      args: ['--no-sandbox', '--disable-gpu']
    })
    const page = await browser.newPage()
    await page.setViewport({ width: 1280, height: 800 })
    // 直接进入这块空画布
    await page.evaluateOnNewDocument((id) => {
      localStorage.setItem('bcc:lastTreeId', id)
    }, seed.treeId)
    await page.goto(APP, { waitUntil: 'networkidle2' })
    await page.waitForSelector('.canvas-wrap', { timeout: 15000 })
    await sleep(1200)

    // ---------- 1. 空画布必须有新建入口 ----------
    const box = await page.$('.empty-canvas')
    if (box) ok('空画布出现提示层')
    else fail('空画布没有提示层，用户无处新建会话')

    const label = box ? await page.$eval('.empty-card .el-button', (b) => b.innerText.trim()) : ''
    if (label.includes('新建')) ok(`提示层有新建入口：${label}`)
    else fail(`入口文案异常：${label || '(无按钮)'}`)

    const noNodes = await page.evaluate(() => document.querySelectorAll('.vue-flow__node').length)
    if (noNodes === 0) ok('画布上确实没有节点卡片')
    else fail(`画布上仍有 ${noNodes} 个节点`)

    await page.screenshot({ path: SHOT })

    // ---------- 2. 点一下就地补回根会话 ----------
    await page.click('.empty-card .el-button')
    await sleep(1200)
    const after = await page.evaluate(() => ({
      nodes: document.querySelectorAll('.vue-flow__node').length,
      hasEmpty: !!document.querySelector('.empty-canvas'),
      title: (document.querySelector('.tree-title, .canvas-title') || {}).innerText || ''
    }))
    if (after.nodes === 1) ok('点「新建一个对话」后出现 1 张卡片')
    else fail(`点完仍是 ${after.nodes} 张卡片`)
    if (!after.hasEmpty) ok('提示层自动消失')
    else fail('提示层没有消失')

    const fresh = await api(`/api/tree/get?treeId=${seed.treeId}`)
    if (fresh.treeId === seed.treeId && (fresh.nodeList || []).length === 1) {
      ok(`画布未重建，就地补回根节点（${fresh.nodeList[0].title}）`)
    } else {
      fail(`画布状态异常：${fresh.treeId} / ${(fresh.nodeList || []).length} 个节点`)
    }

    // ---------- 3. 幂等：已有根节点时不会重复创建 ----------
    await page.reload({ waitUntil: 'networkidle2' })
    await sleep(900)
    const again = await api(`/api/tree/get?treeId=${seed.treeId}`)
    if ((again.nodeList || []).length === 1) ok('重进画布不会多出卡片（补根是幂等的）')
    else fail(`重进后节点数 = ${again.nodeList.length}`)

    log('截图：', SHOT)
  } catch (e) {
    fail(`异常：${e.message}`)
  } finally {
    if (browser) await browser.close()
    if (seed) {
      try { await api(`/api/tree/delete?treeId=${encodeURIComponent(seed.treeId)}`, 'DELETE') } catch (e) { /* ignore */ }
    }
    console.log(failed ? `\n${failed} 项失败` : '\n全部通过')
    process.exitCode = failed ? 1 : 0
  }
})()
