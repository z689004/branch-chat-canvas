/* exe 冒烟：通过 CDP 连上打包后的应用，验证
 *   1. 捆绑后端已包含 /api/node/create-root（新接口）
 *   2. 捆绑前端是最新构建（包含空画布提示层样式/逻辑标记）
 * 前置：exe 已带 BCC_REMOTE_DEBUG_PORT=9333 启动
 */
const puppeteer = require('../frontend/node_modules/puppeteer-core')

let failed = 0
const ok = (m) => console.log('✓', m)
const fail = (m) => { failed++; console.error('✗', m) }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

;(async () => {
  let browser = null
  try {
    const list = await (await fetch('http://127.0.0.1:9333/json')).json()
    const main = list.find((t) => t.type === 'page' && !t.url.includes('mini=1'))
    if (!main) throw new Error('找不到主窗口页面')

    const ver = await (await fetch('http://127.0.0.1:9333/json/version')).json()
    browser = await puppeteer.connect({
      browserWSEndpoint: ver.webSocketDebuggerUrl,
      defaultViewport: null
    })
    const target = await browser.pages()
    const page = target.find((p) => !(p.url() || '').includes('mini=1')) || target[0]
    await sleep(1500)

    // 1. 新接口存在：假 treeId → 404 detail「对话树不存在」（说明路由已注册，而非 405/Not Found）
    const probe = await page.evaluate(async () => {
      const r = await fetch('/api/node/create-root', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ treeId: 'no-such-tree' })
      })
      return { status: r.status, body: await r.text() }
    })
    if (probe.status === 404 && probe.body.includes('对话树不存在')) ok(`补根接口已内置（404 对话树不存在）`)
    else fail(`补根接口异常：${probe.status} ${probe.body.slice(0, 80)}`)

    // 2. 前端是最新构建：资源清单里应包含新哈希的 js，且 js 内含空画布标记
    const assets = await page.evaluate(() =>
      performance.getEntriesByType('resource').map((e) => e.name))
    const js = assets.find((u) => /index-[\w-]+\.js/.test(u))
    ok(`加载的前端资源：${(js || '').split('/').pop()}`)
    const hasNew = await page.evaluate(async (u) => {
      const t = await (await fetch(u)).text()
      return { empty: t.includes('empty-canvas'), repair: t.includes('节点不存在') }
    }, js)
    if (hasNew.empty) ok('前端包含空画布提示层（最新构建）')
    else fail('前端是旧构建：没有 empty-canvas 标记')
    if (hasNew.repair) ok('前端包含节点/画布分开自愈逻辑')
    else fail('前端是旧构建：没有补根自愈标记')

    // 3. 悬浮球窗口也在
    const mini = list.find((t) => t.type === 'page' && t.url.includes('mini=1'))
    if (mini) ok('悬浮球窗口正常')
    else fail('悬浮球窗口缺失')
  } catch (e) {
    fail(`异常：${e.message}`)
  } finally {
    if (browser) { try { browser.disconnect() } catch (e) { /* ignore */ } }
    console.log(failed ? `\n${failed} 项失败` : '\n冒烟通过')
    process.exitCode = failed ? 1 : 0
  }
})()
