# Hermes 搜索功能配置指南

两种方案全对比 + 实操步骤。

---

## 方案对比：一图看懂

| 维度 | 自建 SearXNG | 换支持搜索的中转站 |
|------|:-----------:|:-----------------:|
| **搜索质量** | ⭐⭐⭐⭐ 聚合多家，可调 | ⭐⭐⭐ 看平台能力，通常是单源 |
| **国内可用性** | ⭐⭐⭐⭐⭐ 自己的服务器 | ⭐⭐⭐ 依赖中转站线路 |
| **隐私安全** | ⭐⭐⭐⭐⭐ 数据不出服务器 | ⭐⭐ 搜索词经过中转站 |
| **稳定性** | ⭐⭐⭐⭐⭐ 自己掌控 | ⭐⭐⭐ 看平台良心 |
| **费用** | 🆓 免费 | 🆓 通常免费（已含在 API 费用里） |
| **部署难度** | ⭐⭐⭐ 需要 Docker + 配置 | ⭐ 改几个配置项就行 |
| **维护成本** | ⭐⭐⭐ 偶尔更新镜像 | ⭐ 零维护 |
| **适合谁** | 追求稳定、隐私、长期用 | 想省事、快速体验 |

**建议**：先用方案二快速体验搜索功能，再部署方案一作为长期方案。两者可以共存。

---

# 方案一：自建 SearXNG（推荐长期方案）

SearXNG 是一个开源的元搜索引擎，它自己不爬网页，而是把用户的搜索词转发给 Google/Bing/DuckDuckGo 等真实搜索引擎，然后把结果聚合返回。隐私安全 + 没有 API Key 限制 + 部署在自己服务器上国内直连。

## 1.1 架构

```
微信 → Hermes → SearXNG(你的服务器:Docker) → Bing/Google/百度...
                                              ↑
                                    Hermes 拿到聚合结果
```

## 1.2 部署 SearXNG

### 创建部署目录

```bash
mkdir -p ~/searxng && cd ~/searxng
```

### 编写 docker-compose.yml

```bash
cat > docker-compose.yml << 'EOF'
services:
  searxng:
    image: searxng/searxng:latest
    container_name: searxng
    restart: unless-stopped
    ports:
      - "127.0.0.1:8080:8080"   # 只监听本机，不暴露外网
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
EOF
```

### 生成配置

```bash
# 创建配置目录
mkdir -p searxng-config

# 生成默认配置文件
docker run --rm \
  -v $(pwd)/searxng-config:/etc/searxng:rw \
  searxng/searxng:latest \
  /bin/sh -c "if [ ! -f /etc/searxng/settings.yml ]; then cp /usr/local/searxng/searx/settings.yml /etc/searxng/; fi; if [ ! -f /etc/searxng/limiter.toml ]; then cp /usr/local/searxng/searx/limiter.toml /etc/searxng/; fi; if [ ! -f /etc/searxng/uwsgi.ini ]; then cp /usr/local/searxng/dockerfiles/uwsgi.ini /etc/searxng/; fi; echo done"
```

### 编辑 settings.yml —— 关键配置

```bash
nano searxng-config/settings.yml
```

需要修改的关键部分（完整示例见下面）：

```yaml
use_default_settings: true

general:
  instance_name: "Hermes Search"
  debug: false
  privacypolicy_url: false
  contact_url: false
  enable_metrics: false

search:
  safe_search: 0
  autocomplete: ""
  default_lang: "zh-CN"
  
  # 搜索引擎配置 —— 国内服务器重点看这里
  formats:
    - html
    - json
  
server:
  secret_key: "改成一个随机字符串，用 openssl rand -hex 32 生成"
  bind_address: "0.0.0.0"
  port: 8080
  limiter: false          # 关了限速，只有你自己用
  image_proxy: false
  # 国内服务器必须关掉 HTTP 公网验证，否则 SearXNG 启动时会连外网做检查而失败
  method: "GET"

ui:
  static_use_hash: true
  default_theme: simple
  default_locale: zh-Hans-CN

# 切换搜索引擎请求方式 —— 国内服务器关键！
outgoing:
  request_timeout: 10.0
  useragent_suffix: ""
  # 如果服务器访问外网要代理，在这配
  # proxies:
  #   http: http://你的代理地址:端口
  #   https: http://你的代理地址:端口
  # 使用 POST 方法可以绕过部分网络限制
  using_tor_proxy: false

engines:
  # 百度 —— 国内最快最稳
  - name: baidu
    engine: baidu
    shortcut: bd
    disabled: false

  # 必应 —— 中英文都行，国内可直连
  - name: bing
    engine: bing
    shortcut: bi
    disabled: false

  # 必应新闻
  - name: bing news
    engine: bing_news
    shortcut: bin
    disabled: false

  # DuckDuckGo —— 隐私友好，但国内有时慢
  - name: duckduckgo
    engine: duckduckgo
    shortcut: ddg
    disabled: false

  # Google —— 国内需要代理才能用
  - name: google
    engine: google
    shortcut: go
    disabled: true       # 没代理就关掉

  # Wikipedia 中文
  - name: wikipedia
    engine: wikipedia
    shortcut: wp
    wikipedia_url: https://zh.wikipedia.org/
    disabled: false

  # GitHub 搜索
  - name: github
    engine: github
    shortcut: gh
    disabled: false
```

**重点关注**

- `server.limiter: false` — 关了限速，个人使用不需要
- `engines` 段 — 百度、必应打开；Google 没有代理就关掉
- `outgoing.proxies` — 如果服务器本身需要代理才能访问外网，在这里配

### 生成 secret_key

```bash
# 用这个命令生成随机密钥，替换 settings.yml 里的 secret_key
openssl rand -hex 32
```

### 启动

```bash
cd ~/searxng
docker compose up -d

# 验证
docker compose ps
# 应该看到 searxng 状态是 Up

# 测试搜索（在服务器上）
curl "http://localhost:8080/search?q=test&format=json"
```

### 如果启动失败

```bash
# 看日志
docker compose logs searxng

# 常见问题：
# 1. settings.yml 格式错误 → 检查缩进（用空格不用 Tab）
# 2. 端口占用 → 换 ports 映射
# 3. 国内网络导致镜像拉取慢 → 配 Docker 镜像加速
```

## 1.3 Docker 镜像加速（国内服务器大概率需要）

```bash
# 配置 Docker 国内镜像源
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json << 'EOF'
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.xuanyuan.me"
  ]
}
EOF

sudo systemctl daemon-reload
sudo systemctl restart docker
```

## 1.4 配置 Hermes 使用 SearXNG

### 方式一：交互配置

```bash
hermes setup tools
```

找到 Search Provider，选 **SearXNG**，填入：

- **SearXNG Base URL**：`http://localhost:8080`
- 不需要 API Key（自建实例无需认证）

### 方式二：直接改配置文件

```bash
nano ~/.hermes/config.yaml
```

找到 search 或 tools 段，改成：

```yaml
search:
  provider: searxng
  searxng_base_url: "http://localhost:8080"
  searxng_api_key: ""   # 留空
```

然后重启 gateway：

```bash
sudo systemctl restart hermes-gateway
```

## 1.5 验证搜索

```bash
# 先确认 SearXNG 本身能搜
curl "http://localhost:8080/search?q=Python+asyncio&format=json" | python3 -m json.tool | head -30

# 然后在微信给 Hermes 发：
"帮我搜一下今天的科技新闻"
"搜一下 GitHub 上 star 最多的 Python 项目"
"百度搜索：Ubuntu 24.04 发布时间"
```

## 1.6 SearXNG 日常维护

```bash
# 更新镜像
cd ~/searxng
docker compose pull
docker compose up -d

# 查看日志
docker compose logs -f searxng

# 重启
docker compose restart searxng

# 停止
docker compose down
```

---

# 方案二：换支持搜索的中转站

很多中转平台（兼容 OpenAI API 格式）内置了搜索能力。换过去之后 Hermes 的搜索请求会直接走模型的 web_search 工具。

## 2.1 什么样算"支持搜索"的中转站

这类平台通常会在 API 返回模型列表时包含一个 `web_search` 或 `search` 工具。国内常见的：

| 平台 | 搜索支持 | 体验 |
|------|:-------:|------|
| **硅基流动 SiliconFlow** | ✅ DeepSeek 模型自带搜索 | 稳定 |
| **dstopology** | ✅ gpt-5.x 系列内置 | 看线路 |
| **OhMyGPT** | ✅ 多模型支持 | 稳定 |
| **APIHub** | ⚠️ 部分模型 | 一般 |
| **NanoGPT** | ✅ search 工具 | 需代理 |

> ⚠️ 中转站市场变化快，上述信息是 2026.06 的，实际以你注册后看到的为准。

## 2.2 怎么判断一个中转站有没有搜索

注册后看它的模型列表文档，找这些关键词：
- `web_search` / `search` / `online`
- `tool_choice` 支持
- 模型名带 `-search` 或 `-online` 后缀

或者直接问客服："你们的 API 支持 web_search 工具调用吗？"

## 2.3 操作步骤

### Step 1：注册并获取连接信息

以硅基流动为例（因为它对国内最友好）：

1. 打开 https://siliconflow.cn
2. 注册 → 控制台 → API 密钥 → 新建
3. 记下：
   - Base URL：`https://api.siliconflow.cn/v1`
   - API Key：`sk-xxxx`

### Step 2：在 Hermes 里添加新 Provider

```bash
hermes setup model
```

关键步骤：

1. **Provider** → 选 `custom (direct API)`
2. **Base URL** → 填中转站地址（如 `https://api.siliconflow.cn/v1`）
3. **API Key** → 填获取的密钥
4. **兼容模式** → 选 `1. Auto-detect`
5. **Model** → 选带搜索能力的模型，优先选：
   - `deepseek-ai/DeepSeek-V3`（硅基流动，有搜索功能）
   - 或列表里标注了 search/online 的模型

### Step 3：切到新 Provider 并测试

```bash
# 或者直接改 config.yaml
nano ~/.hermes/config.yaml
```

找到 `model` / `providers` 段，把新 Provider 设为默认。

### Step 4：验证

在微信里问 Hermes：
> "帮我搜索今天的 AI 新闻"
> "查一下 Python 3.13 的新特性"

如果能返回实时信息而非"我的知识截止到..."，就说明搜索生效了。

---

# 两种方案怎么选

| 你的情况 | 推荐 |
|----------|------|
| 想一劳永逸，不怕折腾 | **自建 SearXNG**（方案一） |
| 现在就想用，不想折腾 | **换中转站**（方案二） |
| 都要 | 两个都配，Hermes 支持多 Provider 切换 |
| 服务器网络差 | 方案二，因为 SearXNG 本身也要访问外网搜索引擎 |

---

# 附录：排查搜索不生效

### 搜了但没结果

```bash
# 1. 确认 SearXNG 本身能搜
curl "http://localhost:8080/search?q=hello&format=json"

# 2. 确认 Hermes 配置没写错
hermes config | grep -A5 search

# 3. 看 gateway 日志
journalctl -u hermes-gateway -n 100 --no-pager | grep -i search
```

### 搜索结果很差

SearXNG 的 `settings.yml` 里调整 `engines` 列表，把不想要的引擎关掉（`disabled: true`），只保留百度 + 必应通常就够用。

### 中转站的搜索不生效

- 确认选的模型确实支持 web_search 工具
- 在 Hermes 对话中直接问 "你的搜索工具可用吗？"
- 换一个模型试试，有些模型虽然列出来了但搜索其实是假的
