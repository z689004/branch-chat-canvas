# -*- coding: utf-8 -*-
"""数据模型：对话树节点、对话树。与前端字段保持 camelCase 一致。"""
from typing import Optional, List
from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str  # user | assistant
    content: str


class TreeNode(BaseModel):
    nodeId: str
    parentId: Optional[str] = None
    title: str = "新对话"
    selectedContext: str = ""          # 从父节点划选的文本片段（子分支基准上下文）
    contextMode: str = "simple"        # simple 精简 / full 完整
    messages: List[Message] = Field(default_factory=list)
    x: float = 0.0                     # 画布坐标（拖拽只改坐标，不改树形结构）
    y: float = 0.0
    isCollapsed: bool = False
    createTime: str = ""
    updateTime: str = ""


class Tree(BaseModel):
    treeId: str
    title: str = "未命名画布"
    nodeList: List[TreeNode] = Field(default_factory=list)
    createTime: str = ""
    updateTime: str = ""


# ---------- 请求体 ----------

class TreeCreateBody(BaseModel):
    title: Optional[str] = None


class TreeUpdateBody(BaseModel):
    treeId: str
    title: str


class TreeClearMessagesBody(BaseModel):
    treeId: str


class MiniTreeBody(BaseModel):
    """悬浮球「悬浮速记」画布绑定：treeId 传空字符串表示解除绑定"""
    treeId: str = ""


class ChildCreateBody(BaseModel):
    treeId: str
    parentId: str
    selectedContext: str = ""
    contextMode: str = "simple"
    title: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None


class NodeUpdateBody(BaseModel):
    treeId: str
    nodeId: str
    title: Optional[str] = None
    isCollapsed: Optional[bool] = None
    contextMode: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    # 卡片尺寸：{"w": 宽度, "h": 高度}，由前端拖拽调整后保存
    size: Optional[dict] = None
    # 收藏标记（用于节点状态徽标）
    starred: Optional[bool] = None


class SendBody(BaseModel):
    treeId: str
    nodeId: str
    content: str


class DuplicateBody(BaseModel):
    treeId: str
    nodeId: str
    withSubtree: bool = False      # True = 连同整条分支一起复制


class SnapshotBody(BaseModel):
    """整树快照写入：供前端撤销 / 重做一次性还原结构与内容。"""
    treeId: str
    title: Optional[str] = None
    nodeList: List[dict] = Field(default_factory=list)


class DeleteBody(BaseModel):
    treeId: str
    nodeId: str
