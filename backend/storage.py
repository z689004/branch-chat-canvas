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


def list_trees() -> list:
    trees = []
    for p in DATA_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            trees.append({
                "treeId": data.get("treeId"),
                "title": data.get("title", "未命名画布"),
                "nodeCount": len(data.get("nodeList", [])),
                "updateTime": data.get("updateTime", ""),
            })
        except Exception:
            continue
    trees.sort(key=lambda t: t.get("updateTime") or "", reverse=True)
    return trees
