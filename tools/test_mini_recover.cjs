/* 快速对话自愈回归：主界面删除「悬浮速记」画布后，快速对话仍能继续用
 * 覆盖两条路径：
 *   A. 删完再打开面板 → 打开时自愈，自动新建画布
 *   B. 面板开着时画布被删 → 发送时自愈，自动重建并重发
 * 前置：后端 :8000、前端 dev :5173 已启动
 * 注意：会临时改写后端 meta miniTreeId，结束（含失败）恢复原值
 */
const puppeteer = require('../frontend/node_modules/puppeteer-core')
const path = require('path')
const os = require('os')

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const APP = 'http://localhost:5173/?mini=1'
const API = 'http://localhost:8000'
const SHOT = path.join(os.tmpdir(), 'bcc_mini_recover.png')

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

/** 无 pywebview 时面板打不开，注入最小 mock 让交互流程可跑 */
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
    // 断言「回复内容」需要一个能真正出字的模型：临时切演示模式，结束恢复
    if (origCfg.provider !== 'mock') {
      await api('/api/llm/config', 'POST', { provider: 'mock' })
      log(`临时切换模型为 mock（原 ${origCfg.provider}）`)
    }

    // 一块「速记」画布 + 一条历史消息，模拟用户已经用过快速对话
    seed = await api('/api/tree/create', 'POST', { title: '自愈测试速记' })
    const rootId = seed.nodeList.find((n) => !n.parentId).nodeId
    await (await fetch(`${API}/api/node/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ treeId: seed.treeId, nodeId: rootId, content: '第一句' })
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
    await sleep(600)

    const openPanel = async () => {
      if (await page.$('.mini-panel')) return
      await page.click('.mini-ball')
      await page.waitForSelector('.mini-panel', { timeout: 10000 })
      await sleep(500)
    }
    const panelTitle = () => page.$eval('.mini-tree', (el) => el.textContent.trim())
    const lastAnswer = () => page.evaluate(() => {
      const bubbles = [...document.querySelectorAll('.mini-msg.assistant .mini-bubble')]
      return bubbles.length ? bubbles[bubbles.length - 1].innerText.trim() : ''
    })
    /** 等这一轮回答真正结束：发送按钮回到「发送」且最后一条回答文本稳定 */
    async function waitStable(timeout = 40000) {
      const start = Date.now()
      let prev = ''
      while (Date.now() - start < timeout) {
        const cur = await page.evaluate(() => {
          const b = [...document.querySelectorAll('.mini-msg.assistant .mini-bubble')]
          const btn = document.querySelector('.mini-send')
          return {
            text: b.length ? b[b.length - 1].innerText.trim() : '',
            idle: !!btn && btn.innerText.trim() === '发送'
          }
        })
        if (cur.idle && cur.text && !cur.text.includes('▍') && cur.text === prev) return cur.text
        prev = cur.text
        await sleep(300)
      }
      throw new Error('等待回复超时')
    }

    // ---------- 路径 A：删完再打开面板 ----------
    await openPanel()
    if ((await panelTitle()) === '自愈测试速记') ok('首次打开绑定到原速记画布')
    else fail(`标题不符：${await panelTitle()}`)

    await api(`/api/tree/delete?treeId=${encodeURIComponent(seed.treeId)}`, 'DELETE')
    seed = null
    log('已模拟主界面删除速记画布')

    // 收起再展开，模拟用户删完回来点球
    await page.click('.mini-ops button[title="收起为悬浮球"]')
    await sleep(400)
    await openPanel()
    await sleep(600)

    const hintA = await page.evaluate(() =>
      [...document.querySelectorAll('.mini-bubble')].map((b) => b.innerText).join('\n'))
    if (hintA.includes('已被删除') && hintA.includes('已自动新建')) ok('打开面板时提示已自动新建画布')
    else fail(`未见自愈提示，气泡内容：${hintA.slice(0, 120)}`)

    const newMetaA = (await api('/api/tree/mini')).treeId
    if (newMetaA && newMetaA !== (orig.treeId || '')) ok(`后端绑定已指向新画布 ${newMetaA}`)
    else fail(`后端绑定未更新：${newMetaA}`)

    // 在新画布上真的发一条，确认可用
    await page.type('.mini-input textarea', '画布删了还能聊吗')
    await page.click('.mini-send')
    await waitStable()
    await sleep(300)
    const ansA = await lastAnswer()
    if (ansA && !ansA.includes('对话树不存在') && !ansA.startsWith('⚠️')) ok(`重建后对话可用，回复：${ansA.slice(0, 40)}…`)
    else fail(`重建后仍不可用：${ansA.slice(0, 80)}`)

    await page.screenshot({ path: SHOT })

    // ---------- 路径 B：面板开着时画布被删，直接发送 ----------
    const metaB = (await api('/api/tree/mini')).treeId
    await sleep(1400) // 越过校验节流，让 ensureAlive 在发送时不再预检
    await api(`/api/tree/delete?treeId=${encodeURIComponent(metaB)}`, 'DELETE')
    log('面板保持打开，模拟画布在背后被删除')

    await page.type('.mini-input textarea', '这次被删也不该报错')
    await page.click('.mini-send')
    await waitStable()
    await sleep(600)
    const allText = await page.evaluate(() =>
      [...document.querySelectorAll('.mini-bubble')].map((b) => b.innerText).join('\n'))
    if (allText.includes('对话树不存在')) fail('仍然弹出「对话树不存在」')
    else ok('发送时自愈，未再出现「对话树不存在」')
    if (allText.includes('已自动新建一块并重新发送')) ok('命中重发分支，内容未丢')
    else log('提示：本轮走的是打开面板自愈或预检路径')

    const metaC = (await api('/api/tree/mini')).treeId
    if (metaC && metaC !== metaB) ok(`后端已切到又一块新画布 ${metaC}`)
    else fail(`发送自愈后绑定异常：${metaC}`)

    // ---------- 路径 C：预检通过、发送瞬间才 404 → 自动重发分支 ----------
    // 用一次假 404 精确命中 rebuilt 分支（真实删除很难卡在这个时间窗）
    await sleep(1400)
    await page.evaluate(() => {
      const orig = window.fetch
      let faked = false
      window.fetch = async (url, opt) => {
        if (!faked && String(url).includes('/api/node/send')) {
          faked = true
          return new Response(JSON.stringify({ detail: '对话树不存在' }), {
            status: 404,
            headers: { 'Content-Type': 'application/json' }
          })
        }
        return orig(url, opt)
      }
    })
    await page.type('.mini-input textarea', '命重发分支的问题')
    await page.click('.mini-send')
    await waitStable()
    await sleep(600)
    const textC = await page.evaluate(() =>
      [...document.querySelectorAll('.mini-bubble')].map((b) => b.innerText).join('\n'))
    if (textC.includes('已自动新建一块并重新发送')) ok('发送瞬间 404：命中自动重发分支')
    else fail(`未命中重发分支：${textC.slice(-160)}`)
    if (textC.includes('对话树不存在')) fail('重发分支仍暴露原始报错')
    else ok('重发分支对用户无报错')
    const asked = await page.evaluate(() =>
      [...document.querySelectorAll('.mini-msg.user .mini-bubble')]
        .filter((b) => b.innerText.includes('命重发分支的问题')).length)
    if (asked === 1) ok('问题气泡只有一条，没有重复')
    else fail(`问题气泡出现 ${asked} 次`)

    // ---------- 路径 E：画布还在，发送时根节点已被删 → 就地补根节点重发 ----------
    await sleep(1400) // 越过校验节流，让发送直接打到已被删的节点上
    const metaE = (await api('/api/tree/mini')).treeId
    const treeE0 = await api(`/api/tree/get?treeId=${metaE}`)
    const rootE = treeE0.nodeList.find((n) => !n.parentId)
    await api(`/api/node/delete?treeId=${metaE}&nodeId=${rootE.nodeId}`, 'DELETE')
    log('面板保持打开，已删除画布内唯一的会话节点')
    await page.type('.mini-input textarea', '只删会话的问题')
    await page.click('.mini-send')
    await waitStable()
    await sleep(600)
    const textE = await page.evaluate(() =>
      [...document.querySelectorAll('.mini-bubble')].map((b) => b.innerText).join('\n'))
    // 预检自愈的提示是瞬态的（发送收尾会被落库内容同步掉），不作为断言；
    // 关键保证：无原始报错、画布不换、问题不丢、补回了根节点。
    log('删节点后发送：自愈完成（提示为瞬态，不持久展示）')
    if (textE.includes('节点不存在') || textE.includes('对话树不存在')) fail('补根分支仍暴露原始报错')
    else ok('补根分支对用户无报错')
    if ((await api('/api/tree/mini')).treeId === metaE) ok('画布没被换掉（就地修复而非重建）')
    else fail('画布被重建了，应该只补根节点')
    const askedE = await page.evaluate(() =>
      [...document.querySelectorAll('.mini-msg.user .mini-bubble')]
        .filter((b) => b.innerText.includes('只删会话的问题')).length)
    if (askedE === 1) ok('问题气泡只有一条，没有重复')
    else fail(`问题气泡出现 ${askedE} 次`)
    const treeE = await api(`/api/tree/get?treeId=${metaE}`)
    if ((treeE.nodeList || []).some((n) => !n.parentId)) ok('画布上已有根节点可供后续对话')
    else fail('补根失败，画布仍是空的')

    // ---------- 路径 D：画布还在，但里面的会话（根节点）被删 ----------
    await sleep(1400)
    const metaD = (await api('/api/tree/mini')).treeId
    const treeD = await api(`/api/tree/get?treeId=${metaD}`)
    const rootD = treeD.nodeList.find((n) => !n.parentId)
    await api(`/api/node/delete?treeId=${metaD}&nodeId=${rootD.nodeId}`, 'DELETE')
    const emptyD = await api(`/api/tree/get?treeId=${metaD}`)
    if ((emptyD.nodeList || []).length === 0) ok('已模拟：画布内唯一的会话节点被删除')
    else fail(`删除后仍有 ${emptyD.nodeList.length} 个节点`)

    // 收起再展开，模拟用户删完节点回来点球
    await page.click('.mini-ops button[title="收起为悬浮球"]')
    await sleep(300)
    await openPanel()
    await sleep(800)

    const hintD = await page.evaluate(() =>
      [...document.querySelectorAll('.mini-bubble')].map((b) => b.innerText).join('\n'))
    if (hintD.includes('已被删除') && hintD.includes('已自动新建')) ok('删节点后打开面板：提示已自动新建会话')
    else fail(`未见提示，气泡：${hintD.slice(0, 120)}`)

    const healedD = await api(`/api/tree/get?treeId=${metaD}`)
    const rootsD = (healedD.nodeList || []).filter((n) => !n.parentId)
    if (rootsD.length === 1) ok('画布已补回一个根节点（画布本身未重建）')
    else fail(`补根后根节点数 = ${rootsD.length}`)
    if ((await api('/api/tree/mini')).treeId === metaD) ok('画布绑定未变，仍是原来那块')
    else fail('画布被换掉了，应该就地补节点')

    await page.type('.mini-input textarea', '删掉会话后还能聊吗')
    await page.click('.mini-send')
    await waitStable()
    const ansD = await page.evaluate(() => {
      const b = [...document.querySelectorAll('.mini-msg.assistant .mini-bubble')]
      return b.length ? b[b.length - 1].innerText.trim() : ''
    })
    if (ansD && !ansD.includes('对话树不存在') && !ansD.startsWith('⚠️')) ok(`删节点后对话可用，回复：${ansD.slice(0, 30)}…`)
    else fail(`删节点后仍不可用：${ansD.slice(0, 80)}`)

    const finalD = await api(`/api/tree/get?treeId=${metaD}`)
    const msgsD = (finalD.nodeList.find((n) => !n.parentId) || {}).messages || []
    if (msgsD.length >= 2) ok(`问答已写入根节点（${msgsD.length} 条消息）`)
    else fail(`根节点没有落库：${msgsD.length} 条`)

    await page.screenshot({ path: path.join(os.tmpdir(), 'bcc_mini_recover_b.png') })
    log('截图：', SHOT)
  } catch (e) {
    fail(`异常：${e.message}`)
  } finally {
    if (browser) await browser.close()
    // 恢复模型来源（mock 只是测试期间临时切）
    if (origCfg.provider !== 'mock') {
      try {
        await api('/api/llm/config', 'POST', { provider: origCfg.provider })
        const back = await api('/api/llm/config')
        if (back.provider === origCfg.provider) log(`已恢复模型来源 = ${back.provider}`)
        else fail(`模型来源未恢复：${back.provider}`)
      } catch (e) { fail('恢复模型来源失败：' + e.message) }
    }
    try { await api('/api/tree/mini', 'POST', { treeId: orig.treeId || '' }) } catch (e) { /* ignore */ }
    if (seed) {
      try { await api(`/api/tree/delete?treeId=${encodeURIComponent(seed.treeId)}`, 'DELETE') } catch (e) { /* ignore */ }
    }
    // 清理测试过程中自动新建的「悬浮速记」画布
    try {
      const list = await api('/api/tree/list')
      const mine = (list.trees || list || []).filter((t) => t.title === '悬浮速记')
      for (const t of mine) {
        // 只删本轮之后的（原用户数据不动）：按创建时间兜底，这里用 nodeCount<=0 且非原绑定
        if (t.treeId !== orig.treeId && (t.nodeCount || 0) === 0) {
          await api(`/api/tree/delete?treeId=${encodeURIComponent(t.treeId)}`, 'DELETE')
        }
      }
    } catch (e) { /* ignore */ }
    if (orig.treeId) {
      try { await api('/api/tree/mini', 'POST', { treeId: orig.treeId }) } catch (e) { /* ignore */ }
    }
    const after = await api('/api/tree/mini').catch(() => null)
    log('已恢复 miniTreeId =', after?.treeId || '(空)')
    console.log(failed ? `\n${failed} 项失败` : '\n全部通过')
    process.exitCode = failed ? 1 : 0
  }
})()
