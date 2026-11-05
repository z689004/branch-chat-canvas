/* 卡片缩放探针：八个方向各拖一次，量化「拖动边 → 对应边动、对面边不动」
 * 输出每个方向的 before/after 矩形，肉眼可判读
 */
const puppeteer = require('../frontend/node_modules/puppeteer-core')
const API = 'http://localhost:8000'
const APP = 'http://localhost:5173/'
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function api(p, method = 'GET', body) {
  const r = await fetch(API + p, {
    method, headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined
  })
  if (!r.ok) throw new Error(`${p} -> ${r.status}`)
  return r.json()
}

const DIRS = [
  { dir: 'e', dx: 80, dy: 0 },
  { dir: 'w', dx: -80, dy: 0 },
  { dir: 's', dx: 0, dy: 80 },
  { dir: 'n', dx: 0, dy: -80 },
  { dir: 'se', dx: 60, dy: 60 },
  { dir: 'sw', dx: -60, dy: 60 },
  { dir: 'ne', dx: 60, dy: -60 },
  { dir: 'nw', dx: -60, dy: -60 }
]

;(async () => {
  let tree = null
  let browser = null
  try {
    tree = await api('/api/tree/create', 'POST', { title: '缩放探针' })
    browser = await puppeteer.launch({ executablePath: EDGE, headless: 'new', args: ['--no-sandbox'] })
    const page = await browser.newPage()
    await page.setViewport({ width: 1400, height: 900 })
    await page.evaluateOnNewDocument((id) => localStorage.setItem('bcc:lastTreeId', id), tree.treeId)
    await page.goto(APP, { waitUntil: 'networkidle2' })
    await page.waitForSelector('.chat-node', { timeout: 15000 })
    await sleep(1000)

    const rect = () => page.$eval('.chat-node', (el) => {
      const r = el.getBoundingClientRect()
      return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }
    })
    const handleBox = async (dir) => page.$eval(`.rs-${dir}`, (el) => {
      const r = el.getBoundingClientRect()
      return { cx: r.x + r.width / 2, cy: r.y + r.height / 2 }
    })

    for (const d of DIRS) {
      const before = await rect()
      const p = await handleBox(d.dir)
      await page.mouse.move(p.cx, p.cy)
      await page.mouse.down()
      await page.mouse.move(p.cx + d.dx, p.cy + d.dy, { steps: 8 })
      await page.mouse.up()
      await sleep(500)
      const after = await rect()
      const dW = after.w - before.w, dH = after.h - before.h
      const anchorOk = {
        e: after.x === before.x,
        w: after.x + after.w === before.x + before.w,
        s: after.y === before.y,
        n: after.y + after.h === before.y + before.h
      }
      console.log(`${d.dir.padEnd(2)}  Δw=${String(dW).padStart(4)} Δh=${String(dH).padStart(4)}  ` +
        `left ${before.x}→${after.x}  top ${before.y}→${after.y}  ` +
        `右/下边界 ${before.x + before.w}/${before.y + before.h}→${after.x + after.w}/${after.y + after.h}  ` +
        `对面边固定=${d.dir.split('').every((c) => anchorOk[c]) ? '是' : '否'}`)
    }

    const st = await api(`/api/tree/get?treeId=${tree.treeId}`)
    console.log('落库 size =', JSON.stringify(st.nodeList[0].size), 'x/y =', st.nodeList[0].x, st.nodeList[0].y)
  } catch (e) {
    console.error('异常：', e.message)
  } finally {
    if (browser) await browser.close()
    if (tree) { try { await api(`/api/tree/delete?treeId=${tree.treeId}`, 'DELETE') } catch (e) {} }
  }
})()
