# -*- coding: utf-8 -*-
"""存储层：每棵对话树一个 JSON 文件，持久化到 data/ 目录。

数据目录优先级：环境变量 BCC_DATA_DIR > backend/data（桌面版由启动器指向 exe 同级 data）
"""
import json
import os
import threading
from pathlib import Path

DATA_DIR = Path(os.getenv("BCC_DATA_DIR") or (Path(__file__).parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.RLock()


def _tree_path(tree_id: str) -> Path:
    # 防路径穿越
    safe = "".join(c for c in tree_id if c.isalnum() or c in "-_")
    return DATA_DIR / f"{safe}.json"


def save_tree(tree: dict) -> None:
    with _lock:
        _tree_path(tree["treeId"]).write_text(
            json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def load_tree(tree_id: str):
    p = _tree_path(tree_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def delete_tree(tree_id: str) -> None:
    p = _tree_path(tree_id)
    with _lock:
        if p.exists():
            p.unlink()


# ---------- 轻量元数据（不参与画布列表） ----------
_META_PATH = DATA_DIR / "_meta.json"


def get_meta(key: str, default=None):
    try:
        data = json.loads(_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return default
    return data.get(key, default)


def set_meta(key: str, value) -> None:
    with _lock:
        try:
            data = json.loads(_META_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        data[key] = value
        _META_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_trees() -> list:
    """列出全部对话树。

    注意：data/ 目录里同时存放 desktop.json、llm_config.json 等配置文件，
    以前直接 glob *.json 会把它们误当成画布（treeId 为空、节点数 0），
    在列表里显示成点不开的「未命名画布 (0)」。这里只认 tree-*.json，
    并且校验 treeId 与文件名一致，杜绝脏数据混进列表。
    """
    trees = []
    for p in DATA_DIR.glob("tree-*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        tree_id = data.get("treeId")
        if not isinstance(tree_id, str) or not tree_id or tree_id != p.stem:
            continue
        if not isinstance(data.get("nodeList"), list):
            continue
        trees.append({
            "treeId": tree_id,
            "title": data.get("title") or "未命名画布",
            "nodeCount": len(data.get("nodeList") or []),
            "updateTime": data.get("updateTime", ""),
        })
    trees.sort(key=lambda t: t.get("updateTime") or "", reverse=True)
    return trees
