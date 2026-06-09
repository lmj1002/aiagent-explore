---
name: doc-generator
description: Analyzes a project directory and generates a comprehensive, well-structured README.md documentation in Chinese. Covers architecture overview, execution flow, core components, key technical points, and dependency descriptions. Use when the user asks to "梳理", "整理文档", "写一份md文档", "生成说明文档", or review/documents a directory or module.
---

# 目录文档生成器

## 职责

扫描指定目录下的所有源码、配置、技能文件，阅读并理解代码逻辑与架构关系，生成结构化的中文 README.md 文档。

## 触发场景

| 触发词 | 示例 |
|--------|------|
| `梳理` | "梳理一下 XX 目录的代码" |
| `整理文档` | "把整个执行流程、方法备注等，梳理到同目录下的一份新的md文档中去" |
| `分析` | "分析一下这个模块的关键技术点" |
| `生成说明文档` | "帮我生成一份说明文档" |

## 执行步骤

| 步骤 | 操作 | 详细指南 |
|------|------|----------|
| 1 | 扫描目录结构，获取完整文件清单 | → `scripts/scan-guide.md` |
| 2 | 按优先级逐个读取核心文件 | → `scripts/scan-guide.md#文件读取优先级` |
| 3 | 识别核心组件与架构模式 | → `scripts/scan-guide.md#组件识别清单` |
| 4 | 绘制 ASCII 架构图与执行流程图 | → `references/format-spec.md` |
| 5 | 按 8 模块结构撰写文档 | → `assets/template.md` |
| 6 | 质量自查 | → `references/content-standards.md#质量检查清单` |

## 输出标准

- 文档路径：目标目录下的 `README.md`
- 语言：中文（代码注释/字符串保留原文）
- 结构：严格遵循 `assets/template.md` 的 8 模块骨架
- 格式：遵守 `references/format-spec.md` 的规范
- 内容：满足 `references/content-standards.md` 的要求
