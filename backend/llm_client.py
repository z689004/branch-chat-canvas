# -*- coding: utf-8 -*-
"""大模型调用封装：兼容云端 OpenAI 兼容 API（DeepSeek / 豆包 / OpenAI 等）与本地 Ollama。

配置优先级：页面「模型与密钥管理」保存的配置（data/llm_config.json）> 环境变量 > 默认值。
环境变量（兜底）：
  LLM_PROVIDER    mock（默认，无需 Key 的演示模式）| openai | ollama
  OPENAI_BASE_URL 默认 https://api.deepseek.com（DeepSeek 兼容 OpenAI 协议）
  OPENAI_API_KEY  云端 API 密钥
  LLM_MODEL       默认 deepseek-chat
  OLLAMA_BASE_URL 默认 http://localhost:11434
  OLLAMA_MODEL    默认 qwen2.5:7b

支持多个密钥档案（profiles）：可添加多个 Key / 模型地址，随时切换当前启用的那一个。
"""
import os
import json
import time
import uuid
import asyncio
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional

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

# 多密钥档案：profiles 列表 + 当前启用的 activeId
STATE = {"profiles": [], "activeId": None}

DEFAULT_BASE = {"openai": "https://api.deepseek.com", "ollama": "http://localhost:11434"}
DEFAULT_MODEL = {"openai": "deepseek-chat", "ollama": "qwen2.5:7b"}
PROVIDER_LABEL = {"openai": "云端 API", "ollama": "本地 Ollama", "mock": "演示模式"}


# ---------------- 档案工具 ----------------

def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _stamp() -> str:
    return datetime.now().strftime("%m-%d %H:%M")


def _mask(key: str) -> str:
    if not key:
        return ""
    return key[:4] + "****" + key[-4:] if len(key) > 8 else "****"


def _normalize_profile(raw: dict) -> dict:
    provider = str(raw.get("provider") or "openai").strip().lower()
    if provider not in ("openai", "ollama"):
        provider = "openai"
    return {
        "id": str(raw.get("id") or _uid()),
        "name": str(raw.get("name") or "").strip() or "未命名密钥",
        "provider": provider,
        "baseUrl": str(raw.get("baseUrl") or DEFAULT_BASE[provider]).strip().rstrip("/"),
        "apiKey": str(raw.get("apiKey") or "").strip(),
        "model": str(raw.get("model") or DEFAULT_MODEL[provider]).strip(),
        "lastTest": raw.get("lastTest") if isinstance(raw.get("lastTest"), dict) else None,
    }


def _public_profile(p: dict) -> dict:
    """档案的对外视图：密钥只返回打码结果。"""
    return {
        "id": p["id"],
        "name": p["name"],
        "provider": p["provider"],
        "baseUrl": p["baseUrl"],
        "model": p["model"],
        "hasKey": bool(p["apiKey"]),
        "keyMasked": _mask(p["apiKey"]),
        "lastTest": p.get("lastTest"),
    }


def get_profile(pid) -> Optional[dict]:
    for p in STATE["profiles"]:
        if p["id"] == pid:
            return p
    return None


def get_active_profile() -> Optional[dict]:
    p = get_profile(STATE["activeId"])
    if p:
        return p
    return STATE["profiles"][0] if STATE["profiles"] else None


def _migrate_legacy(saved: dict) -> list:
    """把旧版「单一配置」迁移成第一个密钥档案，保证升级后不丢配置。"""
    out = []
    saved = saved or {}
    key = saved.get("openaiApiKey") or os.getenv("OPENAI_API_KEY", "")
    if key:
        base = saved.get("openaiBaseUrl") or CONFIG["openaiBaseUrl"]
        brand = "DeepSeek" if "deepseek" in base else ("OpenAI" if "openai.com" in base else "云端模型")
        out.append(_normalize_profile({
            "name": f"{brand}（原有配置）",
            "provider": "openai",
            "baseUrl": base,
            "apiKey": key,
            "model": saved.get("llmModel") or CONFIG["llmModel"],
        }))
    if CONFIG["provider"] == "ollama" or saved.get("ollamaBaseUrl"):
        out.append(_normalize_profile({
            "name": "本地 Ollama（原有配置）",
            "provider": "ollama",
            "baseUrl": saved.get("ollamaBaseUrl") or CONFIG["ollamaBaseUrl"],
            "model": saved.get("ollamaModel") or CONFIG["ollamaModel"],
        }))
    return out


def load_config_from_disk() -> None:
    """启动时加载页面保存的配置（优先于环境变量）。"""
    saved = {}
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            saved = {}
    for k in _CONFIG_KEYS:
        if saved.get(k) not in (None, ""):
            CONFIG[k] = str(saved[k]).strip()

    raw = saved.get("profiles")
    if isinstance(raw, list):
        STATE["profiles"] = [_normalize_profile(p) for p in raw if isinstance(p, dict)]
        STATE["activeId"] = saved.get("activeId")
    if not STATE["profiles"]:
        STATE["profiles"] = _migrate_legacy(saved)
        STATE["activeId"] = STATE["profiles"][0]["id"] if STATE["profiles"] else None
    if not get_profile(STATE["activeId"]):
        STATE["activeId"] = STATE["profiles"][0]["id"] if STATE["profiles"] else None
    apply_active()


def save_config_to_disk() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = dict(CONFIG)
    data["profiles"] = STATE["profiles"]
    data["activeId"] = STATE["activeId"]
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def apply_active() -> None:
    """把启用中的档案写入运行时配置（stream_chat 直接读 CONFIG）。"""
    p = get_active_profile()
    if not p:
        return
    if p["provider"] == "openai":
        CONFIG["openaiBaseUrl"] = p["baseUrl"]
        CONFIG["openaiApiKey"] = p["apiKey"]
        CONFIG["llmModel"] = p["model"]
    else:
        CONFIG["ollamaBaseUrl"] = p["baseUrl"]
        CONFIG["ollamaModel"] = p["model"]


def update_config(patch: dict) -> dict:
    """更新全局模型来源，并持久化。"""
    for k in _CONFIG_KEYS:
        if k in patch and patch[k] is not None:
            CONFIG[k] = str(patch[k]).strip()
    if CONFIG["provider"] not in ("mock", "openai", "ollama"):
        CONFIG["provider"] = "mock"
    save_config_to_disk()
    return get_public_config()


def save_profile(payload: dict) -> dict:
    """新增或更新一个密钥档案；保存后自动启用它。Key 留空表示沿用原值。"""
    p = _normalize_profile(payload or {})
    old = get_profile(p["id"])
    if old:
        if not p["apiKey"] and old.get("apiKey"):
            p["apiKey"] = old["apiKey"]
        STATE["profiles"][STATE["profiles"].index(old)] = p
    else:
        STATE["profiles"].append(p)
    STATE["activeId"] = p["id"]
    CONFIG["provider"] = p["provider"]
    apply_active()
    save_config_to_disk()
    return get_public_config()


def delete_profile(pid: str) -> dict:
    p = get_profile(pid)
    if p:
        STATE["profiles"] = [x for x in STATE["profiles"] if x["id"] != pid]
        if STATE["activeId"] == pid:
            nxt = STATE["profiles"][0] if STATE["profiles"] else None
            STATE["activeId"] = nxt["id"] if nxt else None
            CONFIG["provider"] = nxt["provider"] if nxt else "mock"
        apply_active()
        save_config_to_disk()
    return get_public_config()


def activate_profile(pid: str) -> dict:
    p = get_profile(pid)
    if p:
        STATE["activeId"] = pid
        CONFIG["provider"] = p["provider"]
        apply_active()
        save_config_to_disk()
    return get_public_config()


def get_public_config() -> dict:
    """返回给前端的配置（密钥打码）。"""
    active = get_active_profile()
    return {
        "provider": CONFIG["provider"],
        "profiles": [_public_profile(p) for p in STATE["profiles"]],
        "activeId": STATE["activeId"],
        "activeName": active["name"] if active else "",
        "hasKey": bool(active and active["apiKey"]),
        "keyMasked": _mask(active["apiKey"]) if active else "",
        "openaiBaseUrl": CONFIG["openaiBaseUrl"],
        "llmModel": CONFIG["llmModel"],
        "ollamaBaseUrl": CONFIG["ollamaBaseUrl"],
        "ollamaModel": CONFIG["ollamaModel"],
    }


# ---------------- 真实连通性测试 ----------------

async def test_profile(payload: Optional[dict] = None) -> dict:
    """真实测试一个密钥档案：验证地址可达、Key 有效、模型名可用。

    payload 传 {id} 测已保存的档案；也可直接传一份完整配置测未保存的内容。
    """
    payload = payload or {}
    if payload.get("provider") == "mock":
        return {"ok": True, "simulated": True,
                "msg": "演示模式不会发起真实请求，无需测试连接"}

    pid = payload.get("id")
    saved = get_profile(pid) if pid else None
    p = dict(saved) if saved else _normalize_profile(payload)
    if saved and payload.get("apiKey"):        # 编辑界面里刚填的新 Key
        p["apiKey"] = payload["apiKey"]
    if not p.get("apiKey") and payload.get("apiKey"):
        p["apiKey"] = payload["apiKey"]

    if p["provider"] == "ollama":
        result = await _test_ollama(p)
    else:
        result = await _test_openai(p)

    if saved:
        saved["lastTest"] = {
            "ok": bool(result.get("ok")),
            "msg": result.get("msg") or result.get("error") or "",
            "ts": _stamp(),
            "models": (result.get("models") or [])[:12],
        }
        save_config_to_disk()
    return result


async def _test_openai(p: dict) -> dict:
    base = p["baseUrl"]
    key = p["apiKey"]
    model = p["model"]
    if not key:
        return {"ok": False, "error": "未填写 API Key，无法测试"}
    headers = {"Authorization": f"Bearer {key}"}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            # ① 先用 /models 验证 Key（多数端点免费且快）
            r = None
            try:
                r = await c.get(f"{base}/models", headers=headers)
            except Exception:
                r = None
            if r is not None:
                if r.status_code in (401, 403):
                    return {"ok": False, "error": f"鉴权失败（{r.status_code}）：API Key 无效、已过期或无权限"}
                if r.status_code == 200:
                    try:
                        ids = [m.get("id") for m in (r.json().get("data") or []) if isinstance(m, dict)]
                        ids = [i for i in ids if i]
                    except Exception:
                        ids = []
                    ms = int((time.perf_counter() - t0) * 1000)
                    if ids:
                        if model not in ids:
                            return {"ok": True, "warning": True, "latency": ms, "models": ids[:30],
                                    "msg": f"Key 有效（延迟 {ms}ms，可访问 {len(ids)} 个模型）"
                                           f"，但列表里没有「{model}」，请核对模型名"}
                        return {"ok": True, "latency": ms, "models": ids[:30],
                                "msg": f"Key 有效 · 延迟 {ms}ms · 可访问 {len(ids)} 个模型 · 「{model}」可用"}
                    return {"ok": True, "latency": ms, "msg": f"Key 有效 · 延迟 {ms}ms"}

            # ② 端点不支持 /models：发一条最小对话请求（真实调用一次）
            r2 = await c.post(
                f"{base}/chat/completions",
                headers={**headers, "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": "ping"}],
                      "max_tokens": 1, "stream": False},
            )
            ms = int((time.perf_counter() - t0) * 1000)
            if r2.status_code in (401, 403):
                return {"ok": False, "error": f"鉴权失败（{r2.status_code}）：API Key 无效或无权访问该模型"}
            if r2.status_code >= 400:
                return {"ok": False, "error": f"请求失败（{r2.status_code}）：{(r2.text or '')[:200]}"}
            try:
                used = r2.json().get("model") or model
            except Exception:
                used = model
            return {"ok": True, "latency": ms, "msg": f"连接成功 · 延迟 {ms}ms · 模型 {used} 已响应"}
    except httpx.TimeoutException:
        return {"ok": False, "error": f"连接超时（20 秒）：{base} 无响应，请检查网络或地址"}
    except httpx.ConnectError:
        return {"ok": False, "error": f"无法连接 {base}：地址错误、服务不可用或网络不通"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}：{e}"}


async def _test_ollama(p: dict) -> dict:
    base = p["baseUrl"]
    model = p["model"]
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{base}/api/tags")
            if r.status_code >= 400:
                return {"ok": False, "error": f"Ollama 返回 {r.status_code}：{(r.text or '')[:150]}"}
            try:
                names = [m.get("name") for m in (r.json().get("models") or []) if isinstance(m, dict)]
                names = [n for n in names if n]
            except Exception:
                names = []
            ms = int((time.perf_counter() - t0) * 1000)
            if names and not any(n == model or n.split(":")[0] == model.split(":")[0] for n in names):
                return {"ok": True, "warning": True, "latency": ms, "models": names[:30],
                        "msg": f"Ollama 已连接（延迟 {ms}ms，本地 {len(names)} 个模型），"
                               f"但没有「{model}」，请先执行 ollama pull {model}"}
            return {"ok": True, "latency": ms, "models": names[:30],
                    "msg": f"Ollama 已连接 · 延迟 {ms}ms · 模型「{model}」"
                           + ("可用" if names else "（本地模型列表为空）")}
    except httpx.TimeoutException:
        return {"ok": False, "error": f"连接超时（10 秒）：{base} 无响应"}
    except httpx.ConnectError:
        return {"ok": False, "error": f"无法连接 {base}：Ollama 未启动或地址错误"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}：{e}"}


async def test_connection() -> dict:
    """兼容入口：测试当前启用的档案。"""
    p = get_active_profile()
    if not p:
        return {"ok": True, "simulated": True, "msg": "演示模式：未发起真实网络请求"}
    return await test_profile({"id": p["id"]})


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
        raise RuntimeError("未配置 API Key，请点击右上角「模型设置」添加密钥")
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

    return f"""> 🧪 **演示模式回答**（未启用任何密钥，返回模拟内容，完整流程与真实模型一致）

**你的问题：** {question or '（空）'}

**当前上下文片段：** {ctx_line}

### 回答结构示例

1. **概念澄清** —— 这里会先解释问题涉及的核心概念；
2. **举例说明** —— 用一个具体例子帮助理解；
3. **延伸追问** —— 你可以在本回答中**划选任意一段文字**，点击弹出按钮创建子分支，继续向下深挖。

### 如何接入真实大模型

- 打开右上角「模型设置」→ 云端 API，添加一个密钥档案（DeepSeek / 豆包 / OpenAI 等任意 OpenAI 兼容端点），点「测试」验证后启用即可。
- 本机跑 Ollama：添加一个本地档案，地址填 `http://localhost:11434`，模型填 `qwen2.5:7b`。

现在就试试：选中这段回答里的任意一句话，拉出一个子分支吧！"""


async def _stream_mock(messages: list) -> AsyncGenerator[str, None]:
    answer = _build_mock_answer(messages)
    step = 3
    for i in range(0, len(answer), step):
        yield answer[i:i + step]
        await asyncio.sleep(0.015)
