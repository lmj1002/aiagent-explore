# /plan — 根据 Issue 分析生成详细开发计划

基于 `/issue` 的分析报告，生成结构化的技术实现方案，作为 Developer 编码的唯一输入。

---

## 用法

```
/plan <issue-number>                          # 基于已有分析生成计划
/plan <issue-number> --from-analysis <file>   # 指定分析报告路径
```

---

## 前置条件

- 必须已有 Issue 分析报告（`docs/issues/analysis-{issue_id}.md`）
- 如果分析报告不存在，自动触发 `/issue <issue-number>` 先生成分析

---

## 执行流程

### Step 1：读取分析报告

从 `docs/issues/analysis-{issue_id}.md` 中提取：
- 业务目标
- 涉及模块
- 技术约束
- 风险点

### Step 2：调度 Architect

调用 `architect` 智能体，传递完整分析上下文。

Architect 需要回答以下问题并输出到计划：

---

## 输出模板

输出文件：`docs/plans/plan-{issue_id}.md`

```markdown
# Plan #{issue_id} — {Issue 标题}

**关联分析**: docs/issues/analysis-{issue_id}.md
**创建时间**: {timestamp}
**设计者**: Architect Agent

---

## 1. 方案概述

{用 3-5 句话描述整体技术方案}

## 2. 改动清单

| 序号 | 文件路径 | 改动类型 | 改动说明 | 预估行数 |
|------|----------|----------|----------|----------|
| 1 | {path} | 新增/修改/删除 | {说明} | +N/-M |
| ... | ... | ... | ... | ... |

## 3. 执行顺序

```
Step 1: {改动说明}      ← 先做（被其他改动依赖）
Step 2: {改动说明}
Step 3: {改动说明}      ← 后做（依赖前面的改动）
...
```

## 4. 数据结构变更

{如有 DB 变更，列出 DDL；如有 API 变更，列出接口签名}

### 数据库
```sql
-- 迁移脚本（如需要）
ALTER TABLE xxx ADD COLUMN yyy ...;
```

### API
```
POST /api/xxx → 新增参数 {param}: {type}，{说明}
```

## 5. 测试策略

| 测试类型 | 测试内容 | 覆盖文件 |
|----------|----------|----------|
| 单元测试 | {内容} | {文件} |
| 集成测试 | {内容} | {文件} |

## 6. 回滚方案

{如果上线后出现问题，如何快速恢复}

## 7. 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| {风险} | 高/中/低 | 高/中/低 | {措施} |

## 8. 文件路径映射（供 Developer 使用）

```json
{
  "issue_id": "{issue_id}",
  "files": [
    {"path": "{absolute_path}", "action": "modify", "description": "..."}
  ],
  "order": [1, 2, 3],
  "estimated_hours": {X}
}
```
```

---

## 门禁

Plan 完成后展示摘要并等待确认：

```
📐 Plan 已生成

文件改动: {N} 个 | 预估: {X}h | 风险: {低/中/高}

→ 确认执行 /auto-fix {issue_id}
→ 或手动逐步执行 /review 各阶段
```

---

## 禁止

- 不要在没有分析报告的情况下生成 Plan
- 不要跳过"文件路径映射"（Developer 需要这个才能定位代码）
- 不要忽略回滚方案
