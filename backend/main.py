# -*- coding: utf-8 -*-
"""分支对话 AI 画布 — FastAPI 后端入口（原型版）

启动：uvicorn main:app --host 0.0.0.0 --port 8000
构建后的前端（frontend/dist）由本服务静态托管，浏览器打开 http://localhost:8000 即用。
"""
import json
import os
import uuid
from datetime import datetime
from html import escape
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent


def _load_dotenv() -> None:
    """读取项目根目录 .env（零依赖实现），已存在的环境变量优先。"""
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass


_load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import llm_client
import storage
from models import (
    TreeCreateBody, TreeUpdateBody, TreeClearMessagesBody, MiniTreeBody, ChildCreateBody, NodeUpdateBody,
    SendBody, DuplicateBody, SnapshotBody, RootEnsureBody,
)

app = FastAPI(title="分支对话 AI 画布", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ROOT_TITLE_DEFAULT = "新对话"
CHILD_TITLE_DEFAULT = "新分支"


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


llm_client.load_config_from_disk()  # 启动时加载页面保存的模型配置


def get_tree_or_404(tree_id: str) -> dict:
    tree = storage.load_tree(tree_id)
    if not tree:
        raise HTTPException(status_code=404, detail="对话树不存在")
    return tree


def get_node(tree: dict, node_id: str) -> dict:
    for n in tree["nodeList"]:
        if n["nodeId"] == node_id:
            return n
    raise HTTPException(status_code=404, detail="节点不存在")


def _new_node(parent_id, title, selected_context="", context_mode="simple",
              x=0.0, y=0.0) -> dict:
    t = now()
    return {
        "nodeId": uuid.uuid4().hex,
        "parentId": parent_id,
        "title": title,
        "selectedContext": selected_context,
        "contextMode": context_mode,
        "messages": [],
        "x": x,
        "y": y,
        "isCollapsed": False,
        "starred": False,
        "createTime": t,
        "updateTime": t,
    }


def _is_default_title(title: str) -> bool:
    return title in (ROOT_TITLE_DEFAULT, CHILD_TITLE_DEFAULT, "新对话", "新分支")


def build_messages(tree: dict, node: dict, question: str) -> list:
    """根据上下文模式构造发送给大模型的消息数组。"""
    mode = node.get("contextMode", "simple")
    if mode == "full":
        # 完整模式：继承父节点全部对话历史 + 各级选中片段
        by_id = {n["nodeId"]: n for n in tree["nodeList"]}
        chain, cur = [], node
        while cur:
            chain.append(cur)
            cur = by_id.get(cur.get("parentId"))
        msgs = [{"role": "system", "content": llm_client.SYSTEM_PROMPT}]
        for anc in reversed(chain):  # 根节点在前
            if anc.get("selectedContext"):
                msgs.append({"role": "user",
                             "content": f"【关注片段】{anc['selectedContext']}"})
            msgs.extend(anc.get("messages", []))
        msgs.append({"role": "user", "content": question})
        return msgs

    # 精简模式：仅使用选中片段作为上下文
    msgs = [{"role": "system", "content": llm_client.SYSTEM_PROMPT}]
    ctx = node.get("selectedContext", "")
    if ctx:
        msgs.append({"role": "user",
                     "content": f"以下是选中的原文片段：\n「{ctx}」\n\n请基于这段内容回答我接下来的问题。"})
        msgs.append({"role": "assistant", "content": "好的，我会围绕这段内容来回答你的问题。"})
    msgs.append({"role": "user", "content": question})
    return msgs


# ---------------- 树级接口 ----------------

@app.post("/api/tree/create")
def tree_create(body: TreeCreateBody):
    t = now()
    root = _new_node(None, ROOT_TITLE_DEFAULT, x=0.0, y=0.0)
    tree = {
        "treeId": f"tree-{uuid.uuid4().hex[:12]}",
        "title": body.title or "未命名画布",
        "nodeList": [root],
        "createTime": t,
        "updateTime": t,
    }
    storage.save_tree(tree)
    return tree


@app.get("/api/tree/list")
def tree_list():
    return storage.list_trees()


@app.put("/api/tree/update")
def tree_update(body: TreeUpdateBody):
    tree = get_tree_or_404(body.treeId)
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="画布名称不能为空")
    tree["title"] = title
    tree["updateTime"] = now()
    storage.save_tree(tree)
    return {"ok": True, "title": title}


@app.get("/api/tree/get")
def tree_get(treeId: str):
    return get_tree_or_404(treeId)


@app.delete("/api/tree/delete")
def tree_delete(treeId: str):
    storage.delete_tree(treeId)
    # 被删的正好是悬浮速记绑定的画布时，解除绑定，避免悬浮球下次拿到失效 id
    if storage.get_meta("miniTreeId") == treeId:
        storage.set_meta("miniTreeId", "")
    return {"ok": True}


@app.get("/api/tree/mini")
def tree_mini_get():
    """悬浮球「悬浮速记」当前绑定的画布。

    本地存储（localStorage）在悬浮球独立窗口 / 重启后可能读不到，
    由后端记住这个 id，保证每次启动复用同一块画布，不会反复新建空白画布。
    """
    tid = storage.get_meta("miniTreeId") or ""
    if tid:
        tree = storage.load_tree(tid)
        if tree:
            return {"treeId": tid, "title": tree.get("title") or "悬浮速记"}
        storage.set_meta("miniTreeId", "")  # 画布已被删除，清理失效绑定
    return {"treeId": "", "title": ""}


@app.post("/api/tree/mini")
def tree_mini_set(body: MiniTreeBody):
    tid = (body.treeId or "").strip()
    if tid and not storage.load_tree(tid):
        raise HTTPException(status_code=404, detail="画布不存在")
    storage.set_meta("miniTreeId", tid)
    return {"ok": True, "treeId": tid}


@app.post("/api/tree/clear-messages")
def tree_clear_messages(body: TreeClearMessagesBody):
    """清空会话：删除全部分支与对话，只保留一个空白根会话（可撤销）。"""
    tree = get_tree_or_404(body.treeId)
    nodes = tree.get("nodeList", [])
    cleared = sum(len(n.get("messages") or []) for n in nodes)
    roots = [n for n in nodes if not n.get("parentId")]
    if roots:
        root = roots[0]
        root["messages"] = []
        root["selectedContext"] = ""
        root["title"] = ROOT_TITLE_DEFAULT
        root["isCollapsed"] = False
        root["starred"] = False
        root["x"], root["y"] = 0.0, 0.0
        root["size"] = {}
        root["updateTime"] = now()
        tree["nodeList"] = [root]
    else:
        t = now()
        tree["nodeList"] = [_new_node(None, ROOT_TITLE_DEFAULT, x=0.0, y=0.0)]
    tree["updateTime"] = now()
    storage.save_tree(tree)
    return {"ok": True, "cleared": cleared, "removed": len(nodes) - len(tree["nodeList"])}


# ---------------- 节点级接口 ----------------

@app.post("/api/node/create-root")
def node_create_root(body: RootEnsureBody):
    """补根节点：画布还在但会话（节点）被删光时，给画布补一张空白根会话。

    悬浮球「快速对话」以根节点为对话载体，节点没了就发不出消息，
    这里做幂等修复——已有根节点时原样返回，不重复创建。
    """
    tree = get_tree_or_404(body.treeId)
    if any(not n.get("parentId") for n in tree.get("nodeList", [])):
        return tree
    tree.setdefault("nodeList", []).append(_new_node(None, ROOT_TITLE_DEFAULT, x=0.0, y=0.0))
    tree["updateTime"] = now()
    storage.save_tree(tree)
    return tree


@app.post("/api/node/create-child")
def node_create_child(body: ChildCreateBody):
    tree = get_tree_or_404(body.treeId)
    parent = get_node(tree, body.parentId)
    # 默认位置：金字塔布局 —— 子节点落在父节点下方一层，兄弟依次向右排开
    siblings = [n for n in tree["nodeList"] if n["parentId"] == body.parentId]
    psize = parent.get("size") or {}
    card_w = psize.get("w", 340)
    card_h = psize.get("h", 380)
    y = body.y if body.y is not None else parent["y"] + card_h + 150
    if body.x is not None:
        x = body.x
    elif siblings:
        x = max(n["x"] for n in siblings) + card_w + 90
    else:
        x = parent["x"]
    child = _new_node(
        parent_id=body.parentId,
        title=body.title or CHILD_TITLE_DEFAULT,
        selected_context=body.selectedContext,
        context_mode=body.contextMode if body.contextMode in ("simple", "full") else "simple",
        x=x, y=y,
    )
    tree["nodeList"].append(child)
    tree["updateTime"] = now()
    storage.save_tree(tree)
    return child


@app.put("/api/node/update")
def node_update(body: NodeUpdateBody):
    tree = get_tree_or_404(body.treeId)
    node = get_node(tree, body.nodeId)
    if body.title is not None:
        node["title"] = body.title
    if body.isCollapsed is not None:
        node["isCollapsed"] = body.isCollapsed
    if body.contextMode in ("simple", "full"):
        node["contextMode"] = body.contextMode
    if body.x is not None:
        node["x"] = body.x
    if body.y is not None:
        node["y"] = body.y
    if body.size:
        try:
            node["size"] = {
                "w": float(body.size.get("w")),
                "h": float(body.size.get("h")),
            }
        except (TypeError, ValueError):
            pass
    if body.starred is not None:
        node["starred"] = bool(body.starred)
    node["updateTime"] = now()
    tree["updateTime"] = now()
    storage.save_tree(tree)
    return node


def _children_index(tree: dict) -> dict:
    idx = {}
    for n in tree["nodeList"]:
        pid = n.get("parentId")
        if pid:
            idx.setdefault(pid, []).append(n)
    return idx


@app.post("/api/node/duplicate")
def node_duplicate(body: DuplicateBody):
    """复制节点；withSubtree=True 时连同整条分支一起复制。"""
    tree = get_tree_or_404(body.treeId)
    node = get_node(tree, body.nodeId)
    kids_idx = _children_index(tree)

    same_level = [n for n in tree["nodeList"] if n.get("parentId") == node.get("parentId")]
    card_w = (node.get("size") or {}).get("w", 340)
    base_x = max((n.get("x", 0) for n in same_level), default=node.get("x", 0))
    dx = base_x + card_w + 90 - node.get("x", 0)     # 副本排在同层最右侧
    first = {"id": None}

    def clone(n: dict, parent_id, is_root: bool) -> dict:
        nid = uuid.uuid4().hex
        c = dict(n)
        c["nodeId"] = nid
        c["parentId"] = parent_id
        c["title"] = f"{n.get('title', '新分支')} 副本" if is_root else n.get("title", "新分支")
        c["messages"] = [dict(m) for m in n.get("messages", [])]
        c["x"] = n.get("x", 0) + dx
        c["y"] = n.get("y", 0)
        c["isCollapsed"] = False
        c["createTime"] = now()
        c["updateTime"] = now()
        tree["nodeList"].append(c)
        if is_root:
            first["id"] = nid
        if body.withSubtree:
            for k in kids_idx.get(n["nodeId"], []):
                clone(k, nid, False)
        return c

    clone(node, node.get("parentId"), True)
    tree["updateTime"] = now()
    storage.save_tree(tree)
    return {"ok": True, "nodeId": first["id"], "nodeList": tree["nodeList"]}


@app.delete("/api/node/delete")
def node_delete(treeId: str, nodeId: str):
    tree = get_tree_or_404(treeId)
    get_node(tree, nodeId)  # 校验存在
    # 递归收集子孙节点
    doomed = {nodeId}
    changed = True
    while changed:
        changed = False
        for n in tree["nodeList"]:
            if n["parentId"] in doomed and n["nodeId"] not in doomed:
                doomed.add(n["nodeId"])
                changed = True
    tree["nodeList"] = [n for n in tree["nodeList"] if n["nodeId"] not in doomed]
    tree["updateTime"] = now()
    storage.save_tree(tree)
    return {"ok": True, "deleted": len(doomed)}


@app.post("/api/node/send")
async def node_send(body: SendBody):
    tree = get_tree_or_404(body.treeId)
    node = get_node(tree, body.nodeId)
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="问题内容不能为空")

    messages = build_messages(tree, node, content)

    async def event_stream():
        answer = ""
        try:
            async for chunk in llm_client.stream_chat(messages):
                answer += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            err = f"⚠️ 大模型调用失败：{e}"
            yield f"data: {json.dumps({'type': 'error', 'message': err}, ensure_ascii=False)}\n\n"
        finally:
            # 持久化：追加本节点消息；首个问题自动生成节点标题
            fresh = get_tree_or_404(body.treeId)
            n = get_node(fresh, body.nodeId)
            n["messages"].append({"role": "user", "content": content})
            n["messages"].append({"role": "assistant", "content": answer})
            if _is_default_title(n["title"]):
                n["title"] = content[:20]
            n["updateTime"] = now()
            fresh["updateTime"] = now()
            storage.save_tree(fresh)
            yield f"data: {json.dumps({'type': 'done', 'answer': answer, 'title': n['title']}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------- 模型配置 ----------------

@app.get("/api/llm/config")
def llm_config_get():
    return llm_client.get_public_config()


@app.post("/api/llm/config")
def llm_config_update(body: dict):
    return llm_client.update_config(body or {})


@app.post("/api/llm/profile")
def llm_profile_save(body: dict):
    """新增或更新一个密钥档案（保存后自动启用）。"""
    return llm_client.save_profile(body or {})


@app.delete("/api/llm/profile/{pid}")
def llm_profile_delete(pid: str):
    return llm_client.delete_profile(pid)


@app.post("/api/llm/profile/{pid}/activate")
def llm_profile_activate(pid: str):
    return llm_client.activate_profile(pid)


@app.post("/api/llm/test")
async def llm_config_test(body: dict = None):
    """真实连通性测试：可测已保存档案（传 id），也可测未保存的表单内容。"""
    return await llm_client.test_profile(body or {})


# ---------------- 整树快照（撤销 / 重做） ----------------

@app.post("/api/tree/snapshot")
def tree_snapshot(body: SnapshotBody):
    """用前端传来的完整节点列表覆盖当前画布（撤销/重做、批量操作后一次性落库）。"""
    tree = get_tree_or_404(body.treeId)
    cleaned = []
    seen = set()
    for raw in body.nodeList or []:
        n = dict(raw)
        nid = n.get("nodeId")
        if not nid or nid in seen:
            continue
        seen.add(nid)
        n.setdefault("parentId", None)
        n.setdefault("title", "新对话")
        n.setdefault("selectedContext", "")
        n.setdefault("contextMode", "simple")
        n.setdefault("messages", [])
        n.setdefault("x", 0.0)
        n.setdefault("y", 0.0)
        n.setdefault("isCollapsed", False)
        cleaned.append(n)
    for n in cleaned:      # 父节点已不存在时提升为根节点，避免出现孤儿节点
        if n["parentId"] and n["parentId"] not in seen:
            n["parentId"] = None
    tree["nodeList"] = cleaned
    if body.title:
        tree["title"] = body.title
    tree["updateTime"] = now()
    storage.save_tree(tree)
    return tree


# ---------------- 导出 / 导入 ----------------

def _breadcrumb(node_map: dict, node: dict) -> str:
    """根 → 当前节点的路径文字。"""
    chain, cur, guard = [], node, 0
    while cur is not None and guard < 200:
        chain.append(cur["title"])
        pid = cur.get("parentId")
        cur = node_map.get(pid) if pid else None
        guard += 1
    return " → ".join(reversed(chain))


def _walk(tree: dict, parent_id, depth: int, lines: list, node_map: dict) -> None:
    kids = [n for n in tree["nodeList"] if n["parentId"] == parent_id]
    for n in kids:
        prefix = "#" * min(depth + 1, 6)
        lines.append(f"{prefix} {'🌿 ' if n['parentId'] else '🌱 '}{n['title']}")
        path = _breadcrumb(node_map, n)
        lines.append(f"`路径：{path}`")
        mode = "完整模式" if n["contextMode"] == "full" else "精简模式"
        meta = [f"上下文：{mode}"]
        if n.get("selectedContext"):
            meta.append(f"选中片段：「{n['selectedContext'][:80]}」")
        if n.get("starred"):
            meta.append("⭐ 收藏")
        lines.append("")
        lines.append(f"> *{' ｜ '.join(meta)}*")
        lines.append("")
        for m in n.get("messages", []):
            if m["role"] == "user":
                lines.append(f"**🙋 用户**")
                lines.append("")
                lines.append(m["content"])
                lines.append("")
            else:
                lines.append(f"**🤖 AI**")
                lines.append("")
                quoted = "\n".join("> " + ln if ln.strip() else ">"
                                   for ln in str(m["content"]).splitlines())
                lines.append(quoted)
                lines.append("")
        lines.append("---")
        lines.append("")
        _walk(tree, n["nodeId"], depth + 1, lines, node_map)


def _canvas_svg(tree: dict, node_map: dict) -> str:
    """按节点真实坐标生成结构图（还原画布上的空间布局）。"""
    nodes = tree["nodeList"]
    if not nodes:
        return ""

    def size(n):
        s = n.get("size") or {}
        try:
            return float(s.get("w") or 340), float(s.get("h") or 380)
        except (TypeError, ValueError):
            return 340.0, 380.0

    boxes = {}
    for n in nodes:
        w, h = size(n)
        boxes[n["nodeId"]] = (float(n.get("x") or 0), float(n.get("y") or 0), w, h)

    xs = [b[0] for b in boxes.values()] + [b[0] + b[2] for b in boxes.values()]
    ys = [b[1] for b in boxes.values()] + [b[1] + b[3] for b in boxes.values()]
    pad = 60.0
    minx, maxx = min(xs) - pad, max(xs) + pad
    miny, maxy = min(ys) - pad, max(ys) + pad
    bw, bh = max(maxx - minx, 10), max(maxy - miny, 10)

    parts = [
        f'<svg class="canvas-map" viewBox="{minx:.0f} {miny:.0f} {bw:.0f} {bh:.0f}" '
        f'preserveAspectRatio="xMidYMin meet" role="img" aria-label="画布结构图">',
        '<defs><marker id="arw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
        'markerHeight="6" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#b6bfcc"/></marker></defs>',
    ]
    # 连线：父节点底部中点 → 子节点顶部中点（贝塞尔，贴合金字塔树形）
    for n in nodes:
        pid = n.get("parentId")
        if not pid or pid not in boxes:
            continue
        px, py, pw, ph = boxes[pid]
        cx, cy, cw, ch = boxes[n["nodeId"]]
        x1, y1 = px + pw / 2, py + ph
        x2, y2 = cx + cw / 2, cy
        mid = (y1 + y2) / 2
        parts.append(
            f'<path d="M {x1:.0f} {y1:.0f} C {x1:.0f} {mid:.0f}, {x2:.0f} {mid:.0f}, {x2:.0f} {y2:.0f}" '
            f'stroke="#b6bfcc" stroke-width="2.5" fill="none" marker-end="url(#arw)" opacity="0.85"/>'
        )
    # 节点卡片
    for n in nodes:
        x, y, w, h = boxes[n["nodeId"]]
        is_root = not n.get("parentId")
        color = "#00b42a" if is_root else "#3370ff"
        title = str(n.get("title") or "未命名")
        limit = max(6, int((w - 34) / 15))
        label = title if len(title) <= limit else title[: limit - 1] + "…"
        parts.append(
            f'<g><rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="12" '
            f'fill="#ffffff" stroke="#dde2ea" stroke-width="1.5"/>'
            f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{min(h, 8):.0f}" rx="4" fill="{color}" opacity="0.9"/>'
            f'<text x="{x + 18:.0f}" y="{y + 42:.0f}" font-size="16" font-weight="600" fill="#1f2329">{escape(label)}</text>'
            f'<text x="{x + 18:.0f}" y="{y + 70:.0f}" font-size="12" fill="#8a94a6">'
            f'{"起始节点" if is_root else "分支节点"}</text></g>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _md_outline(tree: dict) -> list:
    """Markdown 里的结构概览（用缩进列表呈现层级）。"""
    lines = []

    def emit(parent, depth):
        for n in tree["nodeList"]:
            if n["parentId"] != parent:
                continue
            lines.append(f"{'  ' * depth}- {n['title']}")
            emit(n["nodeId"], depth + 1)

    emit(None, 0)
    return lines


_HTML_TPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --ink:#1f2329; --dim:#6b7280; --line:#e5e7eb; --root:#00b42a; --branch:#3370ff; --bg:#f7f8fa; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:40px 20px 80px; background:var(--bg); color:var(--ink);
        font:15px/1.75 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }}
  .wrap {{ max-width:900px; margin:0 auto; }}
  header {{ margin-bottom:28px; }}
  h1 {{ font-size:26px; margin:0 0 10px; letter-spacing:.2px; }}
  .meta {{ color:var(--dim); font-size:13px; }}
  .node {{ background:#fff; border:1px solid var(--line); border-left:4px solid var(--branch);
          border-radius:10px; padding:16px 18px; margin:0 0 14px; box-shadow:0 1px 2px rgba(16,24,40,.04); }}
  .node.root {{ border-left-color:var(--root); }}
  .node-head {{ display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; margin-bottom:10px; }}
  .badge {{ font-size:11px; padding:1px 7px; border-radius:20px; background:#eef2ff; color:var(--branch); }}
  .badge.root {{ background:#e8f7ee; color:var(--root); }}
  .node-title {{ font-weight:600; font-size:16px; }}
  .path {{ color:var(--dim); font-size:12px; width:100%; }}
  .ctx {{ color:var(--dim); font-size:12px; margin:0 0 10px; }}
  .msg {{ margin:0 0 12px; }}
  .who {{ font-size:12px; font-weight:600; color:var(--dim); margin-bottom:4px; }}
  .bubble {{ white-space:pre-wrap; word-break:break-word; padding:10px 13px; border-radius:8px; background:#f5f6f8; }}
  .ai .bubble {{ background:#f7fbff; border:1px solid #e8f0ff; }}
  footer {{ text-align:center; color:var(--dim); font-size:12px; margin-top:36px; }}
  .map-wrap {{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:18px 18px 10px; margin:0 0 26px; }}
  .map-title {{ font-size:13px; color:var(--dim); margin:0 0 10px; }}
  svg.canvas-map {{ width:100%; height:auto; max-height:640px; display:block; }}
  .sec-title {{ font-size:13px; color:var(--dim); letter-spacing:.5px; margin:28px 0 14px; }}
  @media print {{
    body {{ background:#fff; padding:0; }}
    .node {{ break-inside:avoid; box-shadow:none; }}
    .node, .bubble {{ border-color:#ddd; }}
  }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>{title}</h1>
  <div class="meta">{meta}</div>
</header>
{map}
<div class="sec-title">对话内容</div>
{body}
<footer>由「分支对话画布」导出 · {exported_at}</footer>
</div>
</body>
</html>
"""


@app.get("/api/tree/export")
def tree_export(treeId: str, format: str = "markdown"):
    tree = get_tree_or_404(treeId)
    node_map = {n["nodeId"]: n for n in tree["nodeList"]}

    if format == "json":
        return JSONResponse(
            content=tree,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=tree.json"},
        )

    if format == "mermaid":
        # mindmap 更贴合金字塔树形；节点标题做转义，去掉会破坏语法的字符
        lines = ["mindmap"]
        roots = [n for n in tree["nodeList"] if not n["parentId"]]

        def _label(t: str) -> str:
            return str(t).replace("\n", " ").replace("(", "（").replace(")", "）") \
                .replace("[", "【").replace("]", "】").replace(":", "：")[:40]

        def emit(n, depth):
            indent = "  " * depth
            lines.append(f"{indent}{_label(n['title'])}")
            for k in tree["nodeList"]:
                if k["parentId"] == n["nodeId"]:
                    emit(k, depth + 1)

        for r in roots:
            emit(r, 1)
        text = "\n".join(lines)
        return PlainTextResponse(
            text,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=tree.mmd"},
        )

    if format == "html":
        stamp = now()
        parts = []

        def emit_html(parent_id):
            for n in tree["nodeList"]:
                if n["parentId"] != parent_id:
                    continue
                is_root = not n["parentId"]
                mode = "完整模式" if n["contextMode"] == "full" else "精简模式"
                bits = [f"上下文：{mode}"]
                if n.get("starred"):
                    bits.append("⭐ 收藏")
                if n.get("selectedContext"):
                    bits.append(f"选中片段：「{escape(n['selectedContext'][:80])}」")
                parts.append('<section class="node%s">' % (" root" if is_root else ""))
                parts.append('<div class="node-head">')
                parts.append('<span class="badge%s">%s</span>'
                             % (" root" if is_root else "", "起始" if is_root else "分支"))
                parts.append('<span class="node-title">%s</span>' % escape(n["title"]))
                parts.append('<span class="path">%s</span>' % escape(_breadcrumb(node_map, n)))
                parts.append("</div>")
                parts.append('<p class="ctx">%s</p>' % escape(" ｜ ".join(bits)))
                for m in n.get("messages", []):
                    is_user = m["role"] == "user"
                    parts.append('<div class="msg%s">' % ("" if is_user else " ai"))
                    parts.append('<div class="who">%s</div>' % ("🙋 用户" if is_user else "🤖 AI"))
                    parts.append('<div class="bubble">%s</div>' % escape(str(m["content"])))
                    parts.append("</div>")
                parts.append("</section>")
                emit_html(n["nodeId"])

        emit_html(None)
        svg = _canvas_svg(tree, node_map)
        map_html = (f'<section class="map-wrap"><p class="map-title">画布结构 · {len(tree["nodeList"])} 个节点</p>'
                    f"{svg}</section>") if svg else ""
        html_doc = _HTML_TPL.format(
            title=escape(tree["title"]),
            meta=escape(f"分支对话树 ｜ 共 {len(tree['nodeList'])} 个节点 ｜ 导出时间 {stamp}"),
            map=map_html,
            body="\n".join(parts),
            exported_at=escape(stamp),
        )
        return PlainTextResponse(
            html_doc,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=tree.html"},
        )

    # 默认 Markdown：元信息 + 结构概览 + 分支路径 + AI 回答引用块
    lines = [
        f"# {tree['title']}",
        "",
        f"> 分支对话树 ｜ 共 {len(tree['nodeList'])} 个节点 ｜ 导出时间 {now()}",
        "",
        "## 结构概览",
        "",
        *_md_outline(tree),
        "",
        "---",
        "",
    ]
    _walk(tree, None, 1, lines, node_map)
    return PlainTextResponse(
        "\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=tree.md"},
    )


@app.post("/api/tree/import")
def tree_import(body: dict):
    """导入 JSON 备份为新画布（不覆盖现有数据，节点 id 全部重新分配）。"""
    src = body.get("tree") if isinstance(body.get("tree"), dict) else body
    if not isinstance(src, dict):
        raise HTTPException(status_code=400, detail="备份文件格式不正确：不是有效的 JSON 对象")
    nodes = src.get("nodeList")
    if not isinstance(nodes, list) or not nodes:
        raise HTTPException(status_code=400, detail="备份文件格式不正确：缺少 nodeList")

    raw_ids = []
    for n in nodes:
        if not isinstance(n, dict) or not n.get("nodeId"):
            raise HTTPException(status_code=400, detail="备份文件格式不正确：节点缺少 nodeId")
        raw_ids.append(n["nodeId"])

    t = now()
    idmap = {old: f"n-{uuid.uuid4().hex[:12]}" for old in raw_ids}
    new_nodes = []
    seen = set()
    for n in nodes:
        old = n["nodeId"]
        nid = idmap[old]
        if nid in seen:
            continue  # 重复节点跳过
        seen.add(nid)
        parent = n.get("parentId")
        parent_new = idmap.get(parent) if parent else None
        if parent and not parent_new:
            parent_new = None  # 父节点缺失时挂到根层，避免断链
        msgs = []
        for m in n.get("messages") or []:
            if isinstance(m, dict) and m.get("role") in ("user", "assistant"):
                msgs.append({"role": m["role"], "content": str(m.get("content") or "")})
        node = {
            "nodeId": nid,
            "parentId": parent_new,
            "title": str(n.get("title") or "未命名节点")[:60],
            "selectedContext": str(n.get("selectedContext") or "")[:4000],
            "contextMode": "full" if n.get("contextMode") == "full" else "simple",
            "messages": msgs,
            "x": float(n.get("x") or 0),
            "y": float(n.get("y") or 0),
            "isCollapsed": bool(n.get("isCollapsed")),
            "starred": bool(n.get("starred")),
            "createTime": n.get("createTime") or t,
            "updateTime": t,
        }
        if isinstance(n.get("size"), dict):
            try:
                node["size"] = {"w": float(n["size"]["w"]), "h": float(n["size"]["h"])}
            except (KeyError, TypeError, ValueError):
                pass
        new_nodes.append(node)

    title = str(src.get("title") or "导入的画布").strip() or "导入的画布"
    if not title.endswith("（导入）"):
        title = f"{title}（导入）"
    tree = {
        "treeId": f"tree-{uuid.uuid4().hex[:12]}",
        "title": title[:60],
        "nodeList": new_nodes,
        "createTime": t,
        "updateTime": t,
    }
    storage.save_tree(tree)
    return tree


# ---------------- 静态托管前端构建产物 ----------------
# 候选顺序：环境变量 BCC_STATIC_DIR（桌面版指向打包内的资源）> public > dist
_static_candidates = []
if os.getenv("BCC_STATIC_DIR"):
    _static_candidates.append(Path(os.environ["BCC_STATIC_DIR"]))
_static_candidates += [ROOT_DIR / "frontend" / "public", ROOT_DIR / "frontend" / "dist"]
for cand in _static_candidates:
    if cand.exists() and (cand / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(cand), html=True), name="static")
        break


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
