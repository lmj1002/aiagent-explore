# /auto-fix — 一键 Issue → PR 自动修复流水线

调度 `issue_developer` 编排器，全自动执行：拉取 Issue → 分析 → Plan → 编码 → 安全审查 → Review → PR。

---

## 用法

```
/auto-fix <issue-number>           # 全自动流水线
/auto-fix <issue-number> --dry-run # 仅分析和Plan，不执行代码变更
/auto-fix <issue-number> --skip-security  # 跳过安全审查（仅限 Docs 类 Issue）
```

---

## 执行流程

此命令直接调度 `issue_developer` 智能体，执行完整的 7 阶段流水线：

```
Phase 0: 拉取 & 验证 Issue      → gh issue view
Phase 1: 分析 & 结构化输出       → /issue 逻辑
Phase 2: 方案设计                → architect agent
Phase 3: 创建分支 & 编码         → git checkout -b + developer agent
Phase 4: 安全审查                → security agent  (含失败回路 ≤3次)
Phase 5: 代码审查                → reviewer agent  (含失败回路 ≤2次)
Phase 6: Push & 创建 PR          → git push + gh pr create
Phase 7: 输出交付摘要
```

---

## 门禁点（需人工确认）

为避免全自动带来的风险，以下节点会暂停等待确认：

| 门禁 | 位置 | 说明 |
|------|------|------|
| 🔴 Plan 确认 | Phase 2 → 3 | 展示改动文件清单和风险等级 |
| 🟡 安全审查确认 | Phase 4 重试耗尽时 | P0/P1 风险无法自动修复 |
| 🟡 PR 创建确认 | Phase 6 前 | 展示最终 diff 摘要 |

- `--dry-run` 模式：只执行到 Phase 2，不修改代码
- 标记为 `bug` + `good-first-issue` 的简单 Issue 可能跳过 Plan 确认门禁

---

## 输出

流水线执行过程中会生成以下文件：

```
docs/
├── issues/
│   └── analysis-{issue_id}.md      # Phase 1 输出
├── plans/
│   └── plan-{issue_id}.md          # Phase 2 输出
└── reviews/
    ├── security-{issue_id}.md      # Phase 4 输出
    └── review-{issue_id}.md        # Phase 5 输出
```

最终 PR URL 在终端直接输出。

---

## 中断与恢复

如果流程中断（如权限问题、网络故障）：
- 已 commit 的代码保留在分支上
- 重新执行 `/auto-fix <issue-number>` 会检测已有进度并从中断点继续

---

## 禁止

- 不要对 `need-info` / `blocked` 标签的 Issue 执行
- 不要对 `help-wanted` 标签的 Issue 执行（需人工介入）
- 不要在无 git 仓库的环境中执行
