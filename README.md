# DeepSeek Discord Bot

> ⚠️ **个人自用项目（Personal use only）**
> 本仓库是作者本人日常使用的 Discord 聊天机器人，不接受外部用户、不提供托管、也不保证向后兼容。代码、配置、命令命名都按作者自己的习惯来，不针对通用用户做适配。如果你想 fork 自用，欢迎；但请不要把它当成可对外提供服务的产品。

简洁的 Discord 机器人，支持两种对话模式：

- **普通模式（normal）**：标准 multi-turn，历史按 `user`/`assistant` 角色拼接发送。可通过 `/system` 自定义 system prompt。
- **特殊模式（special）**：把整个对话历史 + 当前消息序列化进 system prompt，user role 仅放占位触发字符串。每次请求新建 HTTP client，请求头带 `Cache-Control: no-store`，无服务端 cache 复用。

## 安装

```bash
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填入你的 token 和 key
```

## 运行

```bash
python bot.py
```

## 命令

| 命令              | 作用                                                          |
| ----------------- | ------------------------------------------------------------- |
| `/special`        | 进入特殊模式（同时清空历史）                                  |
| `/normal`         | 切回普通模式（同时清空历史）                                  |
| `/model`          | 切换当前频道使用的模型（保留历史）                            |
| `/models`         | 列出可用模型                                                  |
| `/system`         | 设置当前频道的 system prompt（仅普通模式生效，不清空历史）    |
| `/system_show`    | 查看当前 system prompt                                        |
| `/system_clear`   | 清空 system prompt                                            |
| `/reset`          | 清空当前频道的会话历史                                        |
| `/status`         | 查看当前模式、模型、历史轮数和 system prompt 状态             |
| `/help`           | 查看用法                                                      |

机器人在被 @ 或在私聊时回复。

## 消息编辑（重生 + 抛弃分支）

在 Discord 上修改一条之前发给机器人的消息时：

1. 历史从那条消息处截断 —— 这条消息之后的所有 user / assistant 都视为「**已抛弃的对话分支**」；
2. 旧的机器人回复（含每段分块）和任何后续消息都会被打上 🪦 reaction 作为视觉标记；
3. 用更新后的历史 + 这条编辑后的消息为最终 user，重新调一次模型，生成新的回复发到频道；普通模式 / 特殊模式都走这套。

实现上用 `on_raw_message_edit` 而不是 `on_message_edit`，所以重启 bot 后仍能识别旧消息的编辑（不依赖 discord.py 的内存缓存）。

## 文件结构

```
deepseek-bot/
├── bot.py              # Discord 入口，事件 + 命令
├── deepseek_client.py  # API 调用，区分普通/特殊模式
├── session.py          # 按 channel 维护模式与历史
├── requirements.txt
├── .env.example
└── .env                # 你自己创建
```

## 关于「无 cache 无记忆」

- **服务端记忆**：DeepSeek API 本身就是无状态的，每次请求都得自己带历史。
- **Prompt cache**：DeepSeek 的 context caching 基于 prefix 自动命中。特殊模式下每次都把完整历史塞进 system prompt 末尾追加新内容，prefix 不会稳定不变 —— 但严格来说 prefix 前段可能仍命中。如果你要 100% 强制 miss，可以在 `chat_special` 的 `system_content` 开头加一个时间戳或随机 nonce，这样每次 prefix 都不同。需要的话告诉我加上。
