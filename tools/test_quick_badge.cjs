/* 快速对话标识回归：主界面里给「悬浮速记」画布的根节点打 ⚡ 快速对话 徽标
 * 前置：后端 :8000、前端 dev :5173 已启动
 * 说明：会临时改写后端 meta miniTreeId，测试结束（含失败）恢复原值
 */
const puppeteer = require('../frontend/node_modules/puppeteer-core')
const path = require('path')
const os = require('os')

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const APP = 'http://localhost:5173/'
const API = 'http://localhost:8000'
const SHOT_MINI = path.join(os.tmpdir(), 'bcc_quick_badge.png')
const SHOT_OTHER = path.join(os.tmpdir(), 'bcc_quick_badge_other.png')

let failed = 0
const log = (...a) => console.log('•', ...a)
const ok = (msg) => console.log('✓', msg)
const fail = (msg) => { failed++; console.error('✗', msg) }

async function api(p, method = 'GET', body) {
  const res = await fetch(API + p, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined
  })
  if (!res.ok) throw new Error(`${p} -> ${res.status} ${await res.text()}`)
  return res.json()
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

;(async () => {
  const orig = await api('/api/tree/mini')
  log('原 miniTreeId =', orig.treeId || '(空)', orig.title ? `(${orig.title})` : '')

  let miniTree = null
  let otherTree = null
  let browser = null

  try {
    miniTree = await api('/api/tree/create', 'POST', { title: '快速对话标识测试' })
    otherTree = await api('/api/tree/create', 'POST', { title: '普通画布对照' })
    const miniRoot = miniTree.nodeList.find((n) => !n.parentId)
    await api('/api/tree/mini', 'POST', { treeId: miniTree.treeId })

    browser = await puppeteer.launch({
      executablePath: EDGE,
      headless: 'new',
      args: ['--no-sandbox', '--disable-gpu']
    })
    const page = await browser.newPage()
    await page.setViewport({ width: 1440, height: 900 })

    /** 打开主界面并切到指定画布（用 lastTreeId 决定初始画布） */
    async function open(treeId) {
      await page.goto(APP, { waitUntil: 'domcontentloaded' })
      await page.evaluate((id) => localStorage.setItem('bcc:lastTreeId', id), treeId)
      await page.reload({ waitUntil: 'networkidle2' })
      await page.waitForSelector('.chat-node', { timeout: 15000 })
      await sleep(700) // 等 refreshMiniTree 回来
    }

    // ---------- 1. 快速对话画布：应出现徽标 ----------
    await open(miniTree.treeId)
    const badges = await page.$$eval('.badge-quick', (els) => els.map((e) => e.textContent.trim()))
    if (badges.length === 1 && badges[0].includes('快速对话')) {
      ok(`快速对话节点显示徽标「${badges[0]}」`)
    } else {
      fail(`徽标数量/文案不符：${JSON.stringify(badges)}`)
    }

    const quickCards = await page.$$eval('.chat-node.is-quick', (els) => els.length)
    if (quickCards === 1) ok('卡片带 is-quick 标识（左侧绿色竖条 + 描边）')
    else fail(`is-quick 卡片数 = ${quickCards}，期望 1`)

    // 徽标只应落在根节点上
    const onRootOnly = await page.evaluate(() => {
      const card = document.querySelector('.chat-node.is-quick')
      if (!card) return false
      return !!card.querySelector('.badge-root') && !!card.querySelector('.badge-quick')
    })
    if (onRootOnly) ok('徽标与「起始」同在根节点卡片上')
    else fail('徽标未落在根节点卡片')

    // header 不溢出（徽标挤压标题时这里会 > 0）
    const overflow = await page.evaluate(() => {
      const h = document.querySelector('.chat-node.is-quick .node-header')
      return h ? h.scrollWidth - h.clientWidth : -1
    })
    if (overflow === 0) ok('header 无横向溢出')
    else fail(`header 横向溢出 ${overflow}px`)

    await page.screenshot({ path: SHOT_MINI })

    // ---------- 2. 普通画布：不应出现徽标 ----------
    await open(otherTree.treeId)
    const otherBadges = await page.$$eval('.badge-quick', (els) => els.length)
    if (otherBadges === 0) ok('普通画布上没有快速对话徽标')
    else fail(`普通画布出现 ${otherBadges} 个徽标`)
    await page.screenshot({ path: SHOT_OTHER })

    // ---------- 3. 兜底：后端 meta 丢了，本地存储还能认出来 ----------
    await api('/api/tree/mini', 'POST', { treeId: '' })
    await page.evaluate((id) => {
      localStorage.setItem('bcc:miniTreeId', id)
      localStorage.setItem('bcc:lastTreeId', id)
    }, miniTree.treeId)
    await page.reload({ waitUntil: 'networkidle2' })
    await page.waitForSelector('.chat-node', { timeout: 15000 })
    await sleep(900)
    const fallback = await page.$$eval('.badge-quick', (els) => els.length)
    if (fallback === 1) ok('meta 丢失时用 localStorage 兜底，徽标仍显示')
    else fail(`兜底失败，徽标数 = ${fallback}`)
    const rewrote = (await api('/api/tree/mini')).treeId
    if (rewrote === miniTree.treeId) ok('已把绑定回写后端 meta')
    else fail(`回写失败：meta = ${rewrote}`)

    log('截图：', SHOT_MINI)
    log('截图：', SHOT_OTHER)
  } catch (e) {
    fail(`异常：${e.message}`)
  } finally {
    if (browser) await browser.close()
    // 恢复原绑定，再清理测试画布（删除时会再次清空绑定）
    try { await api('/api/tree/mini', 'POST', { treeId: orig.treeId || '' }) } catch (e) { fail('恢复 miniTreeId 失败：' + e.message) }
    for (const t of [miniTree, otherTree]) {
      if (!t) continue
      try { await api(`/api/tree/delete?treeId=${encodeURIComponent(t.treeId)}`, 'DELETE') } catch (e) { /* ignore */ }
    }
    if (orig.treeId) {
      try { await api('/api/tree/mini', 'POST', { treeId: orig.treeId }) } catch (e) { /* ignore */ }
    }
    const after = await api('/api/tree/mini').catch(() => null)
    log('已恢复 miniTreeId =', after?.treeId || '(空)')
    console.log(failed ? `\n${failed} 项失败` : '\n全部通过')
    process.exitCode = failed ? 1 : 0
  }
})()
