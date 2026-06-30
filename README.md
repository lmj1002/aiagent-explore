# aiagent-explore

AI Agent 应用落地与个人 AI 软件工程平台探索仓库。

## 仓库定位

本仓库用于记录和探索 AI Agent 从概念到落地的完整学习路径，内容涵盖理论认知、框架实践与工程化思考三个维度。同时作为**个人 AI 软件工程平台**的知识中枢——整合 Hermes（微信入口）、Claude Code / Codex（编码引擎）、MCP（工具协议）、RAG（知识检索），形成"微信发需求 → AI 自主编码 → 自动审查 → PR 交付"的远程工作流。

## 内容方向

### 概念认知

AI Agent 相关核心概念的学习笔记与理解，包括但不限于：

- Agent 架构范式（ReAct、Plan-and-Execute、Multi-Agent 等）
- Tool Use / Function Calling 机制
- Memory 与 Context 管理策略
- 推理与规划能力的演进

### 框架初探

主流 AI Agent 框架的初步探索与试用，通过最小可运行示例理解各框架的设计理念与适用场景：

- **LangChain**: 数据分析智能体 + 内容创作智能体（`langchain/`）
- **LangGraph**: 状态图驱动的 Agent 编排实验（`langgraph/`）
- **RAG 全流程**: 离线索引管线 + 在线推理管线（`Rag/` + `word/rag-knowledge-system.md`）

### 工程思想探索

通过代码 Demo 与文档探索 AI Agent 的工程化实践思路，关注：

- 可观测性与调试策略
- 安全护栏与可控性设计
- 评估体系与效果度量
- 生产环境部署与运维考量

### RAG 检索增强生成

基于 LangChain 实现完整的 RAG 检索链路：

- **Parent Document Retriever**: 父文档 + 子文档双层分割策略 (`Rag/judgement.py`)
- **技术栈**: HuggingFace BGE Embedding + Chroma 向量库 + LangChain
- **知识体系**: RAG 三代演进（Naive → Advanced → Modular）、切片方法、向量数据库选型、相似性算法 (`word/rag-knowledge-system.md`)

### MCP 协议与工具集成

Model Context Protocol 的实践落地，6 大 MCP Server 自动化安装与配置：

- **自动化工作流**: 环境检查 → 并行安装 → 配置生成 → 验证测试 → 报告输出 (`mcp.md`)
- **覆盖 Server**: GitHub / PostgreSQL / SQLite / Filesystem / Brave Search / Playwright
- **安全策略**: Token 通过 env 注入、配置文件 chmod 600、占位符检查
- **Harness Gateway**: MCP 与网关集成方案

### AI 代理流量监控 (Claude-Tap)

AI 代理的 "Wireshark" — API 流量拦截与交互式可视化：

- 拦截 AI CLI 工具与上游 API 之间的所有请求/响应 (`docs/claude-tap-guide.md`)
- 支持 11+ 客户端：Claude Code / Codex / Gemini / Cursor / Hermes / Qoder 等
- 实时 SSE 查看器 + 自包含 HTML 导出 + Token 用量明细

### 远程编码工作流 (Hermes + Claude Code)

微信驱动的远程编码架构设计与模型分工策略：

- **链路**: 微信 → Hermes（GPT-5.5）→ Claude Code（DeepSeek-V4）→ Workplace → Git Push (`herness/work-flow.md`)
- **分工策略**: 小需求 Hermes 直出代码（改接口/修 Bug/写脚本），大工程 Claude Code 编排执行
- **平台规划**: 分 4 阶段构建完整自主软件工程 Agent — 基础工程设施 → 质量保障 → 智能增强 → DevOps 自动化 (`herness/next-phase-implementation.md`)

### 后端面试知识体系

面向高级开发岗位的结构化面试知识库：

- **PHP 高级开发**: 7 大模块 — 语言特性 / 运行原理 / 框架核心 / 设计模式 / 性能调优 / 安全防护 / 架构设计 (`docs/backend-interview/01-php-advanced.md`)
- **Go 高级开发**: 10 大模块 — 语言核心 / 并发编程 / 运行时原理 / 标准库 / 微服务 / 数据库 / 性能调优 / 工程实践 / 消息队列 / Go vs PHP 对比 (`docs/backend-interview/02-golang-advanced.md`)

### 业务领域知识

实际业务场景的对接流程与面经整理：

- **AppsFlyer 归因对接**: 客户端 SDK + S2S/Pull/Push API + 数据模型 + 异常兜底 (`docs/appsflyer-attribution-integration.md`)
- **AppsFlyer 面试 QA**: 按面试关注维度重组的高频考点 (`docs/appsflyer-attribution-interview-qa.md`)

## Issue 驱动自动化工作流

本仓库已搭建基于 Claude Code 的 **Issue → PR 全自动化开发流水线**。从 GitHub Issue 拉取、需求分析、方案设计、代码实现、安全审查到 PR 创建，7 个阶段自动串联执行。

同时支持 Codex 作为备选编码引擎（配置见 `.codex/config.toml`）。

### 快速开始

```
/fetch-issues          # 拉取 Issue 列表
/issue 1               # 分析 Issue
/plan 1                # 生成技术方案
/auto-fix 1            # 一键自动修复（分析→编码→审查→PR）
```

### 架构

```
GitHub Issue → 分析 → 方案设计 → 编码 → 安全审查 → 代码审查 → PR
   (gh CLI)   (/issue)  (/plan) (developer) (security) (reviewer)  (gh pr)
```

详见 **[docs/issue-driven-workflow.md](docs/issue-driven-workflow.md)** — 包含完整使用指南、首次运行实录和常见问题。

## 目录结构

```
.
├── Rag/                              # RAG 检索增强生成实践
│   ├── judgement.py                  #   Parent Document Retriever 实现
│   └── 摘要索引.py                    #   摘要索引实验
├── langchain/                        # LangChain 框架实验
│   ├── buildADataAnalysisAgent.py    #   数据分析智能体
│   ├── buildAContentBuilderAgent/    #   内容创作智能体
│   └── deep-research-agent/          #   深度研究智能体
├── langgraph/                        # LangGraph 状态图实验
├── herness/                          # Hermes 部署与工作流
│   ├── work-flow.md                  #   Hermes + Claude Code 远程编码链路
│   ├── next-phase-implementation.md  #   个人 AI 软件工程平台实施方案
│   ├── hermes-install-guide.md       #   Hermes 安装指南
│   ├── hermes-config-reference.md    #   Hermes 配置参考
│   ├── hermes-search-setup.md        #   本地搜索工具配置
│   ├── SearXNG-Deployment-Guide.md   #   SearXNG 部署指南
│   └── person-style.md               #   个人风格配置
├── docs/                             # 文档中心
│   ├── backend-interview/            #   后端面试知识体系
│   ├── appsflyer-attribution-*.md    #   AppsFlyer 归因对接与面试
│   ├── claude-tap-guide.md           #   Claude-Tap 安装使用指南
│   ├── cache-cdn-warming-guide.md    #   缓存预热与 CDN 预热实战（海外短剧 + 阿里云 VOD）
│   ├── issue-driven-workflow.md      #   Issue 驱动工作流详解
│   ├── issues/                       #   Issue 分析报告
│   ├── plans/                        #   技术方案
│   └── reviews/                      #   审查报告
├── word/                             # 深度知识文档
│   ├── rag-knowledge-system.md       #   RAG 全流程知识体系
│   ├── harness-engineering.md        #   Harness 工程化实践
│   └── claude-code-workflow-ultracode.md  # Claude Code 高级工作流
├── mcp.md                            # MCP Server 自动化安装工作流
├── system-design-interview-arch.md   # 系统设计面试架构
├── .claude/                          # Claude Code 配置
│   ├── agents/                       #   子智能体定义
│   ├── commands/                     #   Slash Commands
│   ├── skills/                       #   技能
│   └── settings.json                 #   项目级配置
├── .codex/                           # Codex 配置（备选引擎）
└── .github/                          # GitHub 模板
```
