"""
DeepSeek Discord Bot
普通模式：标准 multi-turn 对话
特殊模式：所有上下文塞进 system prompt，user role 只放当前消息，无 cache 无记忆
"""
import os
import logging
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from deepseek_client import AVAILABLE_MODELS, DeepSeekClient
from session import SessionManager

# 读取项目根目录的 .env
load_dotenv(Path(__file__).parent / ".env")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
HISTORY_PATH = os.getenv(
    "HISTORY_PATH",
    str(Path(__file__).parent / "chat_history.json"),
)

if not DISCORD_TOKEN:
    raise RuntimeError("缺少 DISCORD_TOKEN，请在 .env 中设置")
if not DEEPSEEK_API_KEY:
    raise RuntimeError("缺少 DEEPSEEK_API_KEY，请在 .env 中设置")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

client = DeepSeekClient(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
    model=DEEPSEEK_MODEL,
)
sessions = SessionManager(default_model=DEEPSEEK_MODEL, storage_path=HISTORY_PATH)


@bot.event
async def on_ready():
    log.info(f"已登录为 {bot.user}（id={bot.user.id}）")
    try:
        synced = await bot.tree.sync()
        log.info(f"同步了 {len(synced)} 个斜杠命令")
    except Exception as e:
        log.exception(f"同步斜杠命令失败: {e}")


# ---------- 模式切换 ----------

@bot.tree.command(name="special", description="进入特殊模式（无记忆、无 cache、上下文全部走 system prompt）")
async def special_cmd(interaction: discord.Interaction):
    sessions.set_mode(interaction.channel_id, "special")
    sessions.clear(interaction.channel_id)
    await interaction.response.send_message(
        "✨ 已进入**特殊模式**\n"
        "- 所有历史对话会作为 system prompt 重新发送\n"
        "- 不使用 API 端的 cache，不保留服务端记忆\n"
        "- 使用 `/normal` 退出，`/reset` 清空当前会话历史"
    )


@bot.tree.command(name="normal", description="切回普通模式")
async def normal_cmd(interaction: discord.Interaction):
    sessions.set_mode(interaction.channel_id, "normal")
    sessions.clear(interaction.channel_id)
    await interaction.response.send_message("已切回**普通模式**，会话已清空。")


@bot.tree.command(name="reset", description="清空当前频道的会话历史")
async def reset_cmd(interaction: discord.Interaction):
    sessions.clear(interaction.channel_id)
    mode = sessions.get_mode(interaction.channel_id)
    await interaction.response.send_message(f"会话已清空。当前模式：**{mode}**")


@bot.tree.command(name="status", description="查看当前频道模式、模型与历史长度")
async def status_cmd(interaction: discord.Interaction):
    mode = sessions.get_mode(interaction.channel_id)
    model = sessions.get_model(interaction.channel_id)
    history = sessions.get_history(interaction.channel_id)
    sys_prompt = sessions.get_system_prompt(interaction.channel_id)
    sys_state = "已设置" if sys_prompt else "未设置"
    await interaction.response.send_message(
        f"模式：**{mode}**｜模型：**{model}**｜历史轮数：{len(history) // 2}"
        f"｜system prompt（仅普通模式生效）：**{sys_state}**"
    )


# ---------- 自定义 system prompt（仅普通模式生效）----------

@bot.tree.command(
    name="system",
    description="设置当前频道的 system prompt（仅普通模式生效，不清空历史）",
)
@discord.app_commands.describe(prompt="system prompt 内容")
async def system_cmd(interaction: discord.Interaction, prompt: str):
    sessions.set_system_prompt(interaction.channel_id, prompt)
    preview = prompt if len(prompt) <= 200 else prompt[:200] + "…"
    await interaction.response.send_message(
        f"已设置当前频道的 **system prompt**（仅普通模式生效）：\n```\n{preview}\n```",
        ephemeral=True,
    )


@bot.tree.command(name="system_show", description="查看当前频道的 system prompt")
async def system_show_cmd(interaction: discord.Interaction):
    prompt = sessions.get_system_prompt(interaction.channel_id)
    if not prompt:
        await interaction.response.send_message(
            "当前频道未设置 system prompt。", ephemeral=True
        )
        return
    if len(prompt) <= 1900:
        body = f"```\n{prompt}\n```"
    else:
        body = f"```\n{prompt[:1900]}…\n```\n（已截断显示）"
    await interaction.response.send_message(
        f"当前频道的 system prompt（仅普通模式生效）：\n{body}", ephemeral=True
    )


@bot.tree.command(name="system_clear", description="清空当前频道的 system prompt")
async def system_clear_cmd(interaction: discord.Interaction):
    sessions.clear_system_prompt(interaction.channel_id)
    await interaction.response.send_message("已清空当前频道的 system prompt。")


# ---------- 模型切换 ----------

@bot.tree.command(name="model", description="切换当前频道使用的 DeepSeek 模型（不清空历史）")
@discord.app_commands.describe(name=f"模型名，可选：{', '.join(AVAILABLE_MODELS)}")
@discord.app_commands.choices(
    name=[discord.app_commands.Choice(name=m, value=m) for m in AVAILABLE_MODELS]
)
async def model_cmd(interaction: discord.Interaction, name: discord.app_commands.Choice[str]):
    sessions.set_model(interaction.channel_id, name.value)
    await interaction.response.send_message(
        f"已切换模型为 **{name.value}**（历史保留）。"
    )


@bot.tree.command(name="models", description="列出可用模型")
async def models_cmd(interaction: discord.Interaction):
    current = sessions.get_model(interaction.channel_id)
    lines = [f"当前频道：**{current}**\n可用模型："]
    for m in AVAILABLE_MODELS:
        prefix = "→" if m == current else "  "
        lines.append(f"{prefix} `{m}`")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="help", description="查看机器人用法")
async def help_cmd(interaction: discord.Interaction):
    text = (
        "**DeepSeek Discord Bot 用法**\n\n"
        "**触发方式**\n"
        "- 在服务器频道里 @ 机器人，或直接私聊\n"
        "- 消息可以是纯文字、纯附件，或文字+附件\n\n"
        "**文件输入**\n"
        "- 支持 `.txt` / `.md` 附件（单个 ≤ 1MB）\n"
        "- 附件内容会拼到你的消息后面一起发给模型\n"
        "- 普通模式与特殊模式都支持\n\n"
        "**模式**\n"
        "- `/normal`：普通模式，标准 multi-turn，保留历史\n"
        "- `/special`：特殊模式，历史塞进 system prompt，无 cache 无服务端记忆\n"
        "- 切换模式会清空当前频道历史\n\n"
        "**模型**\n"
        "- `/model name:<模型>`：切换当前频道的模型，历史保留\n"
        "- `/models`：列出可用模型\n\n"
        "**自定义 system prompt（仅普通模式生效）**\n"
        "- `/system prompt:<文本>`：设置当前频道的 system prompt（不清空历史）\n"
        "- `/system_show`：查看当前 system prompt\n"
        "- `/system_clear`：清空 system prompt\n\n"
        "**消息编辑（重生 + 抛弃分支）**\n"
        "- 在 Discord 上修改之前发给机器人的某条消息后：\n"
        "  - 历史从这条消息处截断，**之后的所有内容都视为已抛弃的对话分支**\n"
        "  - 旧的机器人回复以及任何后续消息都会被打上 🪦 reaction 作为"
        "「已抛弃」的标记\n"
        "  - 用更新后的历史重新调一次模型，作为对编辑后消息的全新回复\n"
        "- 普通模式与特殊模式都支持\n"
        "- 重启 bot 后仍能识别旧消息的编辑\n\n"
        "**其他命令**\n"
        "- `/reset`：清空当前频道历史，模式保持不变\n"
        "- `/status`：查看当前模式、模型和历史轮数\n"
        "- `/help`：显示本说明\n\n"
        "**持久化**\n"
        "- 历史按频道保存到本地 JSON（默认 `chat_history.json`，可通过环境变量 `HISTORY_PATH` 指定）"
    )
    await interaction.response.send_message(text, ephemeral=True)


# ---------- 消息处理 ----------

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    # 让斜杠命令以外的 prefix 命令也能跑（如果你有的话）
    await bot.process_commands(message)
    # 忽略 prefix 命令本身
    if message.content.startswith(bot.command_prefix):
        return
    # 仅在被 @ 或私聊时回应；想要更激进可以去掉这一行
    if not (bot.user in message.mentions or isinstance(message.channel, discord.DMChannel)):
        return

    user_text = await _build_user_text(message)
    if not user_text:
        return

    channel_id = message.channel.id
    mode = sessions.get_mode(channel_id)
    model = sessions.get_model(channel_id)
    history = sessions.get_history(channel_id)

    async with message.channel.typing():
        try:
            if mode == "special":
                reply = await client.chat_special(history=history, user_text=user_text, model=model)
            else:
                system_prompt = sessions.get_system_prompt(channel_id)
                reply = await client.chat_normal(
                    history=history,
                    user_text=user_text,
                    model=model,
                    system_prompt=system_prompt or None,
                )
        except Exception as e:
            log.exception("DeepSeek 调用失败")
            try:
                await message.reply(f"❌ 出错了：`{e}`")
            except Exception:
                log.exception("发送错误回复也失败")
            return

    # 兜底：模型偶尔会返回空字符串，避免 _chunk 静默不发任何消息
    if not reply or not reply.strip():
        log.warning("模型返回空内容，channel=%s mode=%s model=%s", channel_id, mode, model)
        try:
            await message.reply("⚠️ 模型这次返回了空内容，再说一遍试试？")
        except Exception:
            log.exception("发送空回复提示失败")
        return

    # Discord 单条 2000 字限制，超出就分段；先发出去拿到 message id，再写历史，
    # 这样历史里 assistant 条目记录的 bot_message_ids 一定对应真实存在的消息。
    sent_ids: list[int] = []
    for chunk in _chunk(reply, 1900):
        try:
            sent = await message.reply(chunk)
            sent_ids.append(sent.id)
        except Exception:
            log.exception("发送回复失败 channel=%s", channel_id)
            break

    if not sent_ids:
        return

    sessions.append(channel_id, "user", user_text, discord_id=message.id)
    sessions.append(channel_id, "assistant", reply, bot_message_ids=sent_ids)


def _chunk(text: str, size: int):
    for i in range(0, len(text), size):
        yield text[i:i + size]


async def _build_user_text(message: discord.Message) -> str:
    """提取消息正文（去掉 @bot）+ 附件文本，拼成最终送给模型的 user 文本。"""
    text = message.clean_content.replace(f"@{bot.user.display_name}", "").strip()
    attachment_text = await _read_text_attachments(message)
    if attachment_text:
        text = f"{text}\n\n{attachment_text}".strip() if text else attachment_text
    return text


ABANDONED_REACTION = "🪦"


@bot.event
async def on_raw_message_edit(payload: discord.RawMessageUpdateEvent):
    """用户在 Discord 上修改了一条之前发给机器人的消息时：

    1. 在历史里找到这条 user 记录，更新内容；
    2. 把这条之后的所有历史（被抛弃的对话分支）从历史里截断；
    3. 给被抛弃的 Discord 消息（旧 bot reply 的所有分段 + 任何后续 user/bot
       消息）加 🪦 reaction，作为"已抛弃"的视觉标记；
    4. 用截断后的历史 + 这条编辑后的消息为最终 user，重新调一次模型，
       生成新的回复发到频道里。普通模式 / 特殊模式都走这套。

    用 raw 版本是为了 bot 重启后也能处理缓存里没有的旧消息编辑。
    """
    channel = bot.get_channel(payload.channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(payload.channel_id)
        except Exception:
            log.exception("获取频道失败 channel_id=%s", payload.channel_id)
            return
    try:
        after = await channel.fetch_message(payload.message_id)
    except discord.NotFound:
        return
    except Exception:
        log.exception(
            "获取被编辑消息失败 channel=%s message_id=%s",
            payload.channel_id, payload.message_id,
        )
        return

    if after.author.bot:
        return

    new_text = await _build_user_text(after)
    if not new_text:
        # 编辑后内容彻底为空（连附件都没有），不动历史
        return

    found, abandoned_ids = sessions.edit_user_message_and_truncate(
        payload.channel_id, payload.message_id, new_text
    )
    if not found:
        # 这条消息没在历史里（可能原本没 @ 机器人 / 被截断 / 内容没变），忽略
        return

    log.info(
        "edit 触发 regen，channel=%s message_id=%s 抛弃了 %d 条 Discord 消息",
        payload.channel_id, payload.message_id, len(abandoned_ids),
    )

    # 给被抛弃的消息加 🪦
    for mid in abandoned_ids:
        try:
            old_msg = await channel.fetch_message(mid)
            await old_msg.add_reaction(ABANDONED_REACTION)
        except discord.NotFound:
            pass
        except Exception:
            log.exception("给抛弃消息加 reaction 失败 message_id=%s", mid)

    # 重新调模型：截断后的历史末尾就是这条编辑过的 user 消息，
    # 把它拆成 history + user_text 喂给 chat_normal/chat_special。
    channel_id = payload.channel_id
    mode = sessions.get_mode(channel_id)
    model = sessions.get_model(channel_id)
    full_hist = sessions.get_history(channel_id)
    if not full_hist or full_hist[-1].get("role") != "user":
        log.warning("regen 前发现历史末尾不是 user，跳过 channel=%s", channel_id)
        return
    history = full_hist[:-1]
    user_text = full_hist[-1]["content"]

    async with channel.typing():
        try:
            if mode == "special":
                reply = await client.chat_special(
                    history=history, user_text=user_text, model=model,
                )
            else:
                system_prompt = sessions.get_system_prompt(channel_id)
                reply = await client.chat_normal(
                    history=history,
                    user_text=user_text,
                    model=model,
                    system_prompt=system_prompt or None,
                )
        except Exception as e:
            log.exception("DeepSeek regen 调用失败")
            try:
                await after.reply(f"❌ 重新生成失败：`{e}`")
            except Exception:
                log.exception("发送 regen 错误回复也失败")
            return

    if not reply or not reply.strip():
        log.warning("regen 模型返回空内容 channel=%s mode=%s model=%s", channel_id, mode, model)
        try:
            await after.reply("⚠️ 重新生成时模型返回了空内容。")
        except Exception:
            log.exception("发送 regen 空回复提示失败")
        return

    sent_ids: list[int] = []
    for chunk in _chunk(reply, 1900):
        try:
            sent = await after.reply(chunk)
            sent_ids.append(sent.id)
        except Exception:
            log.exception("发送 regen 回复失败 channel=%s", channel_id)
            break

    if sent_ids:
        sessions.append(channel_id, "assistant", reply, bot_message_ids=sent_ids)


ALLOWED_TEXT_EXTS = (".txt", ".md")
MAX_ATTACHMENT_BYTES = 1_000_000  # 单个文件最多 1MB，防止把上下文撑爆


async def _read_text_attachments(message: discord.Message) -> str:
    """把消息里所有 .txt / .md 附件读成纯文本，按文件名分块拼接。"""
    blocks: list[str] = []
    for att in message.attachments:
        name = (att.filename or "").lower()
        if not name.endswith(ALLOWED_TEXT_EXTS):
            continue
        if att.size and att.size > MAX_ATTACHMENT_BYTES:
            log.warning("跳过过大的附件 %s (%d bytes)", att.filename, att.size)
            blocks.append(f"[附件 {att.filename} 超过 {MAX_ATTACHMENT_BYTES} 字节，已跳过]")
            continue
        try:
            raw = await att.read()
            text = raw.decode("utf-8", errors="replace")
        except Exception as e:
            log.exception("读取附件 %s 失败", att.filename)
            blocks.append(f"[附件 {att.filename} 读取失败: {e}]")
            continue
        blocks.append(f"[附件 {att.filename}]\n{text}")
    return "\n\n".join(blocks)


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
