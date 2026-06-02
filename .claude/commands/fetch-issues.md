# /fetch-issues — 自动拉取 GitHub Issue 列表

从 GitHub 仓库拉取 Issue 列表，结构化展示，为后续自动化流水线提供输入。

---

## 用法

```
/fetch-issues                    # 拉取所有 open 状态的 Issue
/fetch-issues --label bug        # 按 label 过滤
/fetch-issues --limit 5          # 限制数量
/fetch-issues --state all        # 包含已关闭的 Issue
/fetch-issues --assignee @me     # 只看分配给我的
```

---

## 执行流程

### Step 1：拉取 Issue 列表

执行命令（根据参数调整 flags）：

```bash
gh issue list --state open --limit 20 --json number,title,labels,assignees,createdAt,updatedAt,url
```

若需要详细信息，追加：
```bash
gh issue view <issue-number> --json number,title,body,labels,assignees,state,createdAt,updatedAt,url,comments
```

### Step 2：结构化输出

将拉取结果整理为以下格式，每个 Issue 生成一个分析卡片：

```markdown
## Issue #{number} — {title}

| 字段 | 内容 |
|------|------|
| 状态 | {state} |
| 标签 | {labels} |
| 负责人 | {assignees} |
| 创建时间 | {createdAt} |
| 更新时间 | {updatedAt} |
| URL | {url} |

### 摘要
{从 body 中提取的前3行关键信息}

### 快速判断
- **复杂度**: {简单/中等/复杂}（根据涉及模块和描述长度估算）
- **类型**: {Bug/Feature/Refactor/Docs}
- **可自动修复**: {是/否/不确定}
```

### Step 3：排序建议

按优先级排列：
1. **Bug + 高优先级标签** > Feature > Docs
2. **有明确复现步骤的** > 描述模糊的
3. **涉及文件少的** > 大范围改动的
4. **最近更新的** > 长期未动的

### Step 4：生成批量操作摘要

```markdown
## 📊 批量操作摘要

| 总计 | 可自动修复 | 需人工介入 | 待确认 |
|------|-----------|-----------|--------|
| {N} | {X} | {Y} | {Z} |

### 建议自动处理（按优先级）
1. #{id} — {title} （理由：{复杂度低/描述清晰/有明确文件指向}）
2. ...

### 建议人工介入
1. #{id} — {title} （理由：{影响范围大/需求模糊/涉及架构决策}）
```

---

## 输出文件

拉取结果持久化到：
```
docs/issues/fetch-{timestamp}.md
```

---

## 后续动作

拉取完成后，提示用户可用下一步命令：

- `/issue {id}` — 深入分析单个 Issue
- `/plan {id}` — 为指定 Issue 生成开发计划
- `/auto-fix {id}` — 一键进入自动修复流水线（Phase 2 实现）

---

## 禁止

- 不要跳过 Step 2 的结构化输出直接进入开发
- 不要对标记为 `需人工介入` 的 Issue 尝试自动修复
