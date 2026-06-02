# ========================== 1. 基础依赖导入 ==========================
import os
import csv
import io
from langchain.tools import tool
from langchain_core.utils.uuid import uuid7
from langgraph.checkpoint.memory import InMemorySaver
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from pathlib import Path

from langchain.agents import create_agent

# ========================== 2. 生成本地销售数据CSV文件 ==========================
# def create_sales_csv():
#     """
#     自动生成 sales_data.csv 到当前目录
#     确保AI能找到文件
#     """
#     data = [
#         ["Date", "Product", "Units Sold", "Revenue"],
#         ["2025-08-01", "Widget A", 10, 250],
#         ["2025-08-02", "Widget B", 5, 125],
#         ["2025-08-03", "Widget A", 7, 175],
#         ["2025-08-04", "Widget C", 3, 90],
#         ["2025-08-05", "Widget B", 8, 200],
#     ]
#
#     file_name = "sales_data.csv"
#     save_path = f".{file_name}"
#
#     # 写入CSV文件
#     with open(save_path, "w", newline="", encoding="utf-8") as f:
#         writer = csv.writer(f)
#         writer.writerows(data)
#
#     print(f"✅ 数据文件已生成：{save_path}")
#     return save_path
#
# # 执行生成（必须先生成文件，AI才能读取）
# csv_path = create_sales_csv()

# ========================== 3. 定义AI可用工具 ==========================

@tool(parse_docstring=True)
def slack_send_message(text: str, file_path: str | None = None) -> str:
    """
    模拟发送Slack消息工具（本地版，无真实API）
    支持发送文本 + 上传附件（图片/文件）

    Args:
        text: 消息内容
        file_path: 附件文件路径（可选）
    """
    print("\n=== 【模拟发送 Slack 消息】===")
    print(f"消息内容：{text}")

    # 处理附件
    if file_path:
        print(f"附件路径：{file_path}")
        if os.path.exists(file_path):
            print(f"✅ 文件上传成功（模拟）：{file_path}")
        else:
            print(f"⚠️ 上传失败：文件不存在")

    print("=======================================\n")
    return "✅ 消息发送完成（本地模拟模式）"


@tool(parse_docstring=True)
def read_csv_file(file_path: str) -> str:
    """
    读取本地CSV文件内容，返回格式化文本
    给AI用来分析数据

    Args:
        file_path: CSV文件路径
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return f"✅ 文件读取成功：\n{content[:1000]}..."  # 限制长度
    except Exception as e:
        return f"❌ 读取失败：{str(e)}"


@tool(parse_docstring=True)
def plot_sales_data(file_path: str) -> str:
    """
    根据销售数据生成折线图/柱状图
    保存为 plot.png 返回路径

    Args:
        file_path: sales_data.csv 路径
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # 无GUI后端，避免线程警告
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        import pandas as pd

        # 配置中文字体
        zh_font = None
        for name in ("Microsoft YaHei", "SimHei", "WenQuanYi Micro Hei"):
            for f in fm.fontManager.ttflist:
                if f.name == name:
                    zh_font = f
                    break
            if zh_font:
                break
        if zh_font:
            plt.rcParams["font.family"] = zh_font.name

        # 读取数据
        df = pd.read_csv(file_path)

        # 绘图
        plt.figure(figsize=(10, 5))
        plt.bar(df["Date"], df["Revenue"], color="skyblue")
        plt.title("每日销售额")
        plt.xlabel("日期")
        plt.ylabel("营收")
        plt.xticks(rotation=45)
        plt.tight_layout()

        # 保存图片
        img_path = "./sales_plot.png"
        plt.savefig(img_path)
        plt.close()

        return f"✅ 图表生成完成：{img_path}"
    except Exception as e:
        return f"❌ 绘图失败：{str(e)}"

# ========================== 4. 创建AI智能体 ==========================

#这里是使用的本地model ollama部署的qwen3.5:2b
def load_llm() -> ChatOpenAI:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    return ChatOpenAI(
        model=os.getenv("MODEL", "qwen3.5:2b"),
        base_url=os.getenv("BASE_URL", "http://localhost:11434/v1/"),
        api_key=os.getenv("API_KEY", "ollama"),
        temperature=0,
    )
llm = load_llm()

# 内存记忆存储（对话历史）
checkpointer = InMemorySaver()
# 创建 Agent
agent = create_agent(
    model=llm,          # 只传你创建好的模型，不传字符串！
    tools=[read_csv_file, plot_sales_data, slack_send_message],
    checkpointer=checkpointer,
)

# 生成对话ID
thread_id = str(uuid7())
config = {"configurable": {"thread_id": thread_id}}

# ========================== 5. 给AI下达任务 ==========================
input_message = {
    "role": "user",
    "content": (
        "请完成以下任务：\n"
        "1. 读取目录下的 sales_data.csv 文件\n"
        "2. 分析销售数据，给出文字总结\n"
        "3. 生成一张美观的图表\n"
        "4. 把分析结果和图表通过slack_send_message工具发送"
    ),
}

# ========================== 6. 流式运行AI并输出结果 ==========================
for step in agent.stream(
    {"messages": [input_message]},
    config,
    stream_mode="values",
):
    if messages := step.get("messages"):
        messages[-1].pretty_print()