"""
LangChain Deep Agent from Scratch Demo

5 步渐进式构建一个数据分析智能体，展示 Middleware 中间件栈的逐步叠加过程。
每步独立可运行，通过 --step 参数选择步骤。

Usage:
    python agent.py --step 1
    python agent.py --step 5
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.messages import HumanMessage
from langchain_openai import ChatOpenAI

# ============================== LLM 加载 ==============================


def load_llm() -> ChatOpenAI:
    """从项目根目录 .env 加载 LLM 配置，默认使用本地 Ollama qwen3.5:2b"""
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")

    try:
        # 创建绕过代理的 httpx 客户端，避免本地 Ollama 请求被代理劫持
        timeout = httpx.Timeout(
            float(os.getenv("LLM_TIMEOUT", "120")),
            connect=10.0,
        )
        http_client = httpx.Client(proxy=None, timeout=timeout)

        llm = ChatOpenAI(
            model=os.getenv("MODEL", "qwen3.5:2b"),
            base_url=os.getenv("BASE_URL", "http://localhost:11434/v1/"),
            api_key=os.getenv("API_KEY", "ollama"),
            temperature=0,
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
            http_client=http_client,
        )
        print(f"[load_llm] 模型: {llm.model_name}, base_url: {llm.openai_api_base}")
        return llm
    except Exception as e:
        print(f"\n❌ LLM 初始化失败: {e}")
        print("   请检查:")
        print("   1. Ollama 是否已启动 (默认 http://localhost:11434)")
        print("   2. 模型是否已下载 (默认 qwen3.5:2b)")
        print("   3. 代理设置是否正常 (HTTPS_PROXY / HTTP_PROXY)")
        sys.exit(1)


# ============================== 目录 & 数据准备 ==============================

EXAMPLE_DIR = Path(__file__).parent
SANDBOX_DIR = EXAMPLE_DIR / "sandbox"
SALES_DATA_SRC = EXAMPLE_DIR.parent / "sales_data.csv"


def ensure_sandbox():
    """确保 sandbox 目录存在，并将 sales_data.csv 拷贝进去"""
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    dst = SANDBOX_DIR / "sales_data.csv"
    if SALES_DATA_SRC.exists():
        shutil.copy2(str(SALES_DATA_SRC), str(dst))
        print(f"[setup] Copied sales_data.csv -> {dst}")
    else:
        print(f"[setup] WARNING: {SALES_DATA_SRC} not found, creating sample data.")
        sample = "Date,Product,Units Sold,Revenue\n2025-08-01,Widget A,10,250\n2025-08-02,Widget B,5,125"
        dst.write_text(sample, encoding="utf-8")
    return SANDBOX_DIR


# ============================== Step 1: Minimal Agent ==============================


def minimal_agent():
    """
    Step 1: 最小化 Agent
    - 无工具 (tools=[])
    - 无中间件
    - 纯对话模式，LLM 直接回应
    """
    print("\n" + "=" * 70)
    print("  Step 1: Minimal Agent (无工具、无中间件)")
    print("=" * 70)

    llm = load_llm()
    agent = create_agent(model=llm, tools=[])

    return agent


# ============================== Step 2: + FilesystemMiddleware ==============================


def with_filesystem():
    """
    Step 2: 添加文件系统中间件
    - FilesystemBackend 替代在线 LangSmithSandbox
    - 支持 read_file / write_file / glob 等文件操作工具
    """
    print("\n" + "=" * 70)
    print("  Step 2: + FilesystemMiddleware (文件系统读写)")
    print("=" * 70)

    from deepagents.backends import FilesystemBackend
    from deepagents.middleware import FilesystemMiddleware

    llm = load_llm()
    sandbox = ensure_sandbox()
    backend = FilesystemBackend(root_dir=str(sandbox))

    agent = create_agent(
        model=llm,
        tools=[],
        middleware=[FilesystemMiddleware(backend=backend)],
    )

    return agent


# ============================== Step 3: + SummarizationMiddleware ==============================


def with_summarization():
    """
    Step 3: 添加上下文压缩中间件
    - SummarizationMiddleware 自动检测对话长度
    - 超过阈值时对历史消息做摘要压缩，防止 Token 超窗口
    """
    print("\n" + "=" * 70)
    print("  Step 3: + SummarizationMiddleware (自动上下文压缩)")
    print("=" * 70)

    from deepagents.backends import FilesystemBackend
    from deepagents.middleware import FilesystemMiddleware, SummarizationMiddleware

    llm = load_llm()
    sandbox = ensure_sandbox()
    backend = FilesystemBackend(root_dir=str(sandbox))

    agent = create_agent(
        model=llm,
        tools=[],
        middleware=[
            FilesystemMiddleware(backend=backend),
            SummarizationMiddleware(model=llm, backend=backend),
        ],
    )

    return agent


# ============================== Step 4: + SkillsMiddleware ==============================


def with_skills():
    """
    Step 4: 添加技能系统中间件
    - SkillsMiddleware 按需加载 skills/ 目录下的领域知识
    - Agent 在相关任务中自动注入 SKILL.md 知识
    """
    print("\n" + "=" * 70)
    print("  Step 4: + SkillsMiddleware (技能系统)")
    print("=" * 70)

    from deepagents.backends import FilesystemBackend
    from deepagents.middleware import (
        FilesystemMiddleware,
        SkillsMiddleware,
        SummarizationMiddleware,
    )

    llm = load_llm()
    sandbox = ensure_sandbox()
    backend = FilesystemBackend(root_dir=str(sandbox))
    skills_dir = str(EXAMPLE_DIR / "skills")

    agent = create_agent(
        model=llm,
        tools=[],
        middleware=[
            FilesystemMiddleware(backend=backend),
            SummarizationMiddleware(model=llm, backend=backend),
            SkillsMiddleware(backend=backend, sources=[skills_dir]),
        ],
    )

    return agent


# ============================== Step 5: + TodoListMiddleware + SubAgentMiddleware ==============================


def full_agent():
    """
    Step 5: 完整 Agent 中间件栈
    - FilesystemMiddleware    (1. 文件系统)
    - SummarizationMiddleware (2. 上下文压缩)
    - SkillsMiddleware        (3. 技能系统)
    - TodoListMiddleware       (4. 任务清单追踪)
    - SubAgentMiddleware      (5. 子智能体委派)
    """
    print("\n" + "=" * 70)
    print("  Step 5: Full Agent (完整中间件栈)")
    print("=" * 70)

    from deepagents import SubAgent
    from deepagents.backends import FilesystemBackend
    from deepagents.middleware import (
        FilesystemMiddleware,
        SkillsMiddleware,
        SubAgentMiddleware,
        SummarizationMiddleware,
    )
    from langchain.agents.middleware import TodoListMiddleware

    llm = load_llm()
    sandbox = ensure_sandbox()
    backend = FilesystemBackend(root_dir=str(sandbox))
    skills_dir = str(EXAMPLE_DIR / "skills")

    visualizer: SubAgent = {
        "name": "visualizer",
        "description": "Generates charts and visualizations from data files using matplotlib and seaborn.",
        "system_prompt": (
            "You are a data visualization specialist. "
            "Write Python scripts using matplotlib and seaborn to generate charts. "
            "Save all figures as PNG files. "
            "Read CSV data files using pandas before plotting."
        ),
        "model": llm,
        "tools": [],
    }

    agent = create_agent(
        model=llm,
        tools=[],
        middleware=[
            FilesystemMiddleware(backend=backend),
            SummarizationMiddleware(model=llm, backend=backend),
            SkillsMiddleware(backend=backend, sources=[skills_dir]),
            TodoListMiddleware(),
            SubAgentMiddleware(backend=backend, subagents=[visualizer]),
        ],
    )

    return agent


# ============================== 入口 & 参数解析 ==============================


def main():
    parser = argparse.ArgumentParser(
        description="LangChain Deep Agent from Scratch - 5 Step Demo"
    )
    parser.add_argument(
        "--step",
        type=int,
        choices=[1, 2, 3, 4, 5],
        default=5,
        help="选择运行哪个步骤 (1-5)，默认运行 Step 5 完整版",
    )
    parser.add_argument(
        "--task",
        type=str,
        default=None,
        help='自定义任务描述（可选），例如: --task "读取 sales_data.csv 并分析销售趋势"',
    )
    args = parser.parse_args()

    # 分步选择
    step_fns = {
        1: minimal_agent,
        2: with_filesystem,
        3: with_summarization,
        4: with_skills,
        5: full_agent,
    }

    agent = step_fns[args.step]()

    # 默认任务：数据分析场景
    default_task = (
        "请完成以下数据分析任务：\n"
        "1. 读取 sales_data.csv 文件，查看数据内容\n"
        "2. 分析数据：计算每种产品的总销量和总收入\n"
        "3. 给出数据洞察和趋势总结\n"
    )

    task = args.task if args.task else default_task

    print(f"\n[task] 任务: {task}\n")

    result = agent.invoke({"messages": [HumanMessage(content=task)]})

    print("\n" + "=" * 70)
    print("  最终响应:")
    print("=" * 70)
    for msg in result.get("messages", []):
        if hasattr(msg, "content") and msg.content:
            print(msg.content)


if __name__ == "__main__":
    main()
