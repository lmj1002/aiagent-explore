# Deep Agent from Scratch — 5 步渐进式构建数据分析智能体

本项目基于 LangChain 官方教程 [Deep Agent from Scratch](https://docs.langchain.com/oss/python/deepagents/deep-agent-from-scratch) 的核心思路，用本地化方式从零构建一个数据分析智能体。通过 5 个独立步骤，逐步叠加 Middleware 中间件，展示从"最小化 Agent"到"完整中间件栈"的演进过程。

---

## 一、架构概览

```
用户输入数据分析任务
         |
         v
+------------------------------------------------------------------+
|                     Agent 执行循环                                |
|                                                                  |
|  +----------+  +----------+  +----------+  +----------+          |
|  |  Step 1  |  |  Step 2  |  |  Step 3  |  |  Step 4  |         |
|  | Minimal  |  |  Filesys |  |Summarize |  |  Skills  |         |
|  |  Agent   |  |  -tem    |  |  -ation  |  |  System  |         |
|  +----------+  +----------+  +----------+  +----------+          |
|                                                                  |
|  +----------+  +----------+                                      |
|  |  Step 5  |  |  Step 5  |                                      |
|  | TodoList |  |  Sub-    |                                      |
|  |          |  |  Agent   |                                      |
|  +----------+  +----------+                                      |
+----------------------------+-------------------------------------+
                             |
                             v
+------------------------------------------------------------------+
|                    FilesystemBackend                              |
|  (本地目录 sandbox/ 替代在线 LangSmithSandbox)                    |
|                                                                  |
|  - read_file("sales_data.csv")   读取 CSV 数据                   |
|  - write_file("report.md", ...)  写入分析报告                    |
|  - glob("*.csv")                 列出数据文件                    |
+------------------------------------------------------------------+
```

## 二、5 步递进构建

### Step 1: 最小化 Agent（基础循环）

```python
agent = create_agent(model=llm, tools=[])
```

- 无工具、无中间件
- 仅具备基础的 LLM 对话能力
- 验证模型连接和 Agent 基础运行流程

### Step 2: 添加文件系统中间件

```python
agent = create_agent(
    model=llm,
    tools=[],
    middleware=[FilesystemMiddleware(backend=backend)],
)
```

- `FilesystemBackend` 替代文档中的 `LangSmithSandbox`，将云端沙箱替换为本地目录 `sandbox/`
- 注入文件操作工具：`read_file`、`write_file`、`glob` 等
- Agent 可以读写本地文件，为数据分析提供数据访问能力

### Step 3: 添加上下文压缩中间件

```python
agent = create_agent(
    model=llm,
    tools=[],
    middleware=[
        FilesystemMiddleware(backend=backend),
        SummarizationMiddleware(model=llm, backend=backend),
    ],
)
```

- `SummarizationMiddleware` 自动监控对话历史长度
- 当对话 Token 超过阈值时，自动对历史消息做摘要压缩
- 防止长对话超出 LLM 上下文窗口限制

### Step 4: 添加技能系统中间件

```python
agent = create_agent(
    model=llm,
    tools=[],
    middleware=[
        FilesystemMiddleware(backend=backend),
        SummarizationMiddleware(model=llm, backend=backend),
        SkillsMiddleware(backend=backend, sources=["<skills_dir>"]),
    ],
)
```

- `SkillsMiddleware` 从指定目录按需加载领域知识
- `skills/data-analysis/SKILL.md` 包含 pandas 和 matplotlib 的常用模式
- Agent 在数据分析任务中自动注入 SKILL.md 内容，提升分析质量

> 注：实际代码中 `<skills_dir>` 使用基于 `__file__` 的绝对路径，避免运行时当前工作目录的差异。

### Step 5: 添加任务清单 + 子智能体中间件（完整版）

```python
agent = create_agent(
    model=llm,
    tools=[],
    middleware=[
        FilesystemMiddleware(backend=backend),                 # 1. 文件系统
        SummarizationMiddleware(model=llm, backend=backend),   # 2. 上下文压缩
        SkillsMiddleware(backend=backend, sources=["<skills_dir>"]), # 3. 技能系统
        TodoListMiddleware(),                                   # 4. 任务清单
        SubAgentMiddleware(backend=backend, subagents=[visualizer]), # 5. 子智能体
    ],
)
```

- `TodoListMiddleware` 提供任务创建、更新、完成追踪能力
- `SubAgentMiddleware` 注入 `visualizer` 子智能体，专注于图表生成
- 主 Agent 可以将可视化任务委派给子智能体，实现分工协作

## 三、中间件栈（执行顺序与职责）

中间件按注册顺序形成管道（Pipeline），每个请求依次经过各中间件处理：

```
请求进入
    |
    v
1. FilesystemMiddleware      -- 注入文件读写工具，管理 sandbox 数据目录
    |
    v
2. SummarizationMiddleware   -- 检查对话长度，必要时压缩历史消息
    |
    v
3. SkillsMiddleware          -- 分析用户意图，从 skills/ 加载相关技能知识
    |
    v
4. TodoListMiddleware        -- 管理任务清单（创建/更新/完成）
    |
    v
5. SubAgentMiddleware        -- 支持将任务委派给专门子智能体
    |
    v
请求交给 LLM 处理
```

**各中间件职责：**

| 中间件 | 来源 | 职责 |
|--------|------|------|
| `FilesystemMiddleware` | `deepagents.middleware` | 注入文件操作工具、管理本地文件系统 |
| `SummarizationMiddleware` | `deepagents.middleware` | 自动压缩过长的对话历史 |
| `SkillsMiddleware` | `deepagents.middleware` | 按需加载领域技能知识 |
| `TodoListMiddleware` | `langchain.agents.middleware` | 任务清单追踪与管理 |
| `SubAgentMiddleware` | `deepagents.middleware` | 子智能体委派与协作 |

## 四、依赖说明

| 库 | 用途 |
|----|------|
| `deepagents` | 核心框架，提供 Middleware 中间件和 Backend |
| `langchain` | `create_agent` 和消息类型（HumanMessage） |
| `langchain_openai` | LLM 客户端（ChatOpenAI），兼容 OpenAI API 格式 |
| `python-dotenv` | 从 `.env` 文件加载环境变量 |
| `pandas` | 数据分析（SKILL.md 中使用） |
| `matplotlib` | 数据可视化（SKILL.md 中使用） |

## 五、运行方式

```bash
# 1. 确保项目根目录有 .env 文件（或使用默认 Ollama 配置）
# 2. 确保 langchain/sales_data.csv 文件存在
# 3. 运行指定步骤

# 运行 Step 1（最小化 Agent）
python langchain/buildADeepAgentFromScratch/agent.py --step 1

# 运行 Step 2（文件系统）
python langchain/buildADeepAgentFromScratch/agent.py --step 2

# 运行 Step 3（上下文压缩）
python langchain/buildADeepAgentFromScratch/agent.py --step 3

# 运行 Step 4（技能系统）
python langchain/buildADeepAgentFromScratch/agent.py --step 4

# 运行 Step 5（完整版，默认）
python langchain/buildADeepAgentFromScratch/agent.py --step 5

# 使用自定义任务
python langchain/buildADeepAgentFromScratch/agent.py --step 5 --task "读取 sales_data.csv，计算每种产品的收入占比，生成饼图"
```

**环境变量配置（`.env`）：**

```
MODEL=qwen3.5:2b
BASE_URL=http://localhost:11434/v1/
API_KEY=ollama
```

## 六、本地化适配说明

### 主要替换

| 文档原版 | 本地实现 | 说明 |
|----------|----------|------|
| `LangSmithSandbox` | `FilesystemBackend(root_dir="./sandbox")` | 云端沙箱到本地目录 |
| `anthropic:claude-sonnet-4-6` | `qwen3.5:2b` (Ollama) | 云端模型到本地模型 |
| `backend.upload("sales.csv", data)` | `shutil.copy2(...)` | API 上传到文件拷贝 |
| `create_agent(model, tools, middleware)` | 完全一致 | core API 无变化 |

### 与 `create_deep_agent` 的区别

本项目使用 `langchain.agents.create_agent` + 手动组装 `middleware` 参数，而不是 `deepagents.create_deep_agent`。两者区别：

| 维度 | `create_agent` | `create_deep_agent` |
|------|---------------|---------------------|
| 来源 | `langchain.agents` | `deepagents` |
| Middleware | 手动组装（本 demo 的核心） | 自动组装 |
| 适用场景 | 学习/实验，展示中间件栈 | 生产快速搭建深度研究 Agent |
| 灵活性 | 高，可精确控制中间件顺序 | 低，使用内置默认顺序 |

## 七、文件结构

```
buildADeepAgentFromScratch/
  agent.py                     # 核心实现：5 步渐进式构建
  skills/
    data-analysis/
      SKILL.md                 # Step 4 技能系统：pandas+matplotlib 领域知识
  sandbox/                     # 自动创建：FilesystemBackend 工作目录
    sales_data.csv             # 示例数据（自动从上级目录拷贝）
  README.md                    # 本文档
```

## 八、参考链接

- [LangChain Deep Agent from Scratch 官方文档](https://docs.langchain.com/oss/python/deepagents/deep-agent-from-scratch)
- [LangChain create_agent API 参考](https://docs.langchain.com/oss/python/deepagents/create_agent)
- [Deep Agents 中间件文档](https://docs.langchain.com/oss/python/deepagents/middleware)
