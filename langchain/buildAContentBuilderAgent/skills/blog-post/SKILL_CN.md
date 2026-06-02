---
name: blog-post
description: Writes and structures long-form blog posts, creates tutorial outlines, and optimizes content for SEO with cover image generation. Use when the user asks to write a blog post, article, how-to guide, tutorial, technical writeup, thought leadership piece, or long-form content.
---

# 博客文章写作技能

## 先做研究（必须）

**在撰写任何博客文章之前，你必须委托研究任务：**

1. 使用 `task` 工具，设置 `subagent_type: "researcher"`
2. 在 description 中同时指定主题和保存位置：

```
task(
    subagent_type="researcher",
    description="研究 [主题]。将结果保存到 research/[slug].md"
)
```

示例：
```
task(
    subagent_type="researcher",
    description="研究 2025 年 AI 智能体的发展现状。将结果保存到 research/ai-agents-2025.md"
)
```

3. 研究完成后，在动笔前先阅读研究结果文件

## 输出结构（必须）

**每篇博客文章必须同时包含正文和封面图：**

```
blogs/
└── <slug>/
    ├── post.md        # 博客正文
    └── hero.png       # 必须：生成的封面图
```

示例：关于 "AI Agents in 2025" 的文章 → `blogs/ai-agents-2025/`

**你必须同时完成两步：**
1. 将文章写入 `blogs/<slug>/post.md`
2. 使用 `generate_image` 生成封面图并保存到 `blogs/<slug>/hero.png`

**没有封面图的博客文章不算完成。**

## 博客文章结构

每篇博客文章应遵循以下结构：

### 1. Hook（开篇）
- 以一个引人入胜的问题、数据或陈述开头
- 让读者想要继续往下读
- 控制在 2-3 句话

### 2. 背景（问题）
- 解释为什么这个主题重要
- 描述问题或机会
- 与读者的经历建立连接

### 3. 正文（解决方案）
- 用 H2 标题拆分为 3-5 个主要部分
- 每部分覆盖一个关键点
- 在合适处包含代码示例、图表或截图
- 列表内容使用 bullet point

### 4. 实践应用
- 展示如何应用这些概念
- 如适用，包含逐步操作指南
- 提供代码片段或模板

### 5. 结论与行动号召
- 总结关键要点（最多 3 条 bullet point）
- 以明确的行动号召收尾
- 链接到相关资源

## 封面图生成

写完文章后，使用 `generate_cover` 工具生成封面图：

```
generate_cover(prompt="详细的图片描述……", slug="your-blog-slug")
```

该工具会将图片保存到 `blogs/<slug>/hero.png`。

### 如何写出有效的图片 Prompt

用以下要素构建你的 prompt：

1. **主体**：主要焦点是什么？要具体明确。
2. **风格**：艺术方向（极简、等轴测、扁平设计、3D 渲染、水彩等）
3. **构图**：元素如何排列（居中、三分法则、对称）
4. **色彩方案**：具体的颜色或情绪（温暖的大地色、冷蓝紫调、高对比度）
5. **光线/氛围**：柔和散射光、戏剧性阴影、黄金时刻、霓虹光芒
6. **技术细节**：宽高比考虑、为文字叠加留出的负空间

### Prompt 示例

**技术类博客：**
```
等轴测 3D 插画：相互连接的发光立方体代表 AI 智能体，每个立方体都有微妙的电路纹理。立方体之间由发光的数据流连接。深海军蓝背景（#0a192f），电蓝色（#64ffda）和柔紫色（#c792ea）点缀。干净极简风格，顶部留出大量负空间用于标题。专业的技术美学。
```

**教程/指南类：**
```
干净的扁平插画：一双手在键盘上打字，抽象的代码符号向上飘浮并转化为灯泡和齿轮。从柔和珊瑚色到浅桃色的温暖渐变背景。友好、亲切的风格。居中构图，预留文字叠加空间。
```

**思想领导力类：**
```
抽象可视化：人类侧面剪影与几何神经网络图案融合。分割式构图 — 左侧为有机水彩纹理，右侧过渡为干净矢量线条。柔和鼠尾草绿与温暖赤陶色调。沉思、前瞻的氛围。
```

## SEO 考量

- 在标题和第一段中包含目标关键词
- 自然地在全文中使用关键词 3-5 次
- 标题控制在 60 字符以内
- 撰写 meta description（150-160 字符）

## 质量检查清单

完成前确认：
- [ ] 文章保存到 `blogs/<slug>/post.md`
- [ ] 封面图生成到 `blogs/<slug>/hero.png`
- [ ] 开篇 2 句话能抓住注意力
- [ ] 每个章节有明确的目的
- [ ] 结论总结了关键要点
- [ ] 行动号召告诉读者下一步该做什么
