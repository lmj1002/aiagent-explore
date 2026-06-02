# Plan #1 — 缺少中文文档

**关联分析**: docs/issues/analysis-1.md
**创建时间**: 2026-06-02
**设计者**: Architect Agent (via /auto-fix)

---

## 1. 方案概述

为 `langchain/buildAContentBuilderAgent/` 下 3 个纯英文文档各创建一个中文版本（`_CN.md` 后缀），不修改任何现有文件。翻译原则：YAML frontmatter 保留英文（系统识别需要），正文全量翻译为中文，技术术语保留原文。

## 2. 改动清单

| 序号 | 文件路径 | 改动类型 | 改动说明 | 预估行数 |
|------|----------|----------|----------|----------|
| 1 | `langchain/buildAContentBuilderAgent/AGENTS_CN.md` | **新增** | AGENTS.md 的中文翻译版 | ~50行 |
| 2 | `langchain/buildAContentBuilderAgent/skills/social-media/SKILL_CN.md` | **新增** | 社交媒体技能文档中文版 | ~60行 |
| 3 | `langchain/buildAContentBuilderAgent/skills/blog-post/SKILL_CN.md` | **新增** | 博客文章技能文档中文版 | ~60行 |

## 3. 执行顺序

```
Step 1: 翻译 AGENTS.md         → AGENTS_CN.md
Step 2: 翻译 social-media SKILL.md  → SKILL_CN.md
Step 3: 翻译 blog-post SKILL.md     → SKILL_CN.md
```

无依赖关系，可任意顺序执行。

## 4. 数据结构变更

无。

## 5. 测试策略

| 测试类型 | 测试内容 |
|----------|----------|
| 文件完整性 | 确认 3 个 `_CN.md` 文件都已创建 |
| 内容检查 | 中文正文无乱码，YAML frontmatter 完整 |
| 副作用检查 | `git status` 确认无现有文件被修改 |

## 6. 回滚方案

`git checkout` 放弃新增文件即可，或 `rm` 3 个 `_CN.md`。

## 7. 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 翻译语义偏差 | 低 | 极低 | 保留技术术语原文，仅翻译说明性文字 |

## 8. 文件路径映射（供 Developer 使用）

```json
{
  "issue_id": "1",
  "files": [
    {"path": "langchain/buildAContentBuilderAgent/AGENTS_CN.md", "action": "create", "description": "AGENTS.md 中文翻译"},
    {"path": "langchain/buildAContentBuilderAgent/skills/social-media/SKILL_CN.md", "action": "create", "description": "社交媒体 SKILL 中文翻译"},
    {"path": "langchain/buildAContentBuilderAgent/skills/blog-post/SKILL_CN.md", "action": "create", "description": "博客 SKILL 中文翻译"}
  ],
  "order": [1, 2, 3],
  "estimated_hours": 0.3
}
```
```

---

## 🔴 Plan 确认门禁

```
📐 Plan 已生成

改动文件: 3 个（全部新增）| 预估: ~20min | 风险: 极低

→ 确认执行 Phase 3（创建分支+生成中文文档）？
```
