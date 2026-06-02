# Issue 驱动自动化开发工作流

基于 Claude Code 搭建的 Issue → PR 全自动化流水线。从 GitHub Issue 拉取到代码提交、审查、PR 创建，7 个阶段全自动执行。

---

## 概述

```
GitHub Issue → 分析 → 方案设计 → 编码 → 安全审查 → 代码审查 → PR
   (gh CLI)    (/issue)  (/plan)  (developer) (security)  (reviewer)  (gh pr)
```

**一句话**: 输入 Issue 编号，输出一个可合并的 Pull Request。

---

## 架构总览

### 7 阶段流水线

```
┌──────────────────────────────────────────────────────────┐
│  Phase 0   Issue 拉取与验证        gh issue view        │
│  Phase 1   Issue 深度分析          /issue 命令          │
│  Phase 2   技术方案设计            architect agent      │
│  Phase 3   创建分支 + 编码实现     developer agent      │
│  Phase 4   安全审查                security agent       │
│  Phase 5   代码审查                reviewer agent       │
│  Phase 6   Push + 创建 PR         git push + gh pr     │
│  Phase 7   交付摘要                输出报告             │
└──────────────────────────────────────────────────────────┘
```

### 失败回路

```
Security 不通过 ──→ Developer 修复 ──→ 重审 (≤3次)
Reviewer REJECT ──→ Architect/Developer 重构 ──→ 重审 (≤2次)
重试耗尽          ──→ 标记 help-wanted，人工介入
```

### 门禁点

| 节点 | 类型 | 说明 |
|------|------|------|
| Phase 2 → 3 | 🔴 Plan 确认 | 展示改动清单和风险，等待人工确认 |
| Phase 4 重试耗尽 | 🟡 安全兜底 | P0/P1 风险无法自动修复时暂停 |
| Phase 6 | 🟡 PR 确认 | 展示最终 diff 摘要 |

---

## 文件结构

```
.claude/
├── agents/                     # 子智能体定义
│   ├── issue_developer.md      # 编排器（7阶段调度 + gh 集成）
│   ├── architect.md            # 系统架构师
│   ├── developer.md            # 高级开发工程师
│   ├── security.md             # 安全专家
│   └── reviewer.md             # 代码审查专家
├── commands/                   # Slash 命令入口
│   ├── fetch-issues.md         # 拉取 Issue 列表
│   ├── issue.md                # Issue 深度分析
│   ├── plan.md                 # 生成开发计划
│   ├── auto-fix.md             # 一键自动修复
│   └── review.md               # 代码审查
└── settings.local.json         # 权限 + 环境变量配置

docs/
├── issues/                     # 分析报告
├── plans/                      # 技术方案
└── reviews/                    # 安全审查 + 代码审查报告

.github/
└── issue_templates/            # Issue 模板
```

---

## 命令参考

### `/fetch-issues` — 拉取 Issue 列表

```
/fetch-issues                    # 拉取所有 open 状态
/fetch-issues --label bug        # 按 label 过滤
/fetch-issues --limit 5          # 限制数量
/fetch-issues --state all        # 包含已关闭的
```

输出：结构化 Issue 列表 + 自动修复建议 + 优先级排序。持久化到 `docs/issues/fetch-{date}.md`。

### `/issue <id>` — Issue 深度分析

```
/issue 1                         # 分析 Issue #1
/issue 1 --remote                # 强制从 GitHub 拉取最新
```

输出：7 段标准化分析报告（基本信息 → 需求概述 → 技术分析 → 影响评估 → 工作量 → 自动化建议 → 下一步）。

### `/plan <id>` — 生成开发计划

```
/plan 1                          # 基于分析报告生成方案
```

输出：改动清单、执行顺序、DB 变更、测试策略、回滚方案、文件路径映射（JSON 格式供 Developer 直接使用）。

### `/review` — 代码审查

```
/review                          # 审查当前分支改动
/review --files <path>           # 只审查指定文件
```

输出：5 维度评分（正确性/性能/安全/架构/可维护性）+ 严重/建议/优化三级问题 + PASS/REJECT 决策。

### `/auto-fix <id>` — 一键自动修复

```
/auto-fix 1                      # 全自动流水线
/auto-fix 1 --dry-run            # 仅分析和Plan，不改代码
/auto-fix 1 --skip-security      # 跳过安全审查（Docs 类 Issue）
```

触发完整的 7 阶段流水线，最终输出 PR URL。

---

## 智能体参考

| 智能体 | 文件 | 职责 | 输入 | 输出 |
|--------|------|------|------|------|
| **issue_developer** | `agents/issue_developer.md` | 编排调度器 | Issue 编号 | PR URL |
| **architect** | `agents/architect.md` | 方案设计 | 分析报告 | plan.md |
| **developer** | `agents/developer.md` | 代码实现 | plan.md | 代码 commit |
| **security** | `agents/security.md` | 安全审查 | diff | security-report.md |
| **reviewer** | `agents/reviewer.md` | 代码审查 | diff | review-report.md |

### 协作关系

```
issue_developer (编排器)
    ├──→ architect     (Phase 2: 方案设计)
    ├──→ developer     (Phase 3: 代码实现)
    ├──→ security      (Phase 4: 安全审查)
    └──→ reviewer      (Phase 5: 代码审查)
```

---

## 使用指南

### 环境准备

**1. 安装 GitHub CLI**

```bash
winget install --id GitHub.cli --source winget
```

**2. 认证 GitHub**

```bash
gh auth login
# 按提示选择 GitHub.com → HTTPS → Login with browser
```

**3. 配置代理（如需要）**

在 `.claude/settings.local.json` 中配置：

```json
{
  "env": {
    "PATH": "/c/Program Files/GitHub CLI:$PATH",
    "HTTPS_PROXY": "http://127.0.0.1:8889",
    "HTTP_PROXY": "http://127.0.0.1:8889"
  },
  "permissions": {
    "allow": [
      "Bash(gh: *)",
      "Bash(git: *)",
      …
    ]
  }
}
```

### 手动分步模式

适合需要精细控制每个阶段的场景：

```
/fetch-issues           → 拉取 Issue 列表，了解有哪些待处理任务
/issue 1               → 深度分析 Issue #1，输出结构化分析报告
/plan 1                → 基于分析生成技术方案
                        → 🔴 确认 Plan
/auto-fix 1            → 进入自动流水线（Phase 3-6）
```

### 一键自动模式

适合清晰、低风险的 Issue：

```
/auto-fix 1            → 分析 → Plan → 编码 → 审查 → PR，一条命令完成
```

---

## 首次运行实录

以下是 Issue [#1 缺少中文文档](https://github.com/lmj1002/aiagent-explore/issues/1) 的完整执行过程。

### 执行摘要

```
Issue:     #1 缺少中文文档
类型:      Docs（文档补充）
复杂度:    中等（3 个文件，361 行）
风险:      极低（纯文档，无代码变更）
耗时:      ~3 分钟
结果:      ✅ PR #2 已创建并关联 Issue
```

### Phase 0: Issue 拉取与验证

```bash
gh issue view 1 --json number,title,body,labels,assignees,state,milestone,url
```

验证结果：
- ✅ 状态 OPEN
- ✅ 无阻塞标签
- ✅ 验收标准明确：每个纯英文文档都有一个对应的中文版

### Phase 1: 全项目扫描分析

扫描了 `.claude/agents/`、`.claude/commands/`、`.claude/skills/`、`langchain/` 下所有 `.md` 文件。

**分析结果**：15 个已有中文文档 + 3 个纯英文文档需要补充。

纯英文文档：
1. `langchain/buildAContentBuilderAgent/AGENTS.md`
2. `langchain/buildAContentBuilderAgent/skills/social-media/SKILL.md`
3. `langchain/buildAContentBuilderAgent/skills/blog-post/SKILL.md`

输出：`docs/issues/analysis-1.md`

### Phase 2: 方案设计

策略：不修改原文件，新增 `_CN.md` 副本。YAML frontmatter 保留英文（系统识别需要），正文全量翻译。

```
改动文件: 3 个（全部新增）| 预估: ~20min | 风险: 极低
```

输出：`docs/plans/plan-1.md`

### Phase 3: 创建分支 + 编码

```bash
git checkout -b issue-1-chinese-docs
```

生成 3 个中文文档，每完成一个 commit 一次：

```
docs(#1): add Chinese translations for English docs
  - AGENTS_CN.md (42 lines)
  - social-media/SKILL_CN.md (185 lines)
  - blog-post/SKILL_CN.md (134 lines)
```

### Phase 4 & 5: 安全审查 + 代码审查

- 🔒 安全审查：✅ PASS（纯文档，无安全风险）
- 👁️ 代码审查：✅ PASS（翻译质量良好，不影响现有文件）

输出：`docs/reviews/security-1.md`、`docs/reviews/review-1.md`

### Phase 6: Push + 创建 PR

```bash
git push origin issue-1-chinese-docs
gh pr create \
  --title "docs(#1): 为英文文档补充中文翻译" \
  --body "..."  # Closes #1
```

结果：https://github.com/lmj1002/aiagent-explore/pull/2

### Phase 7: 交付摘要

| 指标 | 数值 |
|------|------|
| Commits | 1 |
| 新增文件 | 3 |
| 新增行数 | +361 |
| 删除行数 | 0 |
| 审查结果 | 双 PASS |

---

## 输出产物说明

每次流水线执行会在 `docs/` 下生成以下文件：

| 文件 | 阶段 | 内容 |
|------|------|------|
| `docs/issues/fetch-{date}.md` | 拉取 | Issue 列表 + 批量操作建议 |
| `docs/issues/analysis-{id}.md` | 分析 | 7 段标准化分析报告 |
| `docs/plans/plan-{id}.md` | 方案 | 改动清单 + 执行顺序 + 回滚方案 |
| `docs/reviews/security-{id}.md` | 安全 | 安全审查结论 |
| `docs/reviews/review-{id}.md` | 审查 | 5 维度评分 + 合并决策 |

---

## 常见问题

### Q: `gh: command not found`

将 gh 完整路径加入 PATH 或使用绝对路径：
```bash
"/c/Program Files/GitHub CLI/gh" issue list
```

### Q: `TLS handshake timeout`

代理未生效。在 `.claude/settings.local.json` 的 `env` 中配置 `HTTPS_PROXY`。

### Q: `gh auth login` 报错连接失败

走 Personal Access Token 方式：
1. 浏览器打开 https://github.com/settings/tokens
2. 生成 classic token，勾选 `repo` 权限
3. `echo "ghp_xxx" | gh auth login --with-token`

### Q: 代理不稳定导致 `unexpected EOF`

代理连接断开，重试即可。代理恢复后 gh 命令会自动恢复。

### Q: PR 创建后 Issue 没有自动关闭

确保 PR body 中包含 `Closes #N`（N 为 Issue 编号）。PR 合并后 GitHub 会自动关闭关联的 Issue。

### Q: 想跳过安全审查

仅 Docs 类 Issue 可跳过：
```
/auto-fix 1 --skip-security
```
