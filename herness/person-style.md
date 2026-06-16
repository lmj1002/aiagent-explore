# 修改 Hermes 个人风格流程

## 背景

Hermes 的个性化角色通过 `~/.hermes/SOUL.md` 文件定义。但直接修改该文件后重启 gateway，个性化配置并不会立即生效。本文档说明原因并提供正确的修改流程。

## 为什么修改 SOUL.md 后重启不生效？

Hermes 的系统提示词（含 SOUL.md 内容）遵循以下生命周期：

```
首次消息 → 读取 SOUL.md → 构建系统提示词 → 持久化到 state.db
                                                    ↓
后续消息 → 从 state.db 恢复旧提示词 ← 永远不再读取 SOUL.md
```

### 关键代码路径

| 文件 | 行号 | 行为 |
|---|---|---|
| `agent/system_prompt.py` | 87-95 | 从磁盘读取 SOUL.md，放入系统提示词 stable 层 |
| `agent/conversation_loop.py` | 267-270 | **如果 state.db 中存在已存储的提示词，直接复用，跳过 SOUL.md 读取** |
| `agent/conversation_loop.py` | 288 | 仅在 state.db 中无存储时，才重新构建系统提示词（此时会读 SOUL.md） |
| `agent/conversation_loop.py` | 310 | 构建后立即持久化到 state.db |

简而言之：**SOUL.md 只在会话首次创建时被读取一次**，之后永久缓存在 `state.db` 的 `sessions.system_prompt` 列中，跨 gateway 重启也依然有效。

SOUL.md 文件头部注释写的 "This file is loaded fresh each message -- no restart needed." **对 gateway 会话（微信等平台）不适用**。

## 正确修改流程

### 步骤 1：编辑 SOUL.md

```bash
vim ~/.hermes/SOUL.md
# 或
nano ~/.hermes/SOUL.md
```

按需修改角色设定、说话风格、工程原则等内容。

### 步骤 2：通过微信发送 `/reset`

```
/reset
```

这会在 `state.db` 中创建一个新会话（新 session_id），新会话没有预存系统提示词，因此下次消息会触发完整重建。

**注意**：`/reset` 会清空当前会话的对话历史。如果不想清历史，可以使用下面的替代方案。

### 步骤 3：验证

发送一条测试消息，例如：

```
你好，简单介绍一下自己
```

检查回复是否符合新的个性化设定。如果 SOUL.md 中定义了识别标记（如 "【星海协议已加载】"），确认回复中包含该标记。

## 验证方法

### 方法 1：观察回复风格

修改 SOUL.md 前后分别发送 "介绍一下自己"，对比回复风格是否发生变化。

### 方法 2：检查数据库

```bash
cd ~/.hermes
python3 -c "
import sqlite3
conn = sqlite3.connect('state.db')
c = conn.cursor()
c.execute('SELECT id, length(system_prompt) as len FROM sessions ORDER BY started_at DESC LIMIT 1')
row = c.fetchone()
print(f'最新会话: {row[0]}, 提示词长度: {row[1]} 字符')
# 检查是否包含自定义标记
c.execute('SELECT system_prompt FROM sessions ORDER BY started_at DESC LIMIT 1')
sp = c.fetchone()[0] or ''
print(f'含自定义标记: {\"你的关键词\" in sp}')
conn.close()
"
```

### 方法 3：查看 gateway 日志

```bash
tail -f ~/.hermes/logs/agent.log | grep -E "conversation turn|response_len"
```

## 替代方案（不想丢失会话历史）

如果不想用 `/reset` 清空历史，可以手动清除 state.db 中存储的 system_prompt：

```bash
cd ~/.hermes
python3 -c "
import sqlite3
conn = sqlite3.connect('state.db')
c = conn.cursor()
# 查看当前会话
c.execute('SELECT id FROM sessions ORDER BY started_at DESC LIMIT 1')
session_id = c.fetchone()[0]
print(f'当前会话: {session_id}')
# 清空存储的提示词，迫使下次消息重建
c.execute('UPDATE sessions SET system_prompt = \"\" WHERE id = ?', (session_id,))
conn.commit()
print('已清除存储的系统提示词，下次消息将重建')
conn.close()
"
```

Gateway 不需要重启，下次消息即可生效。

## 常见问题

### Q: 修改 config.yaml 中的 `display.personality` 有用吗？

`display.personality` 是旧版配置项，当前版本（0.16.0）主要通过 SOUL.md 控制角色。`/personality` 命令设置的是 `agent.system_prompt`（ephemeral system prompt），会追加到 SOUL.md 之后，而非替代。

### Q: 重启 gateway 或重启服务器能解决吗？

不能。因为系统提示词持久化在 `state.db`（SQLite 文件）中，重启进程不会清除数据库记录。

### Q: 删除 state.db 可以吗？

可以，但会丢失所有会话历史和配置状态。建议用 `/reset` 或上述 SQL 方案。

## 总结

| 操作 | 是否生效 | 备注 |
|---|---|---|
| 修改 SOUL.md 后重启 gateway | ❌ | 旧会话从 DB 恢复旧提示词 |
| 修改 SOUL.md 后发 `/reset` | ✅ | 推荐方式 |
| 修改 SOUL.md + 清 DB system_prompt | ✅ | 保留历史 |
| 修改 SOUL.md + 新用户/新平台首次发消息 | ✅ | 无旧会话，自然触发重建 |
