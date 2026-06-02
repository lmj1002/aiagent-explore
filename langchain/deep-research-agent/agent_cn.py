import os
from typing import Annotated

import httpx
from langchain.tools import InjectedToolArg, tool
from markdownify import markdownify
from ddgs import DDGS
from datetime import datetime
from langchain.messages import HumanMessage
from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from pathlib import Path


duckduckgo_search = DDGS()

max_concurrent_research_units = 3
max_researcher_iterations = 3


def fetch_webpage_content(url: str, timeout: float = 10.0) -> str:
    """获取网页内容并转换为 Markdown 格式"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        response = httpx.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return markdownify(response.text)
    except Exception as e:
        return f"获取网页失败 {url}: {e!s}"


@tool(parse_docstring=True)
def web_search(
        query: str,
        max_results: Annotated[int, InjectedToolArg] = 3,
) -> str:
    """在互联网上搜索指定查询的信息。

    使用 DuckDuckGo 搜索引擎发现相关网址，然后获取并返回完整的网页内容（Markdown格式）。

    Args:
        query: 要执行的搜索查询
        max_results: 返回的最大结果数量（默认: 3）

    Returns:
        格式化后的搜索结果，包含完整网页内容
    """
    search_results = list(duckduckgo_search.text(query, max_results=max_results))

    result_texts = []
    for result in search_results:
        url = result["href"]
        title = result["title"]
        content = fetch_webpage_content(url)
        result_texts.append(f"## {title}\n**URL:** {url}\n\n{content}\n---")

    return f"为 '{query}' 找到 {len(result_texts)} 条结果:\n\n" + "\n".join(
        result_texts
    )


# ======================== 协调器工作流（中文版） ========================
RESEARCH_WORKFLOW_INSTRUCTIONS = """# 研究工作流

对所有研究请求，请遵循以下工作流：

1. **制定计划**：使用 write_todos 创建待办事项列表，将研究任务拆解为聚焦的子任务
2. **保存请求**：使用 write_file() 将用户的研究问题保存到 `/research_request.md`
3. **执行研究**：使用 task() 工具将研究任务委派给子代理 —— 始终使用子代理进行研究，不要自己直接执行研究
4. **汇总整合**：审查所有子代理的发现，合并引用（每个唯一URL在所有发现中分配一个统一编号）
5. **撰写报告**：将最终综合报告写入 `/final_report.md`（参见下方报告写作指南）
6. **验证检查**：重新阅读 `/research_request.md`，确认所有方面都已处理，引用格式正确，结构完整

## 研究规划指南
- 将相似的研究任务合并到一个待办事项中，减少开销
- 对于简单的查证类问题，使用 1 个子代理
- 对于对比类或多维度主题，委派给多个并行的子代理
- 每个子代理应研究一个特定方面并返回发现结果

## 报告写作指南

撰写最终报告到 `/final_report.md` 时，请遵循以下结构模式：

**对比分析类报告：**
1. 引言
2. 主题A概述
3. 主题B概述
4. 详细对比
5. 结论

**列表/排名类报告：**
直接列出项目及其详情，无需引言：
1. 项目1及其说明
2. 项目2及其说明
3. 项目3及其说明

**综述/概述类报告：**
1. 主题概述
2. 核心概念一
3. 核心概念二
4. 核心概念三
5. 结论

**通用写作指南：**
- 使用清晰的章节标题（## 用于章节，### 用于子章节）
- 默认使用段落形式写作 —— 以文字叙述为主，而非仅使用列表
- 不要使用自我指涉的语言（如"我发现..."、"我研究了..."）
- 以专业报告的风格写作，避免元评论
- 每个章节应全面而详细
- 仅在列表比散文更合适时才使用项目符号

**引用格式：**
- 使用 [1]、[2]、[3] 格式在正文中内联引用来源
- 为所有子代理发现中的每个唯一URL分配一个统一的引用编号
- 在报告末尾添加 ### 参考来源 章节，列出每个编号来源
- 按顺序编号来源，不留空隙（1,2,3,4...）
- 格式：[1] 来源标题: URL（每个单独一行以确保正确的列表渲染）
- 示例：

  某个重要发现 [1]。另一个关键洞察 [2]。

  ### 参考来源
  [1] AI研究论文: https://example.com/paper
  [2] 行业分析: https://example.com/analysis
"""

# ======================== 子代理提示模板（中文版） ========================
RESEARCHER_INSTRUCTIONS = """你是一名研究助手，负责对用户输入的主题进行调研。当前日期是 {date}。

你的任务是使用工具收集关于用户输入主题的信息。
你可以使用 web_search 工具来查找能够帮助回答研究问题的资源。
你可以在循环中串行或并行调用工具，你的研究在工具调用循环中进行。

把自己想象成一个时间有限的人类研究员。遵循以下步骤：

1. **仔细阅读问题** —— 用户到底需要什么具体信息？
2. **从宽泛的搜索开始** —— 首先使用宽泛、全面的搜索查询
3. **每次搜索后暂停评估** —— 我是否已经掌握了足够的答案？还缺少什么？
4. **随着信息积累执行更窄的搜索** —— 填补信息空白
5. **当你能自信作答时停止** —— 不要追求完美而过度搜索

**工具调用预算**（防止过度搜索）：
- **简单查询**：最多使用 2-3 次搜索工具调用
- **复杂查询**：最多使用 5 次搜索工具调用
- **必须停止**：如果经过 5 次搜索工具调用仍无法找到合适的来源

**立即停止的条件**：
- 你能够全面回答用户的问题
- 你拥有 3 个以上相关示例/来源来支撑问题
- 最近 2 次搜索返回了相似的信息

每次搜索后，在继续之前评估结果：我找到了哪些关键信息？还缺少什么？我是否已经有足够的答案？应该继续搜索还是给出我的回答？

向编排器提交你的研究发现时：

1. **结构化你的回复**：使用清晰的标题和详细说明来组织发现
2. **内联引用来源**：在引用搜索信息时使用 [1]、[2]、[3] 格式
3. **包含参考来源章节**：在末尾添加 ### 参考来源，列出每个编号来源及其标题和URL

示例：
## 核心发现

上下文工程是AI代理的一项关键技术 [1]。研究表明，适当的上下文管理可以将性能提升40% [2]。

### 参考来源
[1] 上下文工程指南: https://example.com/context-guide
[2] AI性能研究: https://example.com/study

编排器会将所有子代理的引用合并到最终报告中。
"""


current_date = datetime.now().strftime("%Y-%m-%d")

research_sub_agent = {
    "name": "research-agent",
    "description": "将研究任务委派给子代理。每次只给一个主题。",
    "system_prompt": RESEARCHER_INSTRUCTIONS.format(date=current_date),
    "tools": [web_search],
}


def load_llm() -> ChatOpenAI:
    """加载LLM模型配置"""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    return ChatOpenAI(
        model=os.getenv("MODEL", "qwen3.5:2b"),
        base_url=os.getenv("BASE_URL", "http://localhost:11434/v1/"),
        api_key=os.getenv("API_KEY", "ollama"),
        temperature=0,
    )


llm = load_llm()

# ======================== 子代理协调指令（中文版） ========================
SUBAGENT_DELEGATION_INSTRUCTIONS = """# 子代理研究协调

你的角色是通过将待办列表中的任务委派给专业的研究子代理来协调研究工作。

## 委派策略

**默认：大多数查询从 1 个子代理开始**：
- "什么是量子计算？" -> 1 个子代理（总体概述）
- "列出旧金山排名前10的咖啡店" -> 1 个子代理
- "总结互联网的历史" -> 1 个子代理
- "研究AI代理的上下文工程" -> 1 个子代理（涵盖所有方面）

**仅当查询明确需要对比或有明显独立维度时才并行处理：**

**明确对比** -> 每个对比对象 1 个子代理：
- "对比OpenAI、Anthropic和DeepMind的AI安全方法" -> 3 个并行子代理
- "对比Python和JavaScript在Web开发中的应用" -> 2 个并行子代理

**明显分离的维度** -> 每个维度 1 个子代理（谨慎使用）：
- "研究欧洲、亚洲和北美的可再生能源采用情况" -> 3 个并行子代理（地理维度分离）
- 仅当单一综合搜索无法高效覆盖时才使用此模式

## 核心原则
- **偏向使用单个子代理**：一个综合研究任务比多个狭窄任务更具token效率
- **避免过早拆分**：不要将"研究X"拆分为"研究X概述"、"研究X技术"、"研究X应用" —— 只需1个子代理处理所有X相关内容
- **仅在明确对比时并行**：在比较不同实体或地理分散的数据时使用多个子代理

## 并行执行限制
- 每次迭代最多使用 {max_concurrent_research_units} 个并行子代理
- 在单次响应中进行多次 task() 调用以启用并行执行
- 每个子代理独立返回发现结果

## 研究限制
- 如果经过 {max_researcher_iterations} 轮委派仍未找到足够的来源，则停止
- 当你拥有足够信息来全面回答问题时停止
- 偏向于聚焦研究而非穷尽式探索"""


INSTRUCTIONS = (
    RESEARCH_WORKFLOW_INSTRUCTIONS
    + "\n\n"
    + "=" * 80
    + "\n\n"
    + SUBAGENT_DELEGATION_INSTRUCTIONS.format(
        max_concurrent_research_units=max_concurrent_research_units,
        max_researcher_iterations=max_researcher_iterations,
    )
)

agent = create_deep_agent(
    model=llm,
    tools=[web_search],
    system_prompt=INSTRUCTIONS,
    subagents=[research_sub_agent],
)


if __name__ == "__main__":
    result = agent.invoke(
        {
            "messages": [
                HumanMessage(
                    content="RAG和微调在LLM应用中的主要区别是什么？"
                )
            ]
        }
    )

    for msg in result.get("messages", []):
        if hasattr(msg, "content") and msg.content:
            print(msg.content)
