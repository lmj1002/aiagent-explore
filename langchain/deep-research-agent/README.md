# Deep Research Agent - 代码梳理文档

## 一、项目概述（https://docs.langchain.com/oss/python/deepagents/deep-research#next-steps）

这是一个基于 LangChain `deepagents` 库构建的**深度研究代理**。它能够接收用户的研究问题，自动规划、搜索、整合信息，最终生成一份带有完整引用的综合研究报告。

**核心能力：**
- 自动拆解研究问题为子任务
- 委派给子代理并行搜索互联网
- 抓取网页全文并转换为 Markdown
- 合并引用、生成结构化最终报告

---

## 二、文件结构

```
deep-research-agent/
├── agent.py       # 英文原版（可执行）
├── agent_cn.py    # 中文提示词版（可执行）
└── README.md      # 本文档
```

两个代码文件逻辑完全一致，区别仅在于所有提示词（system prompt）和工具名称从英文替换为中文。

---

## 三、架构总览

```
用户输入研究问题
       │
       ▼
┌──────────────────────────────────────┐
│          主代理 (Deep Agent)          │
│                                      │
│  系统提示 = 研究工作流指令             │
│          + 子代理协调指令              │
│                                      │
│  可用工具:                            │
│    - web_search / tavily_search      │
│    - write_todos (内置)              │
│    - write_file  (内置)              │
│    - task()      (内置)              │
└──────────────────┬───────────────────┘
                   │ task() 委派
                   ▼
┌──────────────────────────────────────┐
│        子代理 (research-agent)        │
│                                      │
│  系统提示 = 研究员指令                 │
│                                      │
│  可用工具:                            │
│    - web_search / tavily_search      │
│                                      │
│  职责: 搜索互联网 → 收集信息 →        │
│        返回带引用的结构化发现           │
└──────────────────────────────────────┘
```

---

## 四、核心方法与组件详解

### 4.1 `fetch_webpage_content(url, timeout=10.0)` — 网页内容抓取

| 项目 | 说明 |
|------|------|
| **位置** | agent.py:22-32 |
| **功能** | 通过 HTTP GET 请求获取指定 URL 的网页内容，并使用 `markdownify` 库将 HTML 转换为 Markdown 格式 |
| **输入** | `url` (字符串) — 目标网页地址；`timeout` (浮点数) — 请求超时时间，默认10秒 |
| **输出** | 成功时返回网页的 Markdown 文本；失败时返回错误信息字符串 |
| **依赖** | `httpx`（HTTP客户端）、`markdownify`（HTML→MD转换） |
| **注意** | 设置了浏览器 User-Agent 头以模拟正常浏览器访问，避免被部分网站拒绝 |

### 4.2 `tavily_search(query, max_results=3)` — 网络搜索工具

| 项目 | 说明 |
|------|------|
| **位置** | agent.py:35-66（英文版）/ agent_cn.py:36-63（中文版 `web_search`） |
| **功能** | 组合"搜索引擎查询 + 网页全文抓取"两步操作，是子代理进行研究的核心工具 |
| **输入** | `query` (字符串) — 搜索查询词；`max_results` (整数) — 最大结果数，默认3 |
| **输出** | 格式化字符串，包含结果数量、每个结果的标题、URL和完整Markdown内容 |
| **装饰器** | `@tool(parse_docstring=True)` — LangChain 工具装饰器，自动解析 docstring 生成工具描述 |
| **流程** | ① 调用 DuckDuckGo API 获取搜索结果列表 → ② 遍历结果，对每个URL调用 `fetch_webpage_content()` 获取全文 → ③ 拼接所有结果为一个格式化字符串返回 |
| **注意** | 虽然函数名保留了 `tavily_search`（来自原始 Tavily API 设计），但实际使用的是 DuckDuckGo 作为搜索后端。中文版已重命名为 `web_search` |

### 4.3 `load_llm()` — 大语言模型加载

| 项目 | 说明 |
|------|------|
| **位置** | agent.py:191-198 |
| **功能** | 从环境变量加载 LLM 配置，初始化 ChatOpenAI 实例 |
| **配置项** | `MODEL` — 模型名称（默认 `qwen3.5:2b`）；`BASE_URL` — API地址（默认 `http://localhost:11434/v1/`）；`API_KEY` — API密钥（默认 `ollama`） |
| **环境文件** | 从项目根目录的 `.env` 文件加载（通过 `load_dotenv`） |
| **设计意图** | 默认指向本地 Ollama 服务，方便离线运行；也可通过修改环境变量对接任何兼容 OpenAI API 的服务 |

---

## 五、提示词体系（三层结构）

整个系统的行为由三层提示词共同定义：

### 层次关系

```
INSTRUCTIONS (主代理系统提示)
├── RESEARCH_WORKFLOW_INSTRUCTIONS (工作流层：定义6步研究流程 + 报告模板)
└── SUBAGENT_DELEGATION_INSTRUCTIONS (协调层：定义子代理委派策略 + 并发限制)
                                          │
                                          │ task() 委派时注入
                                          ▼
                              RESEARCHER_INSTRUCTIONS (执行层：子代理的行为指令)
```

### 5.1 `RESEARCH_WORKFLOW_INSTRUCTIONS` — 研究工作流指令（协调器层）

**位置**: agent.py:70-132

定义了完整的 6 步研究流程：

| 步骤 | 动作 | 说明 |
|------|------|------|
| 1 | **制定计划** | 使用 `write_todos` 拆解研究任务 |
| 2 | **保存请求** | 使用 `write_file()` 将用户问题保存到 `/research_request.md` |
| 3 | **执行研究** | 使用 `task()` 委派子代理进行实际搜索（主代理自己不搜索） |
| 4 | **汇总整合** | 审查所有子代理发现，统一分配引用编号 |
| 5 | **撰写报告** | 将综合报告写入 `/final_report.md` |
| 6 | **验证检查** | 重新读取研究请求，确认完整性 |

同时定义了三种报告模板：
- **对比分析类**：引言 → A概述 → B概述 → 详细对比 → 结论
- **列表/排名类**：直接列举，无需引言
- **综述/概述类**：主题概述 → 核心概念1/2/3 → 结论

引用规范：使用 `[1]`, `[2]` 格式内联引用，末尾 `### Sources` 章节汇总。

### 5.2 `SUBAGENT_DELEGATION_INSTRUCTIONS` — 子代理协调指令（策略层）

**位置**: agent.py:200-235

定义子代理的委派策略：

| 规则 | 内容 |
|------|------|
| **默认策略** | 偏向使用 **1 个子代理**，避免过早拆分 |
| **何时并行** | 仅在①明确对比（如 "A vs B"）或②地理分散维度时并行 |
| **并发上限** | 每次迭代最多 `max_concurrent_research_units`（3）个并行子代理 |
| **轮次上限** | 最多 `max_researcher_iterations`（3）轮委派后必须停止 |
| **停止条件** | 有足够信息全面回答时即停止，偏向聚焦而非穷尽 |

### 5.3 `RESEARCHER_INSTRUCTIONS` — 研究员指令（执行层）

**位置**: agent.py:134-178

定义子代理的具体行为：

| 规则 | 内容 |
|------|------|
| **搜索策略** | 先宽后窄：从宽泛查询开始 → 每次搜索后评估 → 逐步细化 |
| **调用的预算** | 简单查询 2-3 次 / 复杂查询最多 5 次搜索调用 |
| **停止条件** | 能全面回答 / 有3+相关来源 / 最近2次搜索返回相似信息 |
| **输出格式** | 结构化发现 + 内联引用 + `### Sources` 章节 |

---

## 六、执行流程（完整时序）

```
┌─ 用户启动 ──────────────────────────────────────────────────────────┐
│  agent.invoke({"messages": [HumanMessage(content="研究问题")]})       │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ 步骤1: 规划 ────────────────────────────────────────────────────────┐
│  主代理分析问题 → 调用 write_todos 拆解为子任务列表                     │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ 步骤2: 保存 ────────────────────────────────────────────────────────┐
│  主代理调用 write_file("/research_request.md", 问题内容)               │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ 步骤3: 委派研究 ────────────────────────────────────────────────────┐
│  主代理调用 task(subagent_type="research-agent", description=...)    │
│                                                                      │
│  ┌─ 子代理执行 ──────────────────────────────────────────────────┐   │
│  │  1. 理解研究主题                                               │   │
│  │  2. 调用 web_search("宽泛查询")           ← DuckDuckGo API    │   │
│  │  3. fetch_webpage_content(url)            ← 网页全文抓取       │   │
│  │  4. 评估结果 → 调用 web_search("细化查询")                     │   │
│  │  5. 重复直到满足停止条件                                        │   │
│  │  6. 返回结构化发现（含引用）给主代理                             │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  （如果需要多个维度研究，主代理并行调用多个子代理）                      │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ 步骤4: 整合 ────────────────────────────────────────────────────────┐
│  主代理收集所有子代理返回的发现 → 去重URL → 重新分配引用编号            │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ 步骤5: 撰写报告 ────────────────────────────────────────────────────┐
│  主代理调用 write_file("/final_report.md", 综合报告内容)              │
│  按报告类型（对比/列表/综述）选择合适的模板结构                         │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ 步骤6: 验证 ────────────────────────────────────────────────────────┐
│  主代理 read_file("/research_request.md") → 逐项核对 → 确认完成        │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ 输出 ───────────────────────────────────────────────────────────────┐
│  返回最终消息列表，打印所有 content 到控制台                            │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 七、关键配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_concurrent_research_units` | 3 | 每轮迭代中允许的最大并行子代理数量 |
| `max_researcher_iterations` | 3 | 子代理委派的最大轮次，超出后必须停止 |
| `timeout` | 10.0s | 单个网页抓取的 HTTP 请求超时时间 |
| `max_results` | 3 | 每次搜索返回的最大结果数 |
| `temperature` | 0 | LLM 的温度参数（0 = 确定性输出） |

---

## 八、依赖说明

| 库 | 用途 |
|----|------|
| `deepagents` | 核心框架，提供 `create_deep_agent`（含子代理委派、文件读写等内置工具） |
| `langchain` | 消息类型（HumanMessage）和工具装饰器（@tool） |
| `langchain_openai` | LLM 客户端（ChatOpenAI），兼容 OpenAI API 格式 |
| `httpx` | 异步 HTTP 客户端，用于网页抓取 |
| `markdownify` | HTML → Markdown 格式转换 |
| `ddgs` | DuckDuckGo 搜索 Python 封装 |
| `python-dotenv` | 从 `.env` 文件加载环境变量 |

---

## 九、两种版本对比

| 维度 | agent.py | agent_cn.py |
|------|----------|-------------|
| 搜索工具名 | `tavily_search` | `web_search` |
| 协调器提示词 | 英文 | 中文 |
| 子代理提示词 | 英文 | 中文 |
| 协调指令 | 英文 | 中文 |
| 工具描述 | 英文 | 中文 |
| 示例问题 | 英文（RAG vs Fine-tuning） | 中文（RAG和微调的区别） |
| 代码逻辑 | 完全一致 | 完全一致 |

---

## 十、运行方式

```bash
# 1. 确保项目根目录有 .env 文件（或使用默认 Ollama 配置）
# 2. 运行英文版
python deep-research-agent/agent.py

# 3. 运行中文版
python deep-research-agent/agent_cn.py
```

**环境变量配置（`.env`）：**

```
MODEL=qwen3.5:2b           # 模型名称
BASE_URL=http://localhost:11434/v1/  # API地址
API_KEY=ollama             # API密钥
```

---

## 十一、拓展：LLM 连接范式与最佳实践

### 11.1 当前写法的问题

当前 `load_llm()` 使用 `ChatOpenAI` + Ollama 默认地址，虽然能正常工作，但存在以下改善空间：

| 问题 | 说明 |
|------|------|
| **硬编码 ChatOpenAI** | 即使后端是 Ollama 本地模型，也走 OpenAI 兼容层。虽然能跑，但丢失了 Ollama 原生特性（如 `num_ctx` 上下文窗口配置、`keep_alive` 会话保持等参数）。 |
| **重复代码** | 三个文件（`agent.py`、`agent_cn.py`、`buildADataAnalysisAgent.py`）各有一份完全相同的 `load_llm()`，修改时需要同步三处。 |
| **注释掉的 dead code** | `agent.py:190` 的 `init_chat_model` 行已被注释，但 `from langchain.chat_models import init_chat_model` 的 import 语句仍然存在，属于无效代码。 |
| **无 provider 抽象** | 想从 Ollama 切换到 OpenAI，需要改代码而非改配置，不符合开闭原则。 |

### 11.2 改进方案

#### 方案一：使用 `ChatOllama`（纯本地 Ollama 场景）

如果确定只用 Ollama 本地模型，使用专用的 `ChatOllama` 是最佳选择，它支持 Ollama 的全部原生参数：

```python
from langchain_ollama import ChatOllama

def load_llm() -> ChatOllama:
    load_dotenv()
    return ChatOllama(
        model=os.getenv("OLLAMA_MODEL", "qwen3.5:2b"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        temperature=0,
        num_ctx=4096,      # 上下文窗口大小
        keep_alive="10m",  # 模型在内存中保持的时间
    )
```

> **适用场景**：纯本地部署，不需要切换云端提供商。

#### 方案二：使用 `init_chat_model`（多提供商切换，推荐）

LangChain 内置的 `init_chat_model` 通过 `provider:model` 前缀的单个字符串即可切换所有提供商，是官方推荐的多提供商方案：

```python
from langchain.chat_models import init_chat_model

def load_llm() -> BaseChatModel:
    load_dotenv()
    return init_chat_model(
        model=os.getenv("LLM_PROVIDER", "ollama:qwen3.5:2b"),
        temperature=0,
    )
```

**切换方式**——只需修改环境变量，无需动代码：

| 场景 | `LLM_PROVIDER` 值 |
|------|-------------------|
| 本地 Ollama | `ollama:qwen3.5:2b` |
| OpenAI | `openai:gpt-4o` |
| Anthropic | `anthropic:claude-sonnet-4-6` |
| Google Gemini | `google_genai:gemini-3.5-flash` |
| DeepSeek | `openai:deepseek-chat` |

> **适用场景**：需要在本地模型和云端模型之间灵活切换，一套代码适配所有提供商。

#### 方案三：工厂模式（最灵活）

对于需要精细控制每个提供商参数的生产项目，可用工厂模式显式选择不同的 Chat 类：

```python
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

def load_llm() -> BaseChatModel:
    load_dotenv()
    provider = os.getenv("LLM_PROVIDER", "ollama")

    if provider == "ollama":
        return ChatOllama(
            model=os.getenv("OLLAMA_MODEL", "qwen3.5:2b"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            temperature=0,
        )
    elif provider == "openai":
        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            api_key=os.getenv("OPENAI_API_KEY"),
            temperature=0,
        )
    elif provider == "anthropic":
        return ChatAnthropic(
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            temperature=0,
        )
    else:
        raise ValueError(f"不支持的 LLM 提供商: {provider}")
```

> **适用场景**：需要利用各提供商的专有参数（如 Anthropic 的 thinking 模式、caching 等高级特性）。

#### 方案对比

| 维度 | 方案一 ChatOllama | 方案二 init_chat_model | 方案三 工厂模式 |
|------|-------------------|------------------------|----------------|
| 代码量 | 最少 | 中等 | 较多 |
| 可切换提供商 | 否 | 是（改环境变量） | 是（改环境变量） |
| 支持专有参数 | 是（Ollama专属） | 有限 | 是（完整） |
| 适合场景 | 纯本地 | 学习/实验 | 生产环境 |

### 11.3 本地模型 vs 运营商模型的连接范式

#### 本地模型连接架构

```
┌──────────────────┐     OpenAI-compatible API     ┌──────────────────────────┐
│   Python 代码     │ ─────────────────────────────→│  本地推理服务              │
│                  │                               │                          │
│  ChatOpenAI      │  base_url=http://localhost:   │  Ollama / vLLM /         │
│  或               │  11434/v1/                   │  LM Studio / llama.cpp   │
│  ChatOllama      │                               │                          │
└──────────────────┘                               └──────────────────────────┘

核心特征：
- 无需真实 API Key（或使用占位符如 "ollama"）
- base_url 指向 localhost
- 模型名是本地拉取的模型 tag（如 qwen3.5:2b、llama3:8b）
- 数据不出本机，隐私有保障
- 延迟取决于本地 GPU/CPU 性能
```

**主流本地推理服务连接对照**：

| 服务 | ChatOllama base_url | ChatOpenAI base_url | 备注 |
|------|---------------------|---------------------|------|
| **Ollama** | `http://localhost:11434` | `http://localhost:11434/v1` | 两种连接方式都原生支持，ChatOllama 方式可配置更多参数 |
| **vLLM** | 不适用 | `http://localhost:8000/v1` | 仅提供 OpenAI 兼容接口 |
| **LM Studio** | 不适用 | `http://localhost:1234/v1` | 仅提供 OpenAI 兼容接口 |
| **llama.cpp** | 不适用 | `http://localhost:8080/v1` | 需启动 server 模式 |

#### 运营商模型连接架构

```
┌──────────────────┐     专用 SDK / REST API      ┌──────────────────────────┐
│   Python 代码     │ ─────────────────────────────→│  云端推理服务              │
│                  │                               │                          │
│  ChatOpenAI      │  api_key=sk-xxx              │  OpenAI API              │
│  ChatAnthropic   │  api_key=sk-ant-xxx          │  Anthropic API           │
│  ChatGoogle      │  api_key=xxx                 │  Google Gemini API       │
└──────────────────┘                               └──────────────────────────┘

核心特征：
- 需要有效的 API Key（付费）
- 不需要本地 GPU
- 模型名是云端标识（如 gpt-4o、claude-sonnet-4-6、gemini-3.5-flash）
- 数据经过公网传输（需关注合规性）
- 延迟取决于网络质量和云端负载
- 按 token 计费
```

**主流运营商 SDK 对照**：

| 提供商 | LangChain 类 | pip 包 | 核心环境变量 |
|--------|-------------|--------|-------------|
| OpenAI | `ChatOpenAI` | `langchain-openai` | `OPENAI_API_KEY` |
| Anthropic | `ChatAnthropic` | `langchain-anthropic` | `ANTHROPIC_API_KEY` |
| Google Gemini | `ChatGoogleGenerativeAI` | `langchain-google-genai` | `GOOGLE_API_KEY` |
| Azure OpenAI | `AzureChatOpenAI` | `langchain-openai` | `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT` |
| DeepSeek | `ChatOpenAI`（兼容） | `langchain-openai` | `DEEPSEEK_API_KEY`（需手动设置 base_url） |

### 11.4 推荐的最佳实践

**对于学习/实验项目（本项目的场景）**：推荐使用 `init_chat_model`（方案二）。一个环境变量即可切换所有提供商，代码改动最小，学习曲线最平缓。

**切换到 OpenAI 只需两步**：

```bash
# 1. 设置环境变量（或写入 .env）
export OPENAI_API_KEY=sk-xxx
export LLM_PROVIDER=openai:gpt-4o

# 2. 直接运行，代码零改动
python deep-research-agent/agent.py
```

**对于生产项目**：推荐使用专用 Chat 类的工厂模式（方案三），因为：
- 生产环境通常有固定的提供商，不需要频繁切换
- 可以充分利用各提供商的专有特性（如 Anthropic 的 prompt caching、extended thinking）
- 类型提示更精确，IDE 支持更好
- 不受 `init_chat_model` 内部行为变化的影响
