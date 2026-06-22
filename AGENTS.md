# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

This is a personal AI Agent learning repository and AI software engineering platform hub. Content spans: conceptual understanding (Agent architecture, Tool Use, Memory, Reasoning), framework exploration (LangChain, LangGraph, RAG), engineering practice (observability, safety, evaluation, deployment), and a remote coding workflow that chains WeChat → Hermes → Claude Code → Git. The repo also serves as a knowledge base for backend interview prep (PHP, Go) and business domain knowledge (AppsFlyer attribution). The primary language for documentation is Chinese. See README.md for details.

## Technology Stack & Environments

### Python / LangChain (`.venv`)
- Virtual environment at `.venv/` (Python 3.11.9)
- Key dependencies: `langchain`, `langchain-huggingface`, `langchain-chroma`, `langchain-openai`, `langchain-text-splitters`, `python-dotenv`
- Activate with: `source .venv/Scripts/activate` (Git Bash) or `.venv\Scripts\activate` (cmd)
- `.env` file at repo root contains API keys and model paths (git-ignored)

### RAG Code (`Rag/`)
- `judgement.py`: Parent Document Retriever using BGE embeddings + Chroma vector store + ChatOpenAI
- `摘要索引.py`: Summary index experiment
- Local embedding model path: `D:\LLM\Local_model\BAAI\bge-large-zh-v1___5`

### MCP Tools
- `mcp.md`: Complete MCP Server automation workflow (6 servers)
- Refer to this when working with MCP tool configuration

### Remote Orchestration (Hermes + Claude Code)
- `herness/work-flow.md`: WeChat → Hermes (GPT-5.5) → Claude Code (DeepSeek-V4) architecture
- `herness/next-phase-implementation.md`: 4-phase platform build-out plan
- Codex may serve as an alternative coding engine alongside or in place of Claude Code

## Issue-Driven Development Workflow

本项目已搭建 Issue → PR 自动化开发流水线。详细架构见下方。

### Slash Commands（用户入口）

| 命令 | 用途 | 文件 |
|------|------|------|
| `/fetch-issues` | 拉取 GitHub Issue 列表，结构化展示 | `.Codex/commands/fetch-issues.md` |
| `/issue <id>` | 深度分析 Issue，输出标准化报告 | `.Codex/commands/issue.md` |
| `/plan <id>` | 基于分析生成技术方案 | `.Codex/commands/plan.md` |
| `/review` | 审查当前改动，输出合并决策 | `.Codex/commands/review.md` |
| `/auto-fix <id>` | 一键启动全自动流水线 | `.Codex/commands/auto-fix.md` |

### Sub-agents（角色定义）

| Agent | 职责 | 文件 |
|-------|------|------|
| `architect` | 系统架构师 — 方案设计 | `.Codex/agents/architect.md` |
| `developer` | 高级工程师 — 代码实现 | `.Codex/agents/developer.md` |
| `security` | 安全专家 — 漏洞审查 | `.Codex/agents/security.md` |
| `reviewer` | 代码审查 — 合并决策 | `.Codex/agents/reviewer.md` |
| `issue_developer` | 编排器 — 7阶段流水线调度 | `.Codex/agents/issue_developer.md` |

### 自动化流水线（7 阶段）

```
Phase 0: Issue 拉取与验证     → gh issue view
Phase 1: Issue 深度分析       → /issue 逻辑
Phase 2: 方案设计              → architect agent
Phase 3: 创建分支 + 编码       → git checkout -b + developer agent
Phase 4: 安全审查              → security agent (失败回路 ≤3次)
Phase 5: 代码审查              → reviewer agent (失败回路 ≤2次)
Phase 6: Push + 创建 PR        → git push + gh pr create
Phase 7: 交付摘要
```

### 输出文件结构

```
docs/
├── issues/
│   └── analysis-{issue_id}.md    # Phase 1 输出
├── plans/
│   └── plan-{issue_id}.md        # Phase 2 输出
└── reviews/
    ├── security-{issue_id}.md    # Phase 4 输出
    └── review-{issue_id}.md      # Phase 5 输出
```

### 工具链依赖

- **GitHub CLI** (`gh`): Issue 拉取、PR 创建、标签管理
- **Git**: 分支管理、代码提交
- **Codex Agent**: 子智能体调度

### 当前限制

- 需手动执行 `gh auth login` 完成 GitHub 认证（一次性）
- 项目尚无测试框架配置（developer.md 中"执行测试"暂为占位）
- 暂未配置定时巡检 Cron（Phase 3 待实现）
- 分支管理策略待定义（Base 分支、冲突处理）

## Repository State

The repo now contains Python code (LangChain RAG pipeline, data analysis agents), documentation across multiple domains (AI Agent theory, backend interviews, AppsFlyer business knowledge, MCP protocol, Claude-Tap monitoring, Hermes orchestration), and AI tooling configuration (Codex agents/commands, Claude Code agents/commands/skills). No automated tests or CI/CD pipelines are configured yet.

### Key Documentation Files

| 文件 | 内容 |
|------|------|
| `docs/backend-interview/01-php-advanced.md` | PHP 高级开发面试知识架构 |
| `docs/backend-interview/02-golang-advanced.md` | Go 高级开发面试知识架构 |
| `docs/appsflyer-attribution-integration.md` | AppsFlyer 归因对接全流程 |
| `docs/appsflyer-attribution-interview-qa.md` | AppsFlyer 面试高频考点 |
| `docs/claude-tap-guide.md` | Claude-Tap 安装与使用指南 |
| `docs/issue-driven-workflow.md` | Issue 驱动工作流详解 |
| `herness/work-flow.md` | Hermes + Claude Code 远程编码工作流 |
| `herness/next-phase-implementation.md` | 个人 AI 软件工程平台实施方案 |
| `mcp.md` | MCP Server 自动化安装工作流 |
| `word/rag-knowledge-system.md` | RAG 全流程知识体系 |

## Development

### Python
- Virtual environment: `.venv/` (Python 3.11.9)
- Install deps: `pip install -r requirements.txt` (if present) or install individually
- RAG scripts: `python Rag/judgement.py` (requires local embedding model)

### Documentation
- All docs are Markdown, primarily in Chinese
- Follow existing doc structure conventions when adding new docs
