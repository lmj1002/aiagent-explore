---
name: social-media
description: Drafts engaging social media posts, writes hooks, suggests hashtags, creates thread structures, and generates companion images. Use when the user asks to write a LinkedIn post, tweet, Twitter/X thread, social media caption, social post, or repurpose content for social platforms.
---

# 社交媒体内容创作技能

## 先做研究（必须）

**在撰写任何社交媒体内容之前，你必须委托研究任务：**

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
    description="研究 2025 年可再生能源趋势。将结果保存到 research/renewable-energy.md"
)
```

3. 研究完成后，在动笔前先阅读研究结果文件

## 输出结构（必须）

**每条社交媒体帖子必须同时包含内容和配图：**

**LinkedIn 帖子：**
```
linkedin/
└── <slug>/
    ├── post.md        # 帖子内容
    └── image.png      # 必须：生成的配图
```

**Twitter/X 推文串：**
```
tweets/
└── <slug>/
    ├── thread.md      # 推文串内容
    └── image.png      # 必须：生成的配图
```

示例：关于 "prompt engineering" 的 LinkedIn 帖子 → `linkedin/prompt-engineering/`

**你必须同时完成两步：**
1. 将内容写入对应路径
2. 使用 `generate_image` 生成配图并保存在帖子旁边

**没有配图的社交媒体帖子不算完成。**

## 平台指南

### LinkedIn

**格式：**
- 字数限制 1,300 字符（约 210 字符后显示"查看更多"）
- 第一行至关重要 — 必须抓住眼球
- 用空行分隔提高可读性
- 末尾加 3-5 个 hashtag

**语调：**
- 专业但有个人色彩
- 分享洞察和经验教训
- 提问以驱动互动
- 使用"我"并分享亲身经历

**结构：**
```
[Hook — 一句抓人眼球的话]

[空行]

[背景 — 为什么这个问题重要]

[空行]

[核心观点 — 2-3 个简短段落]

[空行]

[行动号召或提问]

#hashtag1 #hashtag2 #hashtag3
```

### Twitter/X

**格式：**
- 每条推文 280 字符限制
- 较长内容使用推文串（1/🧵 格式）
- 每条推文不超过 2 个 hashtag

**推文串结构：**
```
1/🧵 [Hook — 核心观点]

2/ [支撑论点 1]

3/ [支撑论点 2]

4/ [案例或证据]

5/ [结论 + 行动号召]
```

## 配图生成

每条社交媒体帖子都需要一张吸睛的配图。使用 `generate_social_image` 工具：

```
generate_social_image(prompt="详细的图片描述……", platform="linkedin", slug="your-post-slug")
```

该工具会将图片保存到 `<platform>/<slug>/image.png`。

### 社交配图最佳实践

社交配图需要在拥挤的信息流中以小尺寸工作：
- **大胆简洁的构图** — 一个清晰的视觉焦点
- **高对比度** — 滑动时能脱颖而出
- **图中不要有文字** — 太小了看不清，平台会自动适配
- **方形或 4:5 比例** — 跨平台兼容

### 如何写出有效的 Prompt

包含以下要素：

1. **单一焦点**：一个明确的主体，不要太拥挤
2. **大胆的风格**：鲜艳的色彩、强烈的形状、高对比度
3. **简洁的背景**：纯色、渐变或微妙的纹理
4. **情绪/能量**：匹配帖子调性（鼓舞人心、紧迫、深思）

### Prompt 示例

**洞察/技巧类帖子：**
```
一盏发光的灯泡悬浮在深紫色渐变背景之上，灯泡由相互连接的金色几何线条构成，柔和的光线向外辐射。极简、醒目、高对比度。方形构图。
```

**公告/新闻类：**
```
抽象的火箭由多彩的几何形状组成，向上发射，留下一串粒子轨迹。明亮的珊瑚色和青色配色搭配干净的白色背景。充满活力、庆祝的氛围。大胆的扁平插画风格。
```

**引人深思的内容：**
```
两个重叠的半透明圆形，一个蓝色一个橙色，中心形成发光的交汇区域。代表协作或思想的交集。深炭灰背景，柔和的空灵光芒。极简主义的沉思风格。
```

## 内容类型

### 公告帖
- 以新闻开头
- 解释影响
- 包含链接或下一步操作

### 洞察帖
- 分享一个具体的学习心得
- 简要说明背景
- 使其可操作

### 提问帖
- 提出一个真诚的问题
- 先给出你的观点
- 聚焦一个主题

## 质量检查清单

完成前确认：
- [ ] 帖子保存到 `linkedin/<slug>/post.md` 或 `tweets/<slug>/thread.md`
- [ ] 配图已在帖子旁边生成
- [ ] 第一行能抓住注意力
- [ ] 内容符合平台字数限制
- [ ] 语调符合平台规范
- [ ] 有明确的行动号召或提问
- [ ] Hashtag 是相关的（不是泛泛的）
