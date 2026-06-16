# aiagent-explore

AI Agent 应用落地相关知识的学习仓库。

## 仓库定位

本仓库用于记录和探索 AI Agent 从概念到落地的完整学习路径，内容涵盖理论认知、框架实践与工程化思考三个维度。

## 内容方向

### 概念认知

AI Agent 相关核心概念的学习笔记与理解，包括但不限于：

- Agent 架构范式（ReAct、Plan-and-Execute、Multi-Agent 等）
- Tool Use / Function Calling 机制
- Memory 与 Context 管理策略
- 推理与规划能力的演进

### 框架初探

主流 AI Agent 框架的初步探索与试用，通过最小可运行示例理解各框架的设计理念与适用场景。

### 工程思想探索

通过代码 Demo 探索 AI Agent 的工程化实践思路，关注：

- 可观测性与调试策略
- 安全护栏与可控性设计
- 评估体系与效果度量
- 生产环境部署与运维考量

## Issue 驱动自动化工作流

本仓库已搭建基于 Claude Code 的 **Issue → PR 全自动化开发流水线**。从 GitHub Issue 拉取、需求分析、方案设计、代码实现、安全审查到 PR 创建，7 个阶段自动串联执行。

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

仓库按主题组织，每个目录对应一个独立的学习单元，包含相关代码示例与说明文档。

## 更新日志

2026-06-17: 搭建 AI 软件工程平台 Pipeline
