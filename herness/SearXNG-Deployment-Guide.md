# SearXNG 部署与调优指南

> 部署日期：2026-06-15  
> 实例名称：Hermes Search  
> 服务器：Ubuntu 22.04 + Docker Compose  
> SearXNG 版本：2026.6.15-cf1410af8

---

## 目录

1. [架构概览](#1-架构概览)
2. [Docker Compose 部署](#2-docker-compose-部署)
3. [配置文件](#3-配置文件)
4. [搜索引擎策略](#4-搜索引擎策略)
5. [Hermes (AI Agent) 集成](#5-hermes-ai-agent-集成)
6. [故障排查记录](#6-故障排查记录)
7. [性能基准](#7-性能基准)

---

## 1. 架构概览

```
┌──────────────┐     WeChat Message      ┌────────────────┐
│   微信用户     │ ──────────────────────→ │  Hermes Agent   │
│  (WeChat)    │ ←────────────────────── │  (Gateway)      │
└──────────────┘     AI Reply            │  systemd        │
                                         │  PID varies     │
                                         └───────┬────────┘
                                                 │ SEARXNG_URL
                                                 ▼
                                         ┌────────────────┐
                                         │   SearXNG       │
                                         │   Docker        │
                                         │   127.0.0.1:8080│
                                         └───────┬────────┘
                                                 │ parallel search
                                         ┌───────┼───────┐
                                         ▼       ▼       ▼
                                      baidu  360search  sogou
                                      bing   (optional)
```

**组件清单：**

| 组件 | 位置 | 端口 | 管理方式 |
|------|------|------|----------|
| SearXNG | Docker (`searxng/searxng:latest`) | `127.0.0.1:8080` | `docker compose` |
| Hermes Gateway | 本地 Python 安装 | - | `systemd` |
| 微信集成 | Hermes 内置 `weixin` 平台 | - | Hermes Gateway |

---

## 2. Docker Compose 部署

### 2.1 目录结构

```
/home/ubuntu/searxng/
├── docker-compose.yml          # 容器编排
└── searxng-config/
    ├── settings.yml            # SearXNG 主配置
    └── limiter.toml            # 机器人检测配置
```

### 2.2 docker-compose.yml

```yaml
services:
  searxng:
    image: searxng/searxng:latest
    container_name: searxng
    restart: unless-stopped
    ports:
      - "127.0.0.1:8080:8080"       # 仅监听本地，不暴露公网
    volumes:
      - ./searxng-config:/etc/searxng:rw
    environment:
      - SEARXNG_BASE_URL=http://localhost:8080/
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - SETGID
      - SETUID
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

**关键设计决策：**

- `127.0.0.1:8080:8080` —— SearXNG 只绑定 localhost，不对外暴露，防止被滥用
- `SEARXNG_BASE_URL=http://localhost:8080/` —— 用于生成正确的自引用 URL
- `unless-stopped` —— 崩溃自动重启
- `cap_drop: ALL` + 最小 `cap_add` —— 容器安全加固

### 2.3 limiter.toml

```toml
[botdetection.ip_limit]
link_token = false
```

禁用 link_token 检测。因为 Hermes 从本地发起的请求不带 `X-Forwarded-For` 头，启用会导致 bot detection 报错。

---

## 3. 配置文件

### 3.1 完整 settings.yml

```yaml
use_default_settings: true

general:
  instance_name: "Hermes Search"

brand:
  issue_url: ""
  docs_url: ""
  public_instances: ""
  wiki_url: ""

search:
  safe_search: 0
  autocomplete: ""
  default_lang: "zh-CN"
  formats:
    - html
    - json

server:
  secret_key: "f3a8e9c1b7d24f56a901c3e8d7b2f4a1"
  bind_address: "0.0.0.0"
  port: 8080
  limiter: false
  image_proxy: false

ui:
  static_use_hash: true
  default_theme: simple
  default_locale: zh-Hans-CN

outgoing:
  request_timeout: 6.0
  useragent_suffix: ""
  using_tor_proxy: false

doi_resolvers:
  oadoi.org: "https://api.oadoi.org/"
  doi.org: "https://doi.org/"

default_doi_resolver: "oadoi.org"

engines:
  # ── Disabled — timeout / unreachable inside China ──
  - name: google
    disabled: true
  - name: duckduckgo
    disabled: true
  - name: brave
    disabled: true
  - name: startpage
    disabled: true
  - name: yahoo
    disabled: true
  - name: qwant
    disabled: true
  - name: yep
    disabled: true
  - name: mojeek
    disabled: true
  - name: mwmbl
    disabled: true
  - name: presearch
    disabled: true
  - name: swisscows
    disabled: true
  - name: wikipedia
    disabled: true

  # ── Enabled — Chinese-friendly web search ──
  - name: baidu
    engine: baidu
    shortcut: bd
    disabled: false
    timeout: 6.0

  - name: 360search
    engine: 360search
    shortcut: 360
    disabled: false
    timeout: 6.0

  - name: sogou
    engine: sogou
    shortcut: sg
    disabled: false
    timeout: 6.0

  - name: bing
    engine: bing
    shortcut: bi
    disabled: false
    timeout: 6.0

  - name: bing news
    engine: bing_news
    shortcut: bin
    disabled: false
    timeout: 6.0
```

### 3.2 配置要点说明

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `use_default_settings` | `true` | 加载 SearXNG 内置默认设置（超时、网络、缓存等），用户配置覆盖其上 |
| `server.bind_address` | `0.0.0.0` | 容器内监听所有接口（外部由 Docker 端口映射控制） |
| `server.limiter` | `false` | 关闭速率限制（由 Docker 端口绑定和 Hermes 控制访问） |
| `outgoing.request_timeout` | `6.0` | 每个引擎请求超时 6 秒 |
| `search.default_lang` | `zh-CN` | 默认中文搜索 |
| `ui.default_locale` | `zh-Hans-CN` | 界面默认简体中文 |
| `brand.public_instances` | `""` | **必须是字符串**（空字符串表示不公开），新版 SearXNG 不接受 `false` |
| engine `timeout` | `6.0` | 每个引擎独立超时，SearXNG 并行请求所有引擎 |

### 3.3 可用的 SearXNG 搜索引擎（完整列表）

SearXNG 内置 250+ 搜索引擎。以下列出了已测试并纳入生产配置的引擎：

| 引擎 | shortcut | 类型 | 国内可达 | 状态 |
|------|----------|------|----------|------|
| **baidu** | `bd` | 通用网页 | ✅ | 启用 |
| **360search** | `360` | 通用网页 | ✅ | 启用 |
| **sogou** | `sg` | 通用网页 | ✅ | 启用 |
| **bing** | `bi` | 通用网页 | ✅ | 启用 |
| **bing news** | `bin` | 新闻搜索 | ✅ | 启用 |
| google | `g` | 通用网页 | ❌ | 禁用 |
| duckduckgo | `ddg` | 通用网页 | ❌ | 禁用 |
| brave | - | 通用网页 | ❌ | 禁用 |
| wikipedia | `wp` | 百科 | ❌ | 禁用 |
| startpage | `sp` | 隐私搜索 | ❌ | 禁用 |

**重要原则：** 只有真正能在当前网络环境中连通的引擎才应启用。SearXNG 并行等待所有引擎返回——一个引擎卡住就会拖慢整个搜索。

---

## 4. 搜索引擎策略

### 4.1 为什么必须禁用海外引擎

SearXNG 的搜索架构是**全并行 + 全等待**：

```
request
  ├─ baidu      ───── 0.5s ✓
  ├─ 360search  ───── 0.8s ✓
  ├─ sogou      ───── 1.0s ✓
  ├─ bing       ───── 2.0s ✓
  └─ google     ───── 6.0s ✗ (timeout)
                    ↓
              总耗时 ~6.0s
```

任何一个启用的引擎都会参与搜索。如果 `google` 或 `wikipedia` 无法连接，每次搜索都要等它 6 秒超时。

### 4.2 引擎超时调优

```
引擎超时 (6s) < 全局请求超时 (6s) < 客户端超时 (10s, Hermes)
```

- 引擎超时略小于全局超时，确保单个引擎失败不影响整体
- 全局超时略小于客户端超时，留出网络传输和 JSON 序列化的余量

### 4.3 搜索质量验证

测试查询 `今天天气`：

```
结果数: 25
搜索引擎: {baidu, 360search, sogou}
无响应: []
响应时间: ~1.0s
```

三个引擎同时返回结果，互补覆盖，搜索质量良好。

---

## 5. Hermes (AI Agent) 集成

### 5.1 配置连接

Hermes 通过两个配置项连接 SearXNG：

**1. `~/.hermes/config.yaml`**

```yaml
web:
  backend: ''
  search_backend: 'searxng'     # 指定使用 SearXNG
  extract_backend: ''
```

**2. `~/.hermes/.env`**

```
SEARXNG_URL=http://localhost:8080
```

### 5.2 验证工具调用

在微信中发送需要实时搜索的消息即可触发 SearXNG 工具调用：

```
帮我搜索一下今天的热点新闻
```

如果 AI 回复包含实时搜索结果（而非"我的知识截止到…"），说明搜索链路正常。

### 5.3 关键命令

```bash
# 查看 Hermes 状态
hermes status

# 查看 SearXNG 日志
docker logs searxng --tail 50

# 重启 Hermes 网关（改配置后）
sudo systemctl restart hermes-gateway

# 重启 SearXNG（改配置后）
cd /home/ubuntu/searxng && sudo docker compose restart

# 直接测试 SearXNG API
curl -s "http://localhost:8080/search?q=关键词&format=json" | python3 -m json.tool | head -50
```

---

## 6. 故障排查记录

### 问题 1：容器崩溃重启循环

**现象：** `docker ps` 显示 `Restarting (1)`，搜索无响应。

**日志：**
```
Expected `str`, got `bool` - at `brand.public_instances`
ValueError: Invalid settings.yml
```

**原因：** `brand.public_instances: false` —— 新版 SearXNG (2026.6.15) schema 校验 `public_instances` 必须为字符串类型。

**修复：** 改为 `public_instances: ""`（空字符串）。

---

### 问题 2：搜索返回空结果

**现象：** API 返回 HTTP 200 + 空 JSON：
```json
{"query": "test", "results": [], "unresponsive_engines": []}
```
响应时间仅 0.2 秒（明显没有真正调用搜索引擎）。

**原因：** `use_default_settings: false` —— 关闭了所有内置默认设置，包括搜索引擎的网络请求、重试、超时等关键配置，导致搜索管线虽然启动但不工作。

**修复：** 改为 `use_default_settings: true`，让 SearXNG 加载完整的默认配置，用户配置仅做覆盖。

---

### 问题 3：搜索超时 15 秒 + 空结果

**现象：** curl 请求 15 秒后超时，日志显示：
```
ERROR:searx.engines.wikipedia: HTTP requests timeout (15s) : ConnectTimeout
```

**原因：** `use_default_settings: true` 加载了 Google、Wikipedia 等几十个默认引擎。zh.wikipedia.org 在国内无法连接，每个引擎超时 15 秒导致搜索被拖死。

**修复：**
1. 显式禁用所有海外引擎（google, wikipedia, duckduckgo 等）
2. 仅启用国内可达引擎（baidu, 360search, sogou, bing）
3. 引擎超时从 10s / 15s 降至 6s

---

### 问题 4：bot detection 报错

**现象：**
```
ERROR:searx.botdetection: X-Forwarded-For nor X-Real-IP header is set!
```

**原因：** `limiter.toml` 中 `link_token = true`，而本地请求不带反向代理头。

**修复：** 设 `link_token = false`，配合 `server.limiter: false`。

---

### 问题 5：配置残留导致引擎名错误

**现象：**
```
ERROR:searx.engines: Engine name contains underscore: "searxng_news"
```

**原因：** 手工编辑时拼写错误。SearXNG 引擎名不支持下划线。

**修复：** 删除无效引擎条目，使用搜索引擎的准确模块名（如 `bing_news` 而非 `searxng_news`）。

---

## 7. 性能基准

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 容器启动 | ❌ 崩溃重启 | ✅ 正常 |
| 搜索响应时间 | ∞ (超时) | ~1.0s |
| 返回结果数 | 0 | 21–25 |
| 活跃引擎数 | 0 (全部失效) | 3 (baidu/360search/sogou) |
| 无响应引擎 | N/A | 0 |
| 内存占用 | - | ~150MB |
| CPU 占用 | - | 可忽略 |

---

## 附录：SearXNG 搜索 API 示例

```bash
# JSON 格式搜索
curl -s "http://localhost:8080/search?q=关键词&format=json"

# 指定搜索引擎
curl -s "http://localhost:8080/search?q=关键词&format=json&engines=baidu,360search"

# 检查可用引擎列表
curl -s "http://localhost:8080/config" | python3 -m json.tool | grep -A5 '"engines"'

# 搜索 + 分页
curl -s "http://localhost:8080/search?q=关键词&format=json&pageno=2"
```
