# Hermes Agent 配置项参考手册

基于 `hermes postinstall` 交互式配置向导，逐项说明。

---

## 配置项总览：哪些必配、哪些可跳

| 序号 | 配置项 | 是否必配 | 一句话 |
|------|--------|:--------:|--------|
| 1 | Browser Engine (Chromium) | ❌ 可跳过 | 网页浏览工具依赖，国内下载慢 |
| 2 | LLM Provider | ✅ **必配** | Agent 的大脑，不配跑不起来 |
| 3 | Model | ✅ **必配** | 选哪个模型来干活 |
| 4 | Context Length | ❌ 可跳过 | 自动检测，回车即过 |
| 5 | Display Name | ❌ 可跳过 | 纯标签，回车即过 |
| 6 | Terminal Backend | ❌ 用默认 | local 就行 |
| 7 | Messaging Platforms | ❌ 可选 | 想在微信/飞书里用 Agent 就配 |
| 8 | Tools | ❌ 用默认 | 默认勾选已够用 |
| 9 | Search Provider | ❌ 可跳过 | 国内网络不通，后续再配 |

---

## 1. Browser Engine（浏览器引擎）

```
Browser engine (Chromium, for web browsing tools) is not installed.
Install now? [Y/n]
```

### 含义

安装 Chromium 浏览器，给 Hermes 的网页自动化工具有个"浏览器"可以用——比如让它打开网页、点击按钮、截屏分析。

### 是否必配

**❌ 不必配**。不影响对话、写代码、读文件等核心功能。国内从 `storage.googleapis.com` 下载极慢，直接选 `n`。

### 什么时候需要

当你让 Agent "帮我去淘宝搜一下XX"、"打开这个网页看看内容"时，它需要一个真实的浏览器。

### 后续安装

```bash
agent-browser install --with-deps
```

---

## 2. LLM Provider（大模型提供商）

```
Select provider:
  ( ) Nous Portal        — 官方订阅（300+ 模型，含工具调用）
  ( ) OpenRouter         — 付费聚合器
  ( ) Anthropic          — Claude 系列
  ( ) OpenAI             — GPT 系列
  ( ) DeepSeek           — 国产之光，便宜
  ( ) Qwen / DashScope   — 阿里云
  ( ) Z.AI / GLM         — 智谱
  ( ) Kimi / Moonshot    — 月之暗面
  ( ) custom (direct API) — 自定义兼容端点
  ...
```

### 含义

Agent 的核心——它调用谁的模型来"思考"。不同的 Provider 就是不同的模型来源。

### 是否必配

**✅ 必配**，不配 Agent 就是个空壳。

### 怎么选

| 你的情况 | 推荐 |
|----------|------|
| 有 DeepSeek API Key | 选 DeepSeek，国内直连，便宜 |
| 有中转平台账号（硅基流动/dstopology 等） | 选 `custom (direct API)` |
| 有 OpenAI/Anthropic 官方 Key + 代理 | 选对应官方项 |
| 啥都没有 | 先去 siliconflow.cn 注册，再选 `custom` |

#### custom 模式填什么

| 字段 | 填写内容 | 示例 |
|------|----------|------|
| Base URL | 中转平台给的 API 地址 | `https://api.dstopology.com/v1` |
| API Key | 平台生成的密钥 | `sk-xxxx` |
| 兼容模式 | `1. Auto-detect` | 绝大多数中转站用这个 |
| 模型 | 从列表选最强的 | `gpt-5.5` |
| Context Length | 回车留空 | 自动检测 |
| Display Name | 随便起名 | `中转站` |

---

## 3. Model（模型选择）

```
Available models:
  1. gpt-5.5
  2. gpt-5.4
  ...
```

### 含义

具体用哪个模型来处理你的请求。不同模型能力、速度和价格不同。

### 选择建议

- **选最新最强的**当默认（如 `gpt-5.5`）
- 日常简单任务可以让 Agent 自动降级到轻量模型
- 后面可以随时 `hermes setup model` 更换

---

## 4. Context Length（上下文窗口大小）

```
Context length in tokens [leave blank for auto-detect]:
```

### 含义

模型一次能"记住"多少内容（单位 token，约等于 0.75 个英文词或 0.5 个中文字）。

### 是否必填

**❌ 不用填**，直接回车。Hermes 会自动查模型的上下文窗口。

### 什么时候手填

只在使用非常小众的自部署模型、Hermes 查不到时才需要。

---

## 5. Display Name（显示名称）

```
Display name [Api.dstopology.com]:
```

### 含义

给你当前配置起个名字，方便在多个 Provider 之间切换时辨认。

### 是否必填

**❌ 不必填**，回车用默认。

### 怎么起名

- `主力机` — 日常用的
- `便宜货` — 处理简单任务省钱的
- `代码专用` — 配的代码模型
- 直接回车用默认也完全没问题

---

## 6. Terminal Backend（终端后端）

```
Select terminal backend:
  (●) Local    — 在本机直接运行命令
  ( ) Docker   — 在隔离容器里运行
  ( ) SSH      — 连到远程机器运行
```

### 含义

Agent 执行 Shell 命令、读写文件时，在哪里执行这些操作。

### 是否改

**❌ 用默认的 Local 就行**。

| 场景 | 选哪个 |
|------|--------|
| Agent 和你同在一台服务器 | Local |
| 想让 Agent 在独立环境操作、不影响宿主机 | Docker |
| Agent 在这台，想让它操作另一台机器 | SSH |

---

## 7. Messaging Platforms（消息平台接入）

```
Select platforms to configure:
  [ ] Weixin / WeChat
  [ ] QQ Bot
  [ ] Feishu / Lark
  [ ] DingTalk
  [ ] Telegram
  [ ] Discord
  ...
```

### 含义

把 Hermes 接入聊天软件，你可以像跟朋友聊天一样通过微信/QQ/飞书等指挥 Agent。

### 是否必配

**❌ 可选**。不配也能用 `hermes` 命令直接在终端对话。

### 国内常用平台对比

| 平台 | 接入难度 | 稳定性 | 适合场景 |
|------|:--------:|:------:|----------|
| **QQ Bot** | ⭐⭐ 中等 | 一般 | 个人使用 |
| **WeChat（个人微信）** | ⭐⭐⭐ 较难 | 有封号风险 | 个人尝鲜 |
| **WeCom（企业微信）** | ⭐ 简单 | 稳定 | 工作场景，有官方 API |
| **Feishu / Lark** | ⭐ 简单 | 稳定 | 团队协作 |
| **DingTalk** | ⭐⭐ 中等 | 稳定 | 企业场景 |
| **Telegram** | ⭐ 最简单 | 稳定 | 个人首选（但需代理） |

### 建议

- 个人尝鲜 → 选 QQ Bot 或 Telegram
- 工作使用 → 飞书或企业微信（API 正规、不怕封）
- 不确定 → 先空着，回头 `hermes setup gateway` 再配

---

### 微信接入完整流程（个人微信扫码方式）

#### 第一步：进入 gateway 配置

```bash
hermes setup gateway
```

在平台列表中用 **空格** 勾选 `Weixin / WeChat`，回车确认。

#### 第二步：授权模式设置

**DM（私聊）授权方式：**

```
How should direct messages be authorized?
  (●) Use DM pairing approval (recommended)
  (○) Allow all direct messages
  (○) Only allow listed user IDs
  (○) Disable direct messages
```

→ 选 **第一个** `Use DM pairing approval`，最安全——陌生人要私聊需要你批准。

**群聊处理方式：**

```
How should group chats be handled?
  (●) Disable group chats (recommended)
  (○) Allow all group chats
  (○) Only allow listed group chat IDs
```

→ 选 **第一个** `Disable group chats`。Agent 进群风险大——群里谁都能 @ 它执行命令。

#### 第三步：扫码绑定

配置完成后，终端会显示一个链接（或 ASCII 二维码）：

```
请使用微信扫描以下二维码：
https://liteapp.weixin.qq.com/q/7GiQu1?qrcode=xxxx&bot_type=3
```

在手机上打开链接，用微信扫码。扫码后会打开一个叫 **OpenClaw/ClawBot** 的微信小程序——这就是微信和 Hermes 之间的"桥梁"。

> **注意**：如果终端提示 `No module named 'qrcode'`，直接忽略，用链接在手机上打开就行。

#### 第四步：设置 Home Channel

```
Use your Weixin user ID (xxx@im.wechat) as the home channel? [Y/n]:
```

→ 选 **Y**。Home Channel 是 Hermes 的"默认聊天窗口"，通知和回复都发到这个号。

#### 第五步：安装为系统服务

```
Install the gateway as a systemd service? [Y/n]:
```

→ 选 **Y**。否则 SSH 一断开 gateway 就停了，微信那头 Agent 就不理你了。

```
Choose how the gateway should run in the background:
  ( ) User service
  (●) System service (starts on boot; requires sudo)
  ( ) Skip
```

→ 服务器上选 **System service**，开机自启、不会因登出挂掉。

```
Start the service now? [Y/n]:
```

→ 选 **Y**，立即启动。

#### 第六步：授权你的微信账号

Gateway 启动后，在微信给 Hermes 发一条消息。然后回到服务器：

```bash
# 查看待批准的 pairing 请求
hermes pairing list

# 批准（code 从上面命令的输出里复制）
hermes pairing approve weixin <code>
```

> ⚠️ **Code 有时效性**（几分钟），如果过期了就再发一条消息产生新 code。

---

### 微信接入常见坑

#### 坑 1：Gateway 启动失败 — `Permission denied (CHDIR)`

```
hermes-gateway.service: Changing to the requested working directory failed: Permission denied
hermes-gateway.service: Failed at step CHDIR spawning /usr/bin/python3.11: Permission denied
```

**原因**：`~/.hermes/` 目录及子文件的所有者不是当前用户。之前用 `sudo hermes postinstall` 导致部分文件归属为 root 或未知 UID。

**排查**：

```bash
sudo ls -la /home/ubuntu/.hermes
# 如果看到 owner 是 10000 或 root 而不是 ubuntu → 中招了
```

**修复**：

```bash
sudo chown -R ubuntu:ubuntu /home/ubuntu/.hermes
sudo systemctl restart hermes-gateway
```

#### 坑 2：微信消息无人回复 — `Unauthorized user`

```bash
journalctl -u hermes-gateway -n 30 --no-pager
# 输出：WARNING gateway.run: Unauthorized user: xxx@im.wechat on weixin
```

**原因**：微信消息已经到达服务器，但因为没有 approve pairing 所以被拦截。或者 pairing code 已过期。

**修复（两种方式）**：

```bash
# 方式 A：正式做法 — 批准 pairing
hermes pairing list                      # 查看待批准
hermes pairing approve weixin <code>     # 批准

# 方式 B：临时做法 — 开放访问（个人服务器推荐）
echo "GATEWAY_ALLOW_ALL_USERS=true" >> ~/.hermes/.env
sudo systemctl restart hermes-gateway
```

> 💡 个人使用建议直接用方式 B，省去 pairing code 过期的麻烦。方式 A 更适合多用户场景。

#### 坑 3：配置丢了 — 平台未启用

```bash
sudo systemctl status hermes-gateway
# 输出：WARNING gateway.run: No messaging platforms enabled.
```

**原因**：之前配置时文件权限不对，WeChat 配置没写进 `config.yaml`。重新跑 `hermes setup gateway` 并确认权限正确。

#### 坑 4：二维码扫不了

远程 SSH 终端里的二维码没法直接用手机扫。

**解决方案**：
- 直接复制终端显示的 `https://liteapp.weixin.qq.com/q/...` 链接，在手机上打开
- 或者把字体调小（`Ctrl+-`）、窗口拉大，ASCII 二维码能显示得更清晰

---

### Gateway 管理命令速查

```bash
# 启停
sudo systemctl start hermes-gateway       # 启动
sudo systemctl stop hermes-gateway        # 停止
sudo systemctl restart hermes-gateway     # 重启
sudo systemctl status hermes-gateway      # 状态

# 日志
journalctl -u hermes-gateway -f           # 实时跟踪
journalctl -u hermes-gateway -n 50        # 最近 50 行

# Pairing 管理
hermes pairing list                       # 待批准列表
hermes pairing approve weixin <code>      # 批准某用户
hermes pairing revoke <user_id>           # 撤销某用户

# 重新配置
hermes setup gateway                      # 重配聊天平台
```

## 8. Tools（工具开关）

```
Tools for CLI:
  [✓] Web Search & Scraping     — 网页搜索抓取
  [✓] Browser Automation        — 浏览器自动化
  [✓] Terminal & Processes      — 执行命令
  [✓] File Operations           — 读写文件
  [✓] Code Execution            — 执行代码
  [✓] Vision / Image Analysis   — 图片识别
  [ ] Video Analysis             — 视频分析
  [✓] Image Generation          — AI 生图
  [ ] X (Twitter) Search        — 推特搜索
  [✓] Text-to-Speech            — 文字转语音
  [✓] Memory                    — 持久记忆
  [✓] Cron Jobs                 — 定时任务
  [ ] Spotify                    — 音乐控制
  [✓] Computer Use (macOS)      — ⚠️ 仅 macOS
```

### 含义

授予 Agent 哪些能力——能不能上网搜、能不能操作文件、能不能执行代码、能不能看图等等。

### 默认就好

Hermes 的默认勾选已经很合理。只需要注意：

| 工具 | 操作 |
|------|------|
| 🖱️ Computer Use (macOS) | **取消勾选** — 你是 Ubuntu，这是 macOS 专用 |
| 🎬 Video Analysis | 不勾，除非你配了支持视频的模型 |
| 🐦 X (Twitter) Search | 不勾，国内用不了 |
| 🧩 Context Engine | 可选勾 — 让 Agent 更理解上下文 |

---

## 9. Search Provider（搜索服务商）

```
Select Search Provider:
  ( ) DuckDuckGo       — 免费，无需 Key（国内连不上）
  ( ) Brave Search     — 免费 2000 次/月
  ( ) SearXNG           — 自建聚合搜索
  ( ) Firecrawl        — 付费，全功能
  ( ) Tavily            — 付费
  ( ) Skip              — 跳过
```

### 含义

Agent 搜索网页时通过哪个搜索引擎来查。

### 国内建议

| 选择 | 理由 |
|------|------|
| ⭐ **Skip** | 先跳过，大部分国外服务连不上 |
| **SearXNG** | 自己有 Docker 可以自建一个，隐私又稳定 |
| 中转平台自带 | 有些中转站的模型自带搜索，不需要额外配 |

### 后续配置

```bash
hermes setup tools    # 回来配搜索
```

---

## 配完了怎么改

```bash
# 单项修改
hermes setup model         # 更换模型/Provider
hermes setup terminal      # 更换执行环境
hermes setup gateway       # 配置聊天平台
hermes setup tools         # 开关工具、配搜索

# 全局重配
hermes setup               # 重新走完整向导

# 直接改文件
nano ~/.hermes/config.yaml        # 配置文件
nano ~/.hermes/.env               # API Key
```

---

## 极简配置清单（3 分钟搞定）

如果只想让 Hermes 跑起来，最小配置就这几项：

1. **Provider** → `custom (direct API)` → 填 Base URL + API Key → 选 `1. Auto-detect`
2. **Model** → 列表里选最强的
3. **后面全部回车/ESC 跳过**
4. **Tools 页** → 取消 `Computer Use (macOS)`

其他全用默认，回头再调。
