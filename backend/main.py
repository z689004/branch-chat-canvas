# -*- coding: utf-8 -*-
"""分支对话 AI 画布 — FastAPI 后端入口（原型版）

启动：uvicorn main:app --host 0.0.0.0 --port 8000
构建后的前端（frontend/dist）由本服务静态托管，浏览器打开 http://localhost:8000 即用。
"""
import json
import os
import uuid
from datetime import datetime
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
    TreeCreateBody, TreeUpdateBody, ChildCreateBody, NodeUpdateBody, SendBody,
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
    return {"ok": True}


# ---------------- 节点级接口 ----------------

@app.post("/api/node/create-child")
def node_create_child(body: ChildCreateBody):
    tree = get_tree_or_404(body.treeId)
    parent = get_node(tree, body.parentId)
    # 默认位置：父节点右侧，按兄弟序号纵向排开
    siblings = [n for n in tree["nodeList"] if n["parentId"] == body.parentId]
    idx = len(siblings)
    x = body.x if body.x is not None else parent["x"] + 460
    y = body.y if body.y is not None else parent["y"] + idx * 280 - (idx > 0 and 140 or 0)
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
    node["updateTime"] = now()
    tree["updateTime"] = now()
    storage.save_tree(tree)
    return node


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


@app.post("/api/llm/test")
async def llm_config_test():
    return await llm_client.test_connection()


# ---------------- 导出 ----------------

def _walk(tree: dict, parent_id, depth: int, lines: list) -> None:
    kids = [n for n in tree["nodeList"] if n["parentId"] == parent_id]
    for n in kids:
        prefix = "#" * min(depth + 1, 6)
        lines.append(f"{prefix} {'🌿 ' if n['parentId'] else '🌱 '}{n['title']}")
        mode = "完整模式" if n["contextMode"] == "full" else "精简模式"
        meta = [f"上下文：{mode}"]
        if n.get("selectedContext"):
            meta.append(f"选中片段：「{n['selectedContext'][:80]}」")
        lines.append(f"> {' ｜ '.join(meta)}")
        for m in n.get("messages", []):
            who = "**🙋 用户**" if m["role"] == "user" else "**🤖 AI**"
            lines.append(f"{who}：{m['content']}\n")
        lines.append("")
        _walk(tree, n["nodeId"], depth + 1, lines)


@app.get("/api/tree/export")
def tree_export(treeId: str, format: str = "markdown"):
    tree = get_tree_or_404(treeId)

    if format == "json":
        return JSONResponse(
            content=tree,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=tree.json"},
        )

    if format == "mermaid":
        lines = ["graph TD"]
        idmap = {}
        for i, n in enumerate(tree["nodeList"]):
            nid = f"n{i}"
            idmap[n["nodeId"]] = nid
            safe = n["title"].replace('"', "'")
            lines.append(f'    {nid}["{safe}"]')
        for n in tree["nodeList"]:
            if n["parentId"] and n["parentId"] in idmap:
                lines.append(f"    {idmap[n['parentId']]} --> {idmap[n['nodeId']]}")
        text = "\n".join(lines)
        return PlainTextResponse(
            text,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=tree.mmd"},
        )

    # 默认 Markdown
    lines = [f"# {tree['title']}（分支对话树）", ""]
    _walk(tree, None, 1, lines)
    return PlainTextResponse(
        "\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=tree.md"},
    )


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
