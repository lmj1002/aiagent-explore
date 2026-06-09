# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

This is a personal AI Agent learning repository focused on bridging AI Agent concepts to real-world application. Content is organized around three dimensions: conceptual understanding (Agent architecture patterns, Tool Use, Memory, Reasoning), framework exploration (hands-on experiments with mainstream Agent frameworks), and engineering practice (observability, safety guardrails, evaluation, production deployment). See README.md for details. The primary language for documentation is Chinese.

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

As of the initial commit, this repo contains no code, build configuration, or tests. Future sessions should re-scan the repo structure when working here, as the project is expected to evolve.

## Development

No build, lint, or test commands are configured yet. When adding code, also set up the appropriate tooling and document the commands here.
