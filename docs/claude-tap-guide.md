# Claude-Tap 安装与使用指南

> 安装日期：2026-06-22 | 版本：0.1.120 | Python 3.11.9

## 一、简介

**claude-tap** 是一个开源的本地代理和追踪查看器，专为 AI 编程代理设计。它能拦截并记录 AI CLI 工具（如 Claude Code）与上游 API 提供商之间的所有 API 流量，并提供交互式浏览器查看器来检查数据——被称为 **"AI 代理的 Wireshark"**。

- **仓库**：[github.com/liaohch3/claude-tap](https://github.com/liaohch3/claude-tap)
- **许可证**：MIT
- **语言**：Python（要求 3.11+）

### 核心特性

| 特性 | 说明 |
|------|------|
| **实时代理** | 位于 AI 客户端和 API 之间，记录所有请求和响应 |
| **实时查看器** | 基于浏览器的 SSE 流式实时更新，零延迟 |
| **结构化差异比较** | 比较相邻请求的变化（消息、系统提示、工具定义），字符级高亮 |
| **系统提示查看器** | 揭示 Claude Code 发送的完整隐藏系统提示 |
| **工具调用检查** | 展开卡片显示工具名称、描述、参数模式、调用结果 |
| **Token 用量明细** | 每个请求的输入/输出/缓存读取/缓存创建 token 计数 |
| **自包含 HTML 导出** | 单个离线 HTML 文件，含深色模式、搜索、键盘导航 |
| **API 密钥自动脱敏** | 授权头在记录前被部分遮盖 |
| **多客户端支持** | 支持 11+ 种 AI 编程 CLI 工具 |
| **国际化** | 英文、简体中文、日文、韩文、法文、阿拉伯文、德文、俄文 |

---

## 二、工作原理

```
你 → 运行 claude-tap → 启动 AI 客户端（如 Claude Code）
    → 请求发送到本地代理 (127.0.0.1:9123) → 转发到真实 API
    → 响应返回
    → 所有请求/响应对被记录到 trace.jsonl
    → 退出时，生成自包含的 HTML 追踪查看器
    → 实时模式可以流式传播到浏览器
```

### 两种代理模式

| 模式 | 说明 | 适用客户端 |
|------|------|-----------|
| **反向代理** | 重写 `ANTHROPIC_BASE_URL`，使客户端将流量发送到本地代理 | Claude Code、Codex、Kimi、Kimi-Code、OpenClaw、CodeBuddy |
| **正向代理** | 充当网络级中间人，设置 `HTTPS_PROXY` + CONNECT/TLS 终止 | Gemini、OpenCode、Pi、Hermes、Cursor、Qoder、Antigravity |

---

## 三、本机安装记录

### 环境信息

| 项目 | 详情 |
|------|------|
| 操作系统 | Windows 11 Home China 10.0.26200 |
| Python | 3.11.9 |
| 安装方式 | pip |
| 安装路径 | `C:\Users\伊初\AppData\Roaming\Python\Python311\Scripts\claude-tap.exe` |
| Claude Code 配置 | 自定义 API 端点 `https://ai-router.plugins-world.cn` |
| Claude Code 环境变量 | `CLAUDE_CODE_ATTRIBUTION_HEADER=0` |

### 安装命令

```bash
# 安装
pip install claude-tap

# 将 Python Scripts 添加到用户 PATH（永久）
# 路径：C:\Users\伊初\AppData\Roaming\Python\Python311\Scripts
```

### 升级

```bash
claude-tap update                         # 自动升级
claude-tap update --installer pip         # 强制用 pip 升级
pip install --upgrade claude-tap          # 直接用 pip
```

---

## 四、基本使用

### Claude Code 追踪

```bash
# 基本追踪（实时浏览器查看器默认开启）
claude-tap

# 继续上一次对话
claude-tap -c

# 传递参数给 Claude Code（使用 -- 分隔符）
claude-tap -- --model claude-sonnet-4-5

# 跳过权限确认（自动批准所有工具调用）
claude-tap -- --dangerously-skip-permissions

# 组合多个参数
claude-tap -- --dangerously-skip-permissions --model claude-sonnet-4-5
```

### 实时查看器控制

```bash
# 禁用实时查看器，仅保存追踪文件（恢复 v0.1.75 之前的行为）
claude-tap --tap-no-live

# 不自动在浏览器中打开查看器
claude-tap --tap-no-open

# 指定实时查看器端口（默认 19527）
claude-tap --tap-live-port 3000
```

### 追踪其他 AI 客户端

```bash
# Codex CLI
claude-tap --tap-client codex

# Gemini CLI
claude-tap --tap-client gemini -- -p "hello"

# Kimi Code CLI
claude-tap --tap-client kimi-code

# Cursor CLI
claude-tap --tap-client cursor -- -p --trust --model auto "hello"

# Codex App（监听本地会话）
claude-tap --tap-client codexapp

# OpenCode
claude-tap --tap-client opencode

# Pi
claude-tap --tap-client pi -- --model openai-codex/gpt-5.3-codex-spark -p "hello"

# Hermes Agent
claude-tap --tap-client hermes

# Qoder CLI
claude-tap --tap-client qoder -- -p "hello" --permission-mode dont_ask

# Antigravity CLI
claude-tap --tap-client agy

# CodeBuddy
claude-tap --tap-client codebuddy
```

### 仅代理模式（自定义设置）

```bash
# 启动代理但不启动客户端
claude-tap --tap-no-launch --tap-port 8080

# 在另一个终端中：
ANTHROPIC_BASE_URL=http://127.0.0.1:8080 claude
```

---

## 五、导出与分析

### 导出追踪

```bash
# 导出为 Markdown
claude-tap export trace.jsonl

# 导出到指定文件
claude-tap export trace.jsonl -o report.md

# 导出为 HTML 查看器
claude-tap export trace.jsonl -o report.html

# 导出为 JSON
claude-tap export trace.jsonl --format json

# 导出提示词快照
claude-tap export trace.jsonl --format prompt-md -o prompt.md

# 注意：实时模式会直接将会话保存到 trace 存储中
```

### Dashboard

```bash
# 浏览追踪历史
claude-tap dashboard

# 停止 dashboard 服务
claude-tap dashboard stop

# 指定 dashboard 端口
claude-tap dashboard --tap-live-port 3000
```

---

## 六、完整 CLI 参考

### 代理选项

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--tap-port PORT` | 代理端口 | 自动 |
| `--tap-host HOST` | 绑定地址 | 127.0.0.1 |
| `--tap-client CLIENT` | 要启动的客户端 | claude |
| `--tap-target TARGET` | 上游 API URL | 自动检测 |
| `--tap-proxy-mode MODE` | 代理模式（reverse/forward） | 按客户端 |
| `--tap-trust-ca` | macOS 上信任正向代理 CA | - |
| `--tap-no-launch` | 仅启动代理，不启动客户端 | - |
| `--tap-allow-path PREFIX` | 允许通过代理的额外路径前缀 | - |

### 查看器选项

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--tap-no-open` | 不自动打开浏览器查看器 | - |
| `--tap-live` | 启用实时仪表盘 | 默认开启 |
| `--tap-no-live` | 禁用实时仪表盘 | - |
| `--tap-live-port PORT` | 实时仪表盘端口 | 19527 |

### 存储与更新选项

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--tap-output-dir DIR` | 旧版追踪导入目录 | ./.traces |
| `--tap-max-traces N` | 最大保留追踪会话数 | 50 |
| `--tap-store-stream-events` | 持久化原始 SSE/WebSocket 事件 | 关闭 |
| `--tap-export-prompt PATH` | 导出捕获的提示词为 Markdown | - |
| `--tap-no-update-check` | 禁用启动时 PyPI 更新检查 | - |
| `--tap-no-auto-update` | 检查更新但不自动下载 | - |

---

## 七、支持的客户端总览

| 客户端 | `--tap-client` | API 类型 | 代理模式 |
|--------|---------------|----------|----------|
| Claude Code | `claude` | Anthropic API / Bedrock / DeepSeek | 反向代理 |
| Codex CLI | `codex` | OpenAI API / ChatGPT OAuth | 反向代理 |
| Codex App | `codexapp` | 本地会话 JSONL | 转录导入 |
| Gemini CLI | `gemini` | Google OAuth / Code Assist | 正向代理 |
| Kimi CLI | `kimi` | Kimi Code / Moonshot Platform | 反向代理 |
| Kimi-Code CLI | `kimi-code` | MoonshotAI/kimi-code | 反向代理 |
| OpenCode | `opencode` | 多提供商 | 正向代理 |
| OpenClaw | `openclaw` | OpenClaw 配置的提供商 | 反向代理 |
| Pi | `pi` | 多提供商（含 Codex OAuth） | 正向代理 |
| Hermes Agent | `hermes` | 多提供商（10+） | 正向代理 |
| Cursor CLI | `cursor` | Cursor Agent | 正向代理 |
| Qoder CLI | `qoder` | Qoder Agent | 正向代理 |
| Antigravity CLI | `agy` | Google Code Assist | 正向代理 |
| CodeBuddy CLI | `codebuddy` | Tencent Copilot | 反向代理 |

---

## 八、安全与隐私

- API 密钥在记录前自动脱敏（`Authorization`、`x-api-key` 等头被遮盖）
- 所有数据保留在本地，无云端仪表盘，无遥测
- SSE 流式响应实时转发，零额外延迟
- 导出的 HTML 查看器完全自包含，无外部依赖

---

## 九、常用工作流

### 日常开发追踪

```bash
# 启动追踪，做完事后查看报告
claude-tap
# ... 在 Claude Code 中完成工作 ...
# 退出后自动生成 HTML 报告在浏览器中打开
```

### 调试 API 调用

```bash
# 仅代理模式，手动控制
claude-tap --tap-no-launch --tap-port 8080 --tap-no-live
# 另一个终端：
ANTHROPIC_BASE_URL=http://127.0.0.1:8080 claude
# 查看 trace.jsonl 中的原始请求/响应
```

### 导出分享

```bash
# 生成自包含的 HTML 报告
claude-tap export trace.jsonl -o session-report.html
# 可以用浏览器直接打开 session-report.html，无需任何依赖
```
