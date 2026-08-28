"""按 Discord channel_id 维护模式 + 模型 + 历史。可选本地 JSON 持久化。"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Literal

log = logging.getLogger("session")

Mode = Literal["normal", "special"]


class SessionManager:
    def __init__(
        self,
        max_turns: int = 50,
        default_model: str = "deepseek-v4-flash",
        storage_path: str | os.PathLike | None = None,
    ):
        # max_turns 是「轮」，1 轮 = 1 条 user + 1 条 assistant
        self._mode: dict[int, Mode] = {}
        self._model: dict[int, str] = {}
        self._history: dict[int, list[dict]] = {}
        self._system_prompt: dict[int, str] = {}
        self._max_msgs = max_turns * 2
        self._default_model = default_model
        self._storage_path: Path | None = Path(storage_path) if storage_path else None
        if self._storage_path is not None:
            self._load()

    def get_mode(self, channel_id: int) -> Mode:
        return self._mode.get(channel_id, "normal")

    def set_mode(self, channel_id: int, mode: Mode) -> None:
        self._mode[channel_id] = mode
        self._save()

    def get_model(self, channel_id: int) -> str:
        return self._model.get(channel_id, self._default_model)

    def set_model(self, channel_id: int, model: str) -> None:
        self._model[channel_id] = model
        self._save()

    def get_system_prompt(self, channel_id: int) -> str:
        return self._system_prompt.get(channel_id, "")

    def set_system_prompt(self, channel_id: int, prompt: str) -> None:
        self._system_prompt[channel_id] = prompt
        self._save()

    def clear_system_prompt(self, channel_id: int) -> None:
        self._system_prompt.pop(channel_id, None)
        self._save()

    def get_history(self, channel_id: int) -> list[dict]:
        # 只返回 API 需要的 role/content，去掉本地用的 discord_id 等字段
        return [
            {"role": m["role"], "content": m["content"]}
            for m in self._history.get(channel_id, [])
        ]

    def append(
        self,
        channel_id: int,
        role: str,
        content: str,
        discord_id: int | None = None,
        bot_message_ids: list[int] | None = None,
    ) -> None:
        hist = self._history.setdefault(channel_id, [])
        entry: dict = {"role": role, "content": content}
        if discord_id is not None:
            entry["discord_id"] = discord_id
        if bot_message_ids:
            entry["bot_message_ids"] = list(bot_message_ids)
        hist.append(entry)
        # 简单截断，避免无限增长
        if len(hist) > self._max_msgs:
            del hist[: len(hist) - self._max_msgs]
        self._save()

    def clear(self, channel_id: int) -> None:
        self._history.pop(channel_id, None)
        self._save()

    def edit_user_message_and_truncate(
        self,
        channel_id: int,
        discord_id: int,
        new_content: str,
    ) -> tuple[bool, list[int]]:
        """根据 Discord 消息 ID 找到对应的 user 历史条目，把它的 content 改成
        new_content，并把它之后的所有历史（被抛弃的对话分支）从历史里截断。

        返回 (found, abandoned_discord_ids)：
        - found：是否找到了这条消息（False 表示历史里没有，或编辑后内容未变）
        - abandoned_discord_ids：被截断的所有消息对应的 Discord 消息 ID
          列表（包含被抛弃的 user 消息和机器人 reply 的所有分段 ID），
          调用方可以用它给这些消息加 reaction 来标识"已抛弃"。
        """
        hist = self._history.get(channel_id)
        if not hist:
            return False, []
        for idx, msg in enumerate(hist):
            if msg.get("role") != "user":
                continue
            if msg.get("discord_id") != discord_id:
                continue
            if msg.get("content") == new_content:
                # 内容没变（多半是 Discord 自动加 embed 触发的 edit 事件），不动历史
                return False, []
            abandoned: list[int] = []
            for later in hist[idx + 1:]:
                if later.get("role") == "user":
                    did = later.get("discord_id")
                    if isinstance(did, int):
                        abandoned.append(did)
                elif later.get("role") == "assistant":
                    for mid in later.get("bot_message_ids") or []:
                        if isinstance(mid, int):
                            abandoned.append(mid)
            msg["content"] = new_content
            del hist[idx + 1:]
            self._save()
            return True, abandoned
        return False, []

    # ---------- 持久化 ----------

    def _load(self) -> None:
        assert self._storage_path is not None
        if not self._storage_path.exists():
            return
        try:
            with self._storage_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            log.exception("读取历史文件失败 %s，跳过加载", self._storage_path)
            return

        for cid_str, entry in (data or {}).items():
            try:
                cid = int(cid_str)
            except ValueError:
                continue
            mode = entry.get("mode")
            if mode in ("normal", "special"):
                self._mode[cid] = mode  # type: ignore[assignment]
            model = entry.get("model")
            if isinstance(model, str) and model:
                self._model[cid] = model
            sys_prompt = entry.get("system_prompt")
            if isinstance(sys_prompt, str) and sys_prompt:
                self._system_prompt[cid] = sys_prompt
            history = entry.get("history") or []
            cleaned: list[dict] = []
            for m in history:
                if not isinstance(m, dict):
                    continue
                if m.get("role") not in ("user", "assistant", "system"):
                    continue
                if not isinstance(m.get("content"), str):
                    continue
                item: dict = {"role": m["role"], "content": m["content"]}
                did = m.get("discord_id")
                if isinstance(did, int):
                    item["discord_id"] = did
                bot_ids = m.get("bot_message_ids")
                if isinstance(bot_ids, list):
                    cleaned_bot_ids = [b for b in bot_ids if isinstance(b, int)]
                    if cleaned_bot_ids:
                        item["bot_message_ids"] = cleaned_bot_ids
                cleaned.append(item)
            if cleaned:
                self._history[cid] = cleaned[-self._max_msgs:]
        log.info("已从 %s 加载 %d 个频道历史", self._storage_path, len(self._history))

    def _save(self) -> None:
        if self._storage_path is None:
            return
        channel_ids = (
            set(self._mode) | set(self._model)
            | set(self._history) | set(self._system_prompt)
        )
        snapshot: dict[str, dict] = {}
        for cid in channel_ids:
            entry: dict = {
                "mode": self._mode.get(cid, "normal"),
                "model": self._model.get(cid, self._default_model),
                "history": self._history.get(cid, []),
            }
            sys_prompt = self._system_prompt.get(cid, "")
            if sys_prompt:
                entry["system_prompt"] = sys_prompt
            snapshot[str(cid)] = entry
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            # 原子写：先写临时文件再 rename，避免半写状态
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self._storage_path.parent),
                prefix=".chat_history.",
                suffix=".tmp",
                delete=False,
            ) as tf:
                json.dump(snapshot, tf, ensure_ascii=False, indent=2)
                tmp_name = tf.name
            os.replace(tmp_name, self._storage_path)
        except Exception:
            log.exception("写入历史文件失败 %s", self._storage_path)
