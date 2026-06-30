"""
模型加载器 —— 统一配置 LlamaIndex 用的 LLM 和嵌入模型。

为什么单独抽出来：LlamaIndex 通过全局 Settings 决定"默认用哪个大模型 / 嵌入模型"，
其他脚本只要 import 这个函数调用一次，就不用每个文件重复配置。

本项目实际环境（都用阿里百炼 DashScope，复用同一个 DASHSCOPE_API_KEY）：
  - LLM      : qwen-turbo（云端，秒级响应）
  - 嵌入模型 : text-embedding-v3（1024 维，中文效果好）

注：本机无可用 GPU，本地 Ollama 跑 2B 模型单句要 5 分钟以上，不适合学习，故全部走云端。
    如果以后换了带显卡的机器想用本地模型，把 LLM 换回 Ollama 即可（见文末注释）。
"""

import os
from dotenv import load_dotenv
from llama_index.core import Settings
from llama_index.llms.dashscope import DashScope, DashScopeGenerationModels
from llama_index.embeddings.dashscope import DashScopeEmbedding, DashScopeTextEmbeddingModels

# 读取 .env 里的 DASHSCOPE_API_KEY
load_dotenv()

# LLM 模型名：qwen-turbo 最快最便宜，学习够用；想效果好可换 qwen-plus / qwen-max
LLM_MODEL = DashScopeGenerationModels.QWEN_TURBO


def setup_models(llm_model: str = LLM_MODEL):
    """配置并返回 (llm, embed_model)，同时写入全局 Settings。"""

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "未找到 DASHSCOPE_API_KEY，请在项目根目录 .env 里配置："
            "DASHSCOPE_API_KEY=sk-你的key"
        )

    # —— 大模型：阿里百炼 qwen-turbo ——
    llm = DashScope(model_name=llm_model, api_key=api_key)

    # —— 嵌入模型：阿里百炼 text-embedding-v3（1024 维）——
    # embed_batch_size=10: DashScope API 限制单次最多嵌入 10 条，超过自动分批
    embed_model = DashScopeEmbedding(
        model_name=DashScopeTextEmbeddingModels.TEXT_EMBEDDING_V3,
        api_key=api_key,
        embed_batch_size=10,
    )

    # 写入全局默认，之后 VectorStoreIndex / query_engine 会自动使用它们
    Settings.llm = llm
    Settings.embed_model = embed_model

    return llm, embed_model


# —— 备选：若以后用带显卡的机器，想把 LLM 换回本地 Ollama ——
# from llama_index.llms.ollama import Ollama
# llm = Ollama(model="qwen3.5:2b", request_timeout=120.0)
