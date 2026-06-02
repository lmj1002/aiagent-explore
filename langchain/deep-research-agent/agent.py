import os
from typing import Annotated, Literal

import httpx
from langchain.tools import InjectedToolArg, tool
from markdownify import markdownify
from ddgs import DDGS
from datetime import datetime
from langchain.messages import HumanMessage
from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from pathlib import Path


duckduckgo_search = DDGS()  # 实例化搜索对象

# tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
max_concurrent_research_units = 3
max_researcher_iterations = 3
def fetch_webpage_content(url: str, timeout: float = 10.0) -> str:
    """Fetch webpage and convert HTML to markdown."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        response = httpx.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return markdownify(response.text)
    except Exception as e:
        return f"Error fetching {url}: {e!s}"


@tool(parse_docstring=True)
def tavily_search(
        query: str,
        max_results: Annotated[int, InjectedToolArg] = 3,
) -> str:
    """Search the web for information on a given query.

       Uses Tavily to discover relevant URLs, then fetches and returns full webpage content as markdown.

       Args:
           query: Search query to execute
           max_results: Maximum number of results to return (default: 1)
           topic: Topic filter - 'general', 'news', or 'finance' (default: 'general')

       Returns:
           Formatted search results with full webpage content
       """
    # 2.调用库合法接口，剔除不支持的topic参数
    search_results = list(duckduckgo_search.text(query, max_results=max_results))

    result_texts = []
    # 3.直接遍历列表数据
    for result in search_results:
        # 4.替换为正确字段名
        url = result["href"]
        title = result["title"]
        content = fetch_webpage_content(url)
        result_texts.append(f"## {title}\n**URL:** {url}\n\n{content}\n---")

    return f"Found {len(result_texts)} result(s) for '{query}':\n\n" + "\n".join(
        result_texts
    )


# 协调器工作流
RESEARCH_WORKFLOW_INSTRUCTIONS = """# Research Workflow

Follow this workflow for all research requests:

1. **Plan**: Create a todo list with write_todos to break down the research into focused tasks
2. **Save the request**: Use write_file() to save the user's research question to `/research_request.md`
3. **Research**: Delegate research tasks to sub-agents using the task() tool - ALWAYS use sub-agents for research, never conduct research yourself
4. **Synthesize**: Review all sub-agent findings and consolidate citations (each unique URL gets one number across all findings)
5. **Write Report**: Write a comprehensive final report to `/final_report.md` (see Report Writing Guidelines below)
6. **Verify**: Read `/research_request.md` and confirm you've addressed all aspects with proper citations and structure

## Research Planning Guidelines
- Batch similar research tasks into a single TODO to minimize overhead
- For simple fact-finding questions, use 1 sub-agent
- For comparisons or multi-faceted topics, delegate to multiple parallel sub-agents
- Each sub-agent should research one specific aspect and return findings

## Report Writing Guidelines

When writing the final report to `/final_report.md`, follow these structure patterns:

**For comparisons:**
1. Introduction
2. Overview of topic A
3. Overview of topic B
4. Detailed comparison
5. Conclusion

**For lists/rankings:**
Simply list items with details - no introduction needed:
1. Item 1 with explanation
2. Item 2 with explanation
3. Item 3 with explanation

**For summaries/overviews:**
1. Overview of topic
2. Key concept 1
3. Key concept 2
4. Key concept 3
5. Conclusion

**General guidelines:**
- Use clear section headings (## for sections, ### for subsections)
- Write in paragraph form by default - be text-heavy, not just bullet points
- Do NOT use self-referential language ("I found...", "I researched...")
- Write as a professional report without meta-commentary
- Each section should be comprehensive and detailed
- Use bullet points only when listing is more appropriate than prose

**Citation format:**
- Cite sources inline using [1], [2], [3] format
- Assign each unique URL a single citation number across ALL sub-agent findings
- End report with ### Sources section listing each numbered source
- Number sources sequentially without gaps (1,2,3,4...)
- Format: [1] Source Title: URL (each on separate line for proper list rendering)
- Example:

 Some important finding [1]. Another key insight [2].

 ### Sources
 [1] AI Research Paper: https://example.com/paper
 [2] Industry Analysis: https://example.com/analysis
"""
# 子代理提示模板
RESEARCHER_INSTRUCTIONS = """You are a research assistant conducting research on the user's input topic. For context, today's date is {date}.

Your job is to use tools to gather information about the user's input topic.
You can use the tavily_search tool to find resources that can help answer the research question.
You can call it in series or in parallel, your research is conducted in a tool-calling loop.

You have access to the tavily_search tool for conducting web searches.

Think like a human researcher with limited time. Follow these steps:

1. **Read the question carefully** - What specific information does the user need?
2. **Start with broader searches** - Use broad, comprehensive queries first
3. **After each search, pause and assess** - Do I have enough to answer? What's still missing?
4. **Execute narrower searches as you gather information** - Fill in the gaps
5. **Stop when you can answer confidently** - Don't keep searching for perfection

**Tool Call Budgets** (Prevent excessive searching):
- **Simple queries**: Use 2-3 search tool calls maximum
- **Complex queries**: Use up to 5 search tool calls maximum
- **Always stop**: After 5 search tool calls if you cannot find the right sources

**Stop Immediately When**:
- You can answer the user's question comprehensively
- You have 3+ relevant examples/sources for the question
- Your last 2 searches returned similar information

After each search, assess results before continuing: What key information did I find? What's missing? Do I have enough to answer? Should I search more or provide my answer?

When providing your findings back to the orchestrator:

1. **Structure your response**: Organize findings with clear headings and detailed explanations
2. **Cite sources inline**: Use [1], [2], [3] format when referencing information from your searches
3. **Include Sources section**: End with ### Sources listing each numbered source with title and URL

Example:
## Key Findings

Context engineering is a critical technique for AI agents [1]. Studies show that proper context management can improve performance by 40% [2].

### Sources
[1] Context Engineering Guide: https://example.com/context-guide
[2] AI Performance Study: https://example.com/study

The orchestrator will consolidate citations from all sub-agents into the final report.
"""


current_date = datetime.now().strftime("%Y-%m-%d")

research_sub_agent = {
    "name": "research-agent",
    "description": "Delegate research to the sub-agent. Give one topic at a time.",
    "system_prompt": RESEARCHER_INSTRUCTIONS.format(date=current_date),
    "tools": [tavily_search],
}

# model = init_chat_model(model="google_genai:gemini-3.5-flash", temperature=0.0)
def load_llm() -> ChatOpenAI:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    return ChatOpenAI(
        model=os.getenv("MODEL", "qwen3.5:2b"),
        base_url=os.getenv("BASE_URL", "http://localhost:11434/v1/"),
        api_key=os.getenv("API_KEY", "ollama"),
        temperature=0,
    )
llm = load_llm()
SUBAGENT_DELEGATION_INSTRUCTIONS = """# Sub-Agent Research Coordination

Your role is to coordinate research by delegating tasks from your TODO list to specialized research sub-agents.

## Delegation Strategy

**DEFAULT: Start with 1 sub-agent** for most queries:
- "What is quantum computing?" -> 1 sub-agent (general overview)
- "List the top 10 coffee shops in San Francisco" -> 1 sub-agent
- "Summarize the history of the internet" -> 1 sub-agent
- "Research context engineering for AI agents" -> 1 sub-agent (covers all aspects)

**ONLY parallelize when the query EXPLICITLY requires comparison or has clearly independent aspects:**

**Explicit comparisons** -> 1 sub-agent per element:
- "Compare OpenAI vs Anthropic vs DeepMind AI safety approaches" -> 3 parallel sub-agents
- "Compare Python vs JavaScript for web development" -> 2 parallel sub-agents

**Clearly separated aspects** -> 1 sub-agent per aspect (use sparingly):
- "Research renewable energy adoption in Europe, Asia, and North America" -> 3 parallel sub-agents (geographic separation)
- Only use this pattern when aspects cannot be covered efficiently by a single comprehensive search

## Key Principles
- **Bias towards single sub-agent**: One comprehensive research task is more token-efficient than multiple narrow ones
- **Avoid premature decomposition**: Don't break "research X" into "research X overview", "research X techniques", "research X applications" - just use 1 sub-agent for all of X
- **Parallelize only for clear comparisons**: Use multiple sub-agents when comparing distinct entities or geographically separated data

## Parallel Execution Limits
- Use at most {max_concurrent_research_units} parallel sub-agents per iteration
- Make multiple task() calls in a single response to enable parallel execution
- Each sub-agent returns findings independently

## Research Limits
- Stop after {max_researcher_iterations} delegation rounds if you haven't found adequate sources
- Stop when you have sufficient information to answer comprehensively
- Bias towards focused research over exhaustive exploration"""


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
    tools=[tavily_search],
    system_prompt=INSTRUCTIONS,
    subagents=[research_sub_agent],
)


if __name__ == "__main__":
    result = agent.invoke(
        {
            "messages": [
                HumanMessage(
                    content="What are the main differences between RAG and fine-tuning for LLM applications?"
                )
            ]
        }
    )

    for msg in result.get("messages", []):
        if hasattr(msg, "content") and msg.content:
            print(msg.content)

######output#######
# What are the main differences between RAG and fine-tuning for LLM applications?
# Updated todo list to [{'content': 'Research and compare RAG vs fine-tuning for LLM applications', 'status': 'in_progress'}]
# Based on my research, I've compiled a comprehensive comparison of **RAG (Retrieval-Augmented Generation)** vs **Fine-Tuning** for LLM applications. Here's what you need to know:
#
# ---
#
# ## **RAG vs Fine-Tuning: A Comprehensive Comparison**
#
# ### **1. How They Work**
#
# #### **RAG (Retrieval-Augmented Generation)**
# - **Core Concept**: Combines external knowledge retrieval with LLM generation
# - **Process**:
#   1. Store your data in a vector database
#   2. When a query is made, search for semantically similar documents
#   3. Retrieve relevant context and append it to the user's query
#   4. LLM generates response using both the query and retrieved documents
# - **Analogy**: Like a research assistant who pulls up relevant documents before answering
#
# #### **Fine-Tuning**
# - **Core Concept**: Retrains the LLM on your specific domain data
# - **Process**:
#   1. Start with a pre-trained LLM (trained on general knowledge)
#   2. Collect and label task-specific data
#   3. Adjust the model's weights/parameters using backpropagation
#   4. Train the model to understand your domain's terminology and patterns
# - **Analogy**: Like teaching a student specific vocabulary and concepts from your domain
#
# ---
#
# ### **2. Key Differences**
#
# | **Aspect** | **RAG** | **Fine-Tuning** |
# |------------|---------|-----------------|
# | **Cost** | Low - minimal hardware | High - requires GPUs, training time |
# | **Setup Time** | Short - weeks to implement | Long - weeks to months |
# | **Maintenance** | Low - data updates automatically | High - requires retraining |
# | **Flexibility** | High - works with any LLM/data | Low - fixed to trained model |
# | **Customization** | Limited - can't change model behavior | Full - can customize writing style, expertise |
# | **Hallucinations** | Low - grounded in retrieved data | Higher - still may generate inaccurate info |
# | **Accuracy** | Good for up-to-date info | Better for domain-specific accuracy |
# | **Data Requirements** | Less labeled data needed | Requires labeled task-specific data |
#
# ---
#
# ### **3. Pros & Cons**
#
# #### **RAG Advantages:**
# ✅ **Dynamic Updates** - No need to retrain when data changes
# ✅ **Cost-Effective** - Lower hardware and resource requirements
# ✅ **Scalable** - Works well with growing data volumes
# ✅ **Fast Implementation** - Quick to set up and deploy
# ✅ **Transparent** - You can trace where information comes from
# ✅ **Flexible** - Works with any LLM or data source
#
# #### **RAG Disadvantages:**
# ⚠️ **Data Quality Dependency** - Poor data leads to poor performance
# ⚠️ **Context Limitations** - Still limited by token/window size
# ⚠️ **Integration Complexity** - Requires building retrieval systems
# ⚠️ **Not Domain-Specific** - May not understand your terminology well
#
# #### **Fine-Tuning Advantages:**
# ✅ **High Accuracy** - Better domain-specific understanding
# ✅ **Reduced Hallucinations** - Grounded in your data
# ✅ **Improved Performance** - Better for repeated tasks
# ✅ **Full Customization** - Can adjust writing style, tone, expertise
#
# #### **Fine-Tuning Disadvantages:**
# ❌ **Expensive** - Requires GPUs, significant time, resources
# ❌ **Maintenance Burden** - Frequent retraining needed
# ❌ **Complex to Maintain** - Requires deep expertise in neural networks
# ❌ **Static Knowledge** - Can't easily incorporate new information
#
# ---
#
# ### **4. Best Use Cases**
#
# #### **Choose RAG When:**
# - ✅ Your data updates frequently (e.g., customer support tickets, news articles)
# - ✅ You need fast, cost-effective solutions
# - ✅ Your use cases are dynamic and vary in complexity
# - ✅ You want transparency about where information comes from
# - ✅ You're starting with limited budget and expertise
# - ✅ Your data is somewhat structured but not perfect
#
# **Examples:**
# - Customer support chatbots
# - Legal document summarization
# - Medical information retrieval
# - Technical documentation
# - Knowledge base systems
#
# #### **Choose Fine-Tuning When:**
# - ✅ Your queries are repetitive and predictable
# - ✅ You have a static dataset that rarely changes
# - ✅ You need maximum domain-specific accuracy
# - ✅ Your business has budget and expertise for training
# - ✅ You want to embed your terminology and style deeply
# - ✅ You're building a specialized expert system
#
# **Examples:**
# - Legal advice chatbots (trained on legal documents)
# - Medical diagnosis assistants
# - Financial analysis tools
# - Technical support with specific product knowledge
# - Content generation for specific industries
#
# ---
#
# ### **5. When to Combine Both (The "Best of Both Worlds")**
#
# Many organizations use **both approaches together** for maximum flexibility:
#
# 1. **Fine-tune** the LLM to understand your domain's terminology and basic concepts
# 2. **Use RAG** to provide real-time updates and context
# 3. **Combine** for the best of both: domain expertise + up-to-date information
#
# This hybrid approach gives you:
# - ✅ Domain-specific understanding
# - ✅ Current, relevant information
# - ✅ Fast deployment
# - ✅ Scalable architecture
#
# ---
#
# ### **6. Decision Framework**
#
# **Ask yourself these questions:**
#
# 1. **How often does your data change?**
#    - Frequently → RAG
#    - Rarely → Fine-tuning
#
# 2. **How much budget do you have?**
#    - Limited → RAG
#    - Abundant → Fine-tuning
#
# 3. **How complex are your queries?**
#    - Simple/repetitive → Fine-tuning
#    - Dynamic/complex → RAG
#
# 4. **How important is transparency?**
#    - High → RAG
#    - Low → Fine-tuning
#
# 5. **Do you need maximum accuracy?**
#    - Yes → Fine-tuning
#    - No → RAG
#
# ---
#
# ### **7. Implementation Considerations**
#
# **For RAG:**
# - Choose appropriate vector database (e.g., Pinecone, Weaviate, Milvus)
# - Implement proper chunking strategies
# - Build retrieval and reranking systems
# - Consider hybrid search (keyword + semantic)
#
# **For Fine-Tuning:**
# - Start with a good pre-trained model (e.g., Llama, Mistral, GPT)
# - Prepare high-quality labeled data
# - Use appropriate training techniques (SFT, PPO, etc.)
# - Monitor for overfitting and data drift
#
# ---
#
# ### **8. Bottom Line**
#
# **RAG is the modern standard** for most applications because it's:
# - ✅ Faster to implement
# - ✅ More cost-effective
# - ✅ Easier to maintain
# - ✅ More flexible
#
# **Fine-tuning is still valuable** when:
# - ✅ You need maximum domain-specific accuracy
# - ✅ Your queries are highly repetitive
# - ✅ You have budget and expertise
# - ✅ You want to embed your terminology deeply
#
# **The best approach is often a hybrid** - fine-tune for domain expertise, then use RAG for real-time updates and context.
#
# ---
#
# Would you like me to dive deeper into any specific aspect, such as implementation strategies, cost comparisons, or specific use case recommendations?
# Updated file /final_report.md
#      1	# RAG vs Fine-Tuning: A Comprehensive Comparison for LLM Applications
#      2
#      3	## Executive Summary
#      4
#      5	Retrieval-Augmented Generation (RAG) and fine-tuning represent two distinct approaches to building Large Language Model (LLM) applications. While both can improve upon the capabilities of base models, they differ fundamentally in architecture, cost, flexibility, and use case suitability. This report provides a detailed comparison to help organizations select the appropriate approach for their specific needs.
#      6
#      7	## 1. How They Work
#      8
#      9	### RAG (Retrieval-Augmented Generation)
#     10
#     11	RAG combines external knowledge retrieval with LLM generation. The process involves:
#     12
#     13	1. **Data Storage**: Store your data in a vector database or knowledge base
#     14	2. **Query Processing**: When a query is made, search for semantically similar documents
#     15	3. **Context Retrieval**: Retrieve relevant context and append it to the user's query
#     16	4. **Generation**: LLM generates response using both the query and retrieved documents
#     17
#     18	**Analogy**: Like a research assistant who pulls up relevant documents before answering a question.
#     19
#     20	### Fine-Tuning
#     21
#     22	Fine-tuning involves retraining an LLM on your specific domain data. The process involves:
#     23
#     24	1. **Pre-trained Model**: Start with a pre-trained LLM (trained on general knowledge)
#     25	2. **Data Collection**: Collect and label task-specific data
#     26	3. **Model Adjustment**: Adjust the model's weights/parameters using backpropagation
#     27	4. **Training**: Train the model to understand your domain's terminology and patterns
#     28
#     29	**Analogy**: Like teaching a student specific vocabulary and concepts from your domain.
#     30
#     31	## 2. Key Differences
#     32
#     33	### Cost
#     34
#     35	| Approach | Cost |
#     36	|----------|------|
#     37	| RAG | Low - minimal hardware requirements |
#     38	| Fine-Tuning | High - requires GPUs, significant training time and resources |
#     39
#     40	### Setup Time
#     41
#     42	| Approach | Time Required |
#     43	|----------|---------------|
#     44	| RAG | Weeks to implement |
#     45	| Fine-Tuning | Weeks to months |
#     46
#     47	### Maintenance
#     48
#     49	| Approach | Maintenance Burden |
#     50	|----------|-------------------|
#     51	| RAG | Low - data updates automatically |
#     52	| Fine-Tuning | High - requires retraining |
#     53
#     54	### Flexibility
#     55
#     56	| Aspect | RAG | Fine-Tuning |
#     57	|--------|-----|-------------|
#     58	| LLM Choice | Works with any LLM | Fixed to trained model |
#     59	| Data Source | Works with any data | Limited to trained data |
#     60	| Customization | Limited - can't change model behavior | Full - can customize writing style, tone, expertise |
#     61
#     62	### Accuracy
#     63
#     64	| Aspect | RAG | Fine-Tuning |
#     65	|--------|-----|-------------|
#     66	| Hallucinations | Low - grounded in retrieved data | Higher - still may generate inaccurate info |
#     67	| Domain Accuracy | Good for up-to-date info | Better for domain-specific accuracy |
#     68
#     69	### Data Requirements
#     70
#     71	| Aspect | RAG | Fine-Tuning |
#     72	|--------|-----|-------------|
#     73	| Labeled Data | Less labeled data needed | Requires labeled task-specific data |
#     74
#     75	## 3. Detailed Comparison
#     76
#     77	### RAG Advantages
#     78
#     79	- **Dynamic Updates**: No need to retrain when data changes
#     80	- **Cost-Effective**: Lower hardware and resource requirements
#     81	- **Scalable**: Works well with growing data volumes
#     82	- **Fast Implementation**: Quick to set up and deploy
#     83	- **Transparent**: You can trace where information comes from
#     84	- **Flexible**: Works with any LLM or data source
#     85
#     86	### RAG Disadvantages
#     87
#     88	- **Data Quality Dependency**: Poor data leads to poor performance
#     89	- **Context Limitations**: Still limited by token/window size
#     90	- **Integration Complexity**: Requires building retrieval systems
#     91	- **Not Domain-Specific**: May not understand your terminology well
#     92
#     93	### Fine-Tuning Advantages
#     94
#     95	- **High Accuracy**: Better domain-specific understanding
#     96	- **Reduced Hallucinations**: Grounded in your data
#     97	- **Improved Performance**: Better for repeated tasks
#     98	- **Full Customization**: Can adjust writing style, tone, expertise
#     99
#    100	### Fine-Tuning Disadvantages
# Updated todo list to [{'content': 'Research and compare RAG vs fine-tuning for LLM applications', 'status': 'completed'}]
# I've completed the research and created a comprehensive comparison report. Here's a summary:
#
# ## Key Findings
#
# **RAG (Retrieval-Augmented Generation)** is the modern standard for most applications because it's:
# - **Faster to implement** (weeks vs months)
# - **More cost-effective** (lower hardware requirements)
# - **Easier to maintain** (data updates automatically)
# - **More flexible** (works with any LLM/data source)
#
# **Fine-Tuning** is valuable when:
# - You need **maximum domain-specific accuracy**
# - Your queries are **highly repetitive**
# - You have **budget and expertise**
# - You want to **embed your terminology deeply**
#
# **The hybrid approach** (fine-tuning + RAG) is often the best solution, combining domain expertise with real-time updates.
#
# The report has been saved to `/final_report.md` with detailed comparisons, decision frameworks, and implementation considerations.