# -*- coding: utf-8 -*-
"""大模型调用封装：兼容云端 OpenAI 兼容 API（DeepSeek / 豆包 / OpenAI 等）与本地 Ollama。

配置优先级：页面「模型设置」保存的配置（data/llm_config.json）> 环境变量 > 默认值。
环境变量（兜底）：
  LLM_PROVIDER    mock（默认，无需 Key 的演示模式）| openai | ollama
  OPENAI_BASE_URL 默认 https://api.deepseek.com（DeepSeek 兼容 OpenAI 协议）
  OPENAI_API_KEY  云端 API 密钥
  LLM_MODEL       默认 deepseek-chat
  OLLAMA_BASE_URL 默认 http://localhost:11434
  OLLAMA_MODEL    默认 qwen2.5:7b
"""
import os
import json
import asyncio
from pathlib import Path
from typing import AsyncGenerator

import httpx

CONFIG = {
    "provider": os.getenv("LLM_PROVIDER", "mock").strip().lower(),
    "openaiBaseUrl": os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com").rstrip("/"),
    "openaiApiKey": os.getenv("OPENAI_API_KEY", ""),
    "llmModel": os.getenv("LLM_MODEL", "deepseek-chat"),
    "ollamaBaseUrl": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
    "ollamaModel": os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
}

CONFIG_PATH = Path(os.getenv("BCC_DATA_DIR") or (Path(__file__).parent / "data")) / "llm_config.json"
_CONFIG_KEYS = ("provider", "openaiBaseUrl", "openaiApiKey", "llmModel",
                "ollamaBaseUrl", "ollamaModel")


def load_config_from_disk() -> None:
    """启动时加载页面保存的配置（优先于环境变量）。"""
    if not CONFIG_PATH.exists():
        return
    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        for k in _CONFIG_KEYS:
            if saved.get(k) not in (None, ""):
                CONFIG[k] = str(saved[k]).strip()
    except Exception:
        pass


def save_config_to_disk() -> None:
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def update_config(patch: dict) -> dict:
    """更新运行时配置并持久化。值为空字符串表示清除该配置。"""
    for k in _CONFIG_KEYS:
        if k in patch and patch[k] is not None:
            CONFIG[k] = str(patch[k]).strip()
    if CONFIG["provider"] not in ("mock", "openai", "ollama"):
        CONFIG["provider"] = "mock"
    save_config_to_disk()
    return get_public_config()


def get_public_config() -> dict:
    """返回给前端的配置（密钥打码）。"""
    key = CONFIG["openaiApiKey"]
    if key:
        key_masked = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
    else:
        key_masked = ""
    return {
        "provider": CONFIG["provider"],
        "openaiBaseUrl": CONFIG["openaiBaseUrl"],
        "llmModel": CONFIG["llmModel"],
        "ollamaBaseUrl": CONFIG["ollamaBaseUrl"],
        "ollamaModel": CONFIG["ollamaModel"],
        "hasKey": bool(key),
        "keyMasked": key_masked,
    }


async def test_connection() -> dict:
    """用当前配置发一条测试消息，验证连通性。"""
    try:
        sample = ""
        async for chunk in stream_chat([{"role": "user", "content": "请只回复两个字：成功"}]):
            sample += chunk
            if len(sample) > 30:
                break
        return {"ok": True, "sample": sample[:60]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}

SYSTEM_PROMPT = (
    "你是「分支对话画布」中的 AI 助手。用户在无限画布上围绕某个主题以树状分支的方式与你讨论，"
    "子分支往往基于从父级回答中划选的一段文字进行追问。"
    "请用简体中文、结构清晰的 Markdown 回答，紧扣用户给出的上下文，简洁、准确、有深度。"
)


async def stream_chat(messages: list) -> AsyncGenerator[str, None]:
    """统一入口：根据配置选择后端，逐段 yield 文本片段。"""
    provider = CONFIG["provider"]
    if provider == "openai":
        async for chunk in _stream_openai(messages):
            yield chunk
    elif provider == "ollama":
        async for chunk in _stream_ollama(messages):
            yield chunk
    else:
        async for chunk in _stream_mock(messages):
            yield chunk


async def _stream_openai(messages: list) -> AsyncGenerator[str, None]:
    base = CONFIG["openaiBaseUrl"]
    key = CONFIG["openaiApiKey"]
    model = CONFIG["llmModel"]
    if not key:
        raise RuntimeError("未配置 API Key，请点击右上角「模型设置」填入密钥")
    payload = {"model": model, "messages": messages, "stream": True}
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST", f"{base}/chat/completions", json=payload, headers=headers
        ) as resp:
            if resp.status_code in (401, 403):
                raise RuntimeError(f"鉴权失败({resp.status_code})，请检查 API Key 是否正确")
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    delta = json.loads(data)["choices"][0]["delta"].get("content")
                except Exception:
                    continue
                if delta:
                    yield delta


async def _stream_ollama(messages: list) -> AsyncGenerator[str, None]:
    payload = {"model": CONFIG["ollamaModel"], "messages": messages, "stream": True}
    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST", f"{CONFIG['ollamaBaseUrl']}/api/chat", json=payload
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                content = data.get("message", {}).get("content", "")
                if content:
                    yield content
                if data.get("done"):
                    return


# ---------------- Mock 模式（无需任何 Key，验证交互用） ----------------

def _build_mock_answer(messages: list) -> str:
    question, context = "", ""
    for m in messages:
        if m.get("role") != "user":
            continue
        c = m.get("content", "")
        if c.startswith("【关注片段】") or c.startswith("以下是选中的原文片段"):
            context = c
        else:
            question = c
    ctx_line = context.replace("\n", " ")[:120] if context else "（本节点无选中片段）"

    return f"""> 🧪 **演示模式回答**（未配置大模型 API，返回模拟内容，完整流程与真实模型一致）

**你的问题：** {question or '（空）'}

**当前上下文片段：** {ctx_line}

### 回答结构示例

1. **概念澄清** —— 这里会先解释问题涉及的核心概念；
2. **举例说明** —— 用一个具体例子帮助理解；
3. **延伸追问** —— 你可以在本回答中**划选任意一段文字**，点击弹出按钮创建子分支，继续向下深挖。

### 如何接入真实大模型

- 云端 API（DeepSeek / OpenAI / 豆包等）：

```bash
set LLM_PROVIDER=openai
set OPENAI_API_KEY=你的密钥
set OPENAI_BASE_URL=https://api.deepseek.com
set LLM_MODEL=deepseek-chat
```

- 本地 Ollama：

```bash
set LLM_PROVIDER=ollama
set OLLAMA_MODEL=qwen2.5:7b
```

配置后重启后端即可生效。现在就试试：选中这段回答里的任意一句话，拉出一个子分支吧！"""


async def _stream_mock(messages: list) -> AsyncGenerator[str, None]:
    answer = _build_mock_answer(messages)
    step = 3
    for i in range(0, len(answer), step):
        yield answer[i:i + step]
        await asyncio.sleep(0.015)
