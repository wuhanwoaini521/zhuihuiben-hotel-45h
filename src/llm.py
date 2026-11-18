"""模型调用层：只用标准库，接口同构（OpenAI 兼容）。

设计意图：**同一个 prompt、同一份代码，既能跑百炼，也能跑本地模型。**

- 生产/参赛用的是阿里云百炼（DashScope 兼容模式）
- 本地留一条 Ollama 通道，纯粹为了"不花 token 也能验证 prompt 是否成立"

切到百炼只需一个环境变量：

    export DASHSCOPE_API_KEY=sk-xxx
    python -m src.agent_parse --provider bailian --package-keyword 自助晚餐

默认走本地 Ollama（http://127.0.0.1:11434/v1），不需要任何 Key。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

PRESETS: dict[str, dict[str, str]] = {
    # 阿里云百炼（DashScope OpenAI 兼容模式），比赛要求的运行时链路
    "bailian": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "key_env": "DASHSCOPE_API_KEY",
    },
    # 本地 Ollama：仅用于离线验证 prompt，不参与参赛交付
    "ollama": {
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen3.5:4b-hub",
        "key_env": "",
    },
}


class LLMError(RuntimeError):
    pass


def resolve(provider: str = "ollama", model: str | None = None) -> dict[str, str]:
    preset = PRESETS.get(provider)
    if not preset:
        raise LLMError(f"未知 provider：{provider}（可选 {', '.join(PRESETS)}）")
    key = ""
    if preset["key_env"]:
        key = os.environ.get(preset["key_env"], "")
        if not key:
            raise LLMError(
                f"provider={provider} 需要环境变量 {preset['key_env']}，当前未设置。"
                f"没有凭据时用 --provider ollama 做本地验证。"
            )
    return {
        "provider": provider,
        "base_url": os.environ.get("LLM_BASE_URL", preset["base_url"]).rstrip("/"),
        "model": model or os.environ.get("LLM_MODEL", preset["model"]),
        "api_key": key or "ollama",
    }


def chat(messages: list[dict[str, str]], *, provider: str = "ollama",
         model: str | None = None, temperature: float = 0.0,
         timeout: int = 300, json_mode: bool = False) -> str:
    """一次对话调用，返回纯文本。"""
    cfg = resolve(provider, model)
    payload: dict[str, Any] = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    req = urllib.request.Request(
        f"{cfg['base_url']}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:400]
        raise LLMError(f"{cfg['provider']} HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMError(
            f"连不上 {cfg['base_url']}（{getattr(exc, 'reason', exc)}）。"
            f"本地需先启动 ollama serve 并确认模型已加载，或改用 --provider bailian。"
        ) from exc

    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"返回结构异常：{str(body)[:300]}") from exc


def extract_json(text: str) -> dict[str, Any]:
    """从模型输出里抠出第一个完整 JSON 对象（容忍 ```json 围栏与前后废话）。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.lstrip().lower().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
    start = cleaned.find("{")
    if start == -1:
        raise LLMError(f"模型输出里没有 JSON：{text[:200]}")

    depth, in_str, esc = 0, False, False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start:i + 1])
    raise LLMError(f"JSON 不完整：{text[:200]}")
