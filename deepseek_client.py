"""DeepSeek API 客户端"""
from __future__ import annotations

import logging
from typing import Literal

import httpx

log = logging.getLogger("deepseek")

Role = Literal["user", "assistant", "system"]


AVAILABLE_MODELS = ("deepseek-v4-flash", "deepseek-v4-pro")


class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 120.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = model
        # 每次请求新建 client，避免任何连接级 cache
        self.timeout = timeout

    # ---------- 普通模式：标准 multi-turn ----------
    async def chat_normal(
        self,
        history: list[dict],
        user_text: str,
        model: str | None = None,
        system_prompt: str | None = None,
    ) -> str:
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        return await self._post(messages, model=model)

    # ---------- 特殊模式 ----------
    # 把完整历史 + 当前用户消息序列化进 system prompt
    # user role 只放一个占位/触发词，强制每次都是"全新会话"
    async def chat_special(self, history: list[dict], user_text: str, model: str | None = None) -> str:
        transcript_lines: list[str] = []
        for msg in history:
            role = msg["role"].upper()
            transcript_lines.append(f"[{role}]\n{msg['content']}")
        transcript_lines.append(f"[USER]\n{user_text}")
        transcript = "\n\n".join(transcript_lines)

        system_content = (
            "You are a helpful assistant. Below is the full conversation so far, "
            "including the latest user message. Continue the conversation by "
            "producing the next [ASSISTANT] reply. Output only the reply content, "
            "no role tag, no preamble.\n\n"
            "===== CONVERSATION =====\n"
            f"{transcript}\n"
            "========================\n\n"
            "Now write the next [ASSISTANT] reply:"
        )

        messages = [
            {"role": "system", "content": system_content},
            # user role 留一个最小触发，这样请求结构合法
            {"role": "user", "content": "(continue)"},
        ]
        return await self._post(messages, model=model, disable_cache=True)

    # ---------- 底层请求 ----------
    async def _post(self, messages: list[dict], model: str | None = None, disable_cache: bool = False) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if disable_cache:
            # 双保险：DeepSeek 的 prompt cache 是自动的，但加个 no-store 表明意图
            headers["Cache-Control"] = "no-store"

        use_model = model or self.default_model
        payload = {
            "model": use_model,
            "messages": messages,
            "stream": False,
            "temperature": 0.7,
        }

        # 每次都新建 AsyncClient，杜绝连接复用带来的副作用
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            log.info(
                "→ DeepSeek: model=%s, messages=%d, special=%s",
                use_model, len(messages), disable_cache,
            )
            resp = await http.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"DeepSeek 返回结构异常: {data}") from e
        # 思考模式下偶尔 content 为空，把 reasoning_content 兜底回退
        if not content:
            content = data["choices"][0]["message"].get("reasoning_content", "") or ""
        return content.strip()
