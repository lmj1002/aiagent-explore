# Build a Content Builder Agent — 代码梳理文档

## 一、项目概述

这是一个基于 LangChain `create_deep_agent` 构建的**内容创作智能体**。它能够接收用户的内容选题，自动调度研究子代理搜索互联网、收集资料，然后按照品牌规范撰写博客文章或社交媒体内容，并调用 Gemini 生图模型自动生成配图。

**核心能力：**
- 多层 Agent 协作：主代理（Content Writer）+ 子代理（Researcher）
- 声明式配置：YAML 定义子代理 + Markdown 定义记忆/技能
- 四工具协同：免费网页搜索 + 博客封面生成 + 社媒配图生成 + 文件读写
- 双模式图片生成：支持 Google 直连 / 中转站代理
- 文件系统后端：输出内容持久化到本地目录

---

## 二、文件结构

```
buildAContentBuilderAgent/
├── AGENTS.md                   # 主代理「记忆」— 品牌语调、写作规范
├── content_writer.py           # 主程序 — Agent 定义、工具、执行入口
├── subagents.yaml              # 子代理声明式配置（YAML）
├── demo_gemini_proxy.py        # Gemini 生图双模式 Demo
├── skills/                     # 技能目录（深度代理自动加载）
│   ├── blog-post/
│   │   └── SKILL.md            # 博客写作技能 — 结构、SEO、配图规范
│   └── social-media/
│       └── SKILL.md            # 社媒写作技能 — LinkedIn/X、配图规范
└── blogs/ / linkedin/ / tweets/   # 运行时生成的内容输出目录
```

---

## 三、架构总览

```
用户输入选题
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│              主代理 (Content Writer Agent)                    │
│                                                              │
│  model:        Ollama (qwen3.5:2b) ← load_llm()             │
│  memory:       AGENTS.md (品牌语调 + 写作规范)                 │
│  skills:       skills/blog-post/, skills/social-media/       │
│                                                              │
│  可用工具:                                                    │
│    - generate_cover       → Gemini 生图（博客封面）            │
│    - generate_social_image → Gemini 生图（社媒配图）            │
│    - write_file (内置)     → 写入文件                         │
│    - task() (内置)         → 委派子代理                       │
│  backend: FilesystemBackend(root_dir) → 输出到本地目录         │
└──────────────────────────┬───────────────────────────────────┘
                           │ task(subagent_type="researcher")
                           ▼
┌──────────────────────────────────────────────────────────────┐
│              子代理 (Researcher)                              │
│                                                              │
│  model:        Ollama (qwen3.5:2b) ← subagents.yaml 定义     │
│  system_prompt: subagents.yaml 中的研究者指令                  │
│                                                              │
│  可用工具:                                                    │
│    - web_search           → DuckDuckGo 免费搜索 + 网页全文抓取  │
│    - write_file (内置)     → 保存研究结果到 research/*.md      │
└──────────────────────────────────────────────────────────────┘
```

---

## 四、核心组件详解

### 4.1 `content_writer.py` — 主程序

#### 工具层（4 个工具）

| 工具 | 行数 | 功能 | 后端 |
|------|------|------|------|
| `web_search` | 33-63 | DuckDuckGo 搜索 + 网页全文抓取（Markdown） | 免费，提供给子代理使用 |
| `fetch_webpage_content` | 20-30 | HTTP GET 请求 + `markdownify` 转换 | `httpx` + `markdownify` |
| `generate_cover` | 66-93 | 生成博客封面图 → `blogs/<slug>/hero.png` | Gemini (`google.genai`) |
| `generate_social_image` | 96-123 | 生成社媒配图 → `<platform>/<slug>/image.png` | Gemini (`google.genai`) |

**关键技术点**：

| 技术点 | 说明 |
|--------|------|
| `load_subagents(config_path)` | 从 YAML 加载子代理定义，并将字符串工具名（如 `"web_search"`）映射为 Python 函数引用 |
| `load_llm()` | 从 `.env` 加载配置，返回 `ChatOpenAI` 实例指向本地 Ollama。文字生成零成本 |
| `FilesystemBackend` | 深度代理的文件系统后端，`root_dir=EXAMPLE_DIR`，所有文件读写都限定在此目录下 |
| `create_deep_agent` | 组合 model + memory + skills + tools + subagents + backend，构建完整代理 |
| `load_dotenv` | 加载 `F:\study\aiagent-explore\.env`，为 Gemini 提供 `GOOGLE_API_KEY` |

#### `load_llm()` — 本地模型加载

```python
def load_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("MODEL", "qwen3.5:2b"),
        base_url=os.getenv("BASE_URL", "http://localhost:11434/v1/"),
        api_key=os.getenv("API_KEY", "ollama"),
        temperature=0,
    )
```

所有文字生成（主代理 + 子代理）都走本地 Ollama，不消耗 API 费用。

#### `load_subagents()` — YAML 到工具的桥接

```
subagents.yaml 中的 "web_search" 字符串
        │
        ▼  load_subagents() 映射
        │
available_tools = {"web_search": web_search}  ← Python 函数对象
        │
        ▼  注入子代理
subagent["tools"] = [web_search]
```

关键设计：工具定义在 Python 文件中，子代理配置在 YAML 中，`load_subagents` 负责桥接两者。修改工具无需动 YAML，修改子代理描述无需动 Python。

### 4.2 `subagents.yaml` — 子代理声明式配置

```yaml
researcher:
  description: >
    ALWAYS use this first to research any topic before writing content.
    ...
  model: ollama:qwen3.5:2b          # 子代理使用本地 Ollama
  system_prompt: |                   # 研究员的完整行为指令
    You are a research assistant...
  tools:
    - web_search                      # 工具名 → Python 端映射
```

| 字段 | 说明 |
|------|------|
| `description` | 主代理看到的子代理描述，决定**何时**委派 |
| `model` | 子代理的模型，`ollama:qwen3.5:2b` = 本地免费 |
| `system_prompt` | 子代理的完整行为指令，包括工具列表、研究流程、停止条件 |
| `tools` | 子代理可用的工具名列表，由 `load_subagents()` 映射到 Python 函数 |

### 4.3 `AGENTS.md` — 主代理记忆（品牌规范）

作为 `memory` 参数传给 `create_deep_agent`，主代理在执行任何任务时都会遵守其中的规范：

| 模块 | 内容 |
|------|------|
| **Brand Voice** | 专业但平易近人、清晰直接、自信不自大、善用案例 |
| **Writing Standards** | 主动语态、价值先行、一段一意、具体优于抽象、结尾引导行动 |
| **Content Pillars** | AI 代理与自动化、开发者工具与效率、软件架构、新兴技术趋势 |
| **Research Requirements** | 写作前必须用 `researcher` 子代理，收集 3+ 可信来源 |

### 4.4 `skills/` — 技能目录

`create_deep_agent` 的 `skills` 参数指定技能文件路径，代理运行时自动加载。

#### `skills/blog-post/SKILL.md`

定义了博客写作的完整 SOP：

| 阶段 | 要点 |
|------|------|
| **研究** | 必须先用 `task(subagent_type="researcher")` 委派研究，结果保存到 `research/<slug>.md` |
| **结构** | Hook → Context → Main Content (3-5 节) → Practical Application → Conclusion & CTA |
| **配图** | 必须用 `generate_cover` 生成 `hero.png`，包含详细的 prompt 写作指南 |
| **SEO** | 关键词在标题和首段出现、标题 <60 字符、meta description 150-160 字符 |
| **输出** | `blogs/<slug>/post.md` + `blogs/<slug>/hero.png` |

#### `skills/social-media/SKILL.md`

定义了社媒内容的完整 SOP：

| 平台 | 规则 |
|------|------|
| **LinkedIn** | 1300 字符限制、首行 Hook、3-5 个 hashtag、专业但个人化 |
| **Twitter/X** | 280 字符/条、Threads 用 1/🧵 格式、≤2 个 hashtag |
| **配图** | 必须用 `generate_social_image`，社媒图要简洁大胆、高对比度 |
| **输出** | `linkedin/<slug>/` 或 `tweets/<slug>/`，含 `post.md` + `image.png` |

### 4.5 `demo_gemini_proxy.py` — Gemini 连接双模式 Demo

```python
def create_gemini_client() -> genai.Client:
    api_key = os.getenv("GOOGLE_API_KEY")
    proxy_base_url = os.getenv("GEMINI_BASE_URL", "").strip()

    if proxy_base_url:
        # 中转站模式
        http_opts = types.HttpOptions(base_url=proxy_base_url)
        return genai.Client(api_key=api_key, http_options=http_opts)
    else:
        # 直连模式
        return genai.Client(api_key=api_key)
```

| 模式 | `.env` 配置 | 实际请求端点 |
|------|------------|-------------|
| **直连** | 仅 `GOOGLE_API_KEY` | `https://generativelanguage.googleapis.com/v1beta/...` |
| **中转站** | + `GEMINI_BASE_URL=https://www.packyapi.com` | `https://www.packyapi.com/v1beta/...` |

> SDK 会在 `base_url` 后自动追加 `/v1beta`，中转站需要兼容此路径格式。

---

## 五、完整执行流程

```
┌─ 1. 启动 ──────────────────────────────────────────────────────────┐
│  python content_writer.py "Write a blog post about AI agents"      │
│                                                                     │
│  → load_dotenv() 加载 .env (GOOGLE_API_KEY, MODEL 等)              │
│  → create_content_writer() 构建 Agent                              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─ 2. 主代理接收任务 ─────────────────────────────────────────────────┐
│  HumanMessage: "Write a blog post about AI agents..."              │
│                                                                     │
│  主代理读取 memory (AGENTS.md) + skills (blog-post/SKILL.md)        │
│  → 理解：这是博客写作任务，需要先研究、再写作、最后配图                 │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─ 3. 委派研究 ───────────────────────────────────────────────────────┐
│  主代理调用 task(subagent_type="researcher",                        │
│      description="Research AI agents... save to research/xxx.md")  │
│                                                                     │
│  ┌─ 子代理执行 ─────────────────────────────────────────────────┐   │
│  │  1. web_search("AI agents transforming software development")│   │
│  │     → DuckDuckGo 搜索 → 获取 URL 列表                         │   │
│  │     → fetch_webpage_content(url) → HTML → Markdown           │   │
│  │  2. web_search("AI coding assistants 2025 statistics")       │   │
│  │  3. web_search("software development automation trends")     │   │
│  │  4. write_file("research/ai-agents-dev.md", 研究发现)          │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─ 4. 撰写博客 ───────────────────────────────────────────────────────┐
│  主代理 read_file("research/ai-agents-dev.md")                      │
│  → 按 blog-post SKILL.md 的结构生成文章                              │
│  → write_file("blogs/ai-agents-dev/post.md", 文章内容)              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─ 5. 生成配图 ───────────────────────────────────────────────────────┐
│  主代理调用 generate_cover(                                          │
│      prompt="Isometric 3D illustration of AI agents...",           │
│      slug="ai-agents-dev"                                          │
│  )                                                                  │
│  → genai.Client() → gemini-2.5-flash-image → hero.png              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─ 6. 输出 ───────────────────────────────────────────────────────────┐
│  最终产出:                                                          │
│  blogs/ai-agents-dev/                                               │
│  ├── post.md      ← 完整博客文章（含引用）                            │
│  └── hero.png     ← Gemini 生成的封面图                              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 六、关键技术点

### 6.1 `FilesystemBackend` — 文件系统后端

`create_deep_agent` 的 `backend` 参数将代理的读写限定在指定根目录。所有 `write_file`、`read_file` 操作都在此目录下进行。

### 6.2 `memory` vs `skills` vs `subagents`

| 参数 | 类型 | 作用 | 示例 |
|------|------|------|------|
| `memory` | 文件路径列表 | 始终加载到主代理上下文中的「长期记忆」 | `AGENTS.md` |
| `skills` | 目录路径列表 | 按需加载的技能（任务匹配时自动激活） | `skills/blog-post/` |
| `subagents` | 子代理定义列表 | 可委派的专业子代理 | `researcher` |

### 6.3 模型分层策略

```
主代理: Ollama (qwen3.5:2b)         ← 文字生成（免费）
    │
    ├── 生图工具: Gemini (直连/中转站)  ← 图片生成（API/付费）
    │
    └── 子代理: Ollama (qwen3.5:2b)   ← 网页搜索 + 资料整理（免费）
```

只有生图才走付费 API，其余全部本地免费。

### 6.4 声明式配置的好处

- **YAML → 子代理**：修改研究员行为无需改 Python 代码
- **AGENTS.md → 品牌规范**：换一个品牌只需替换 Markdown 文件
- **SKILL.md → 写作模板**：新增内容类型只需新增一个目录 + SKILL.md

---

## 七、依赖说明

| 库 | 用途 |
|----|------|
| `deepagents` | 核心框架：`create_deep_agent`、`FilesystemBackend` |
| `langchain` | 消息类型、工具装饰器 |
| `langchain_openai` | `ChatOpenAI` → Ollama 本地模型 |
| `google-genai` | Gemini 生图 SDK |
| `ddgs` | DuckDuckGo 免费搜索 |
| `httpx` + `markdownify` | 网页抓取 + HTML→MD |
| `pyyaml` | 解析 `subagents.yaml` |
| `python-dotenv` | 加载 `.env` 环境变量 |

---

## 八、运行方式

```bash
# 默认任务（写一篇 AI 代理主题博客）
python langchain/buildAContentBuilderAgent/content_writer.py

# 自定义任务
python langchain/buildAContentBuilderAgent/content_writer.py "Write a LinkedIn post about prompt engineering"

# 测试 Gemini 生图
python langchain/buildAContentBuilderAgent/demo_gemini_proxy.py
```

**`.env` 必需配置**：

```
# 本地 Ollama
MODEL=qwen3.5:2b
BASE_URL=http://localhost:11434/v1/
API_KEY=ollama

# Gemini 生图（二选一）
GOOGLE_API_KEY=AIzaSy...              # 直连：Google AI Studio 官方 key
# GEMINI_BASE_URL=https://www.packyapi.com  # 中转站：取消注释并填写
```
