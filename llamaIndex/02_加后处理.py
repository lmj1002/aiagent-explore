"""
============================================================
 02 · 给 RAG 加"后处理" —— 对比过滤前 / 后的检索质量
============================================================
节点后处理器(Node Postprocessor)解决的问题：向量检索会返回一批"语义相近"的块，
但"相近"不等于"相关" —— 有些相似度低的块可能是噪声。后处理器在检索之后、
生成之前过滤/重排这些块，提升最终输入给 LLM 的上下文质量。

本脚本用 SimilarityPostprocessor：按相似度阈值过滤掉弱相关的块。

流程对比：
    不过滤：向量检索 top_k=6 →  直接全拿 6 个   （加后处理前）
    过滤：  向量检索 top_k=6 →  过滤掉 <0.55 的（加后处理后）

运行：
    cd F:\study\aiagent-explore
    .venv\Scripts\python.exe llamaIndex\02_加后处理.py
"""

import sys

sys.stdout.reconfigure(encoding="utf-8")

from llama_index.core import SimpleDirectoryReader, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.postprocessor import SimilarityPostprocessor
from utils import setup_models

# ---------- 0~3. 和主干一样：配模型、加载、切分、建索引 ----------
print("⏳ 正在加载模型...")
setup_models()
print("✅ 模型就绪\n")

documents = SimpleDirectoryReader(
    input_files=["data/三国小知识.txt"]
).load_data()
nodes = SentenceSplitter(chunk_size=256, chunk_overlap=50).get_nodes_from_documents(documents)
index = VectorStoreIndex(nodes)
print(f"🗂️  索引就绪（{len(nodes)} 个 Node）\n")

# ---------- 4. 粗筛：先检索候选 ----------
# 【🔧 改我①】TOP_K：检索召回数
TOP_K = 8
# 【🔧 改我②】CUTOFF：相似度阈值，低于此值的块会被过滤掉
CUTOFF = 0.60

retriever = index.as_retriever(similarity_top_k=TOP_K)

# 这个问题故意"绕"一点：答案分散，考验过滤
QUESTION = "夷陵之战蜀汉为什么会失败？"

print("=" * 60)
print(f"❓ 问题：{QUESTION}\n")

# ---------- 对比 A：不过滤，看原始检索结果 ----------
raw_nodes = retriever.retrieve(QUESTION)
print(f"【A · 加后处理前】向量检索原始结果（top_k={TOP_K}）：")
for i, n in enumerate(raw_nodes, 1):
    flag = f"  ← 低于阈值 {CUTOFF}，会被过滤" if n.score < CUTOFF else ""
    print(f"   {i}. 相似度{n.score:.3f} | {n.node.text[:40].strip()}...{flag}")

# ---------- 对比 B：加后处理，过滤弱相关块 ----------
postprocessor = SimilarityPostprocessor(similarity_cutoff=CUTOFF)
filtered_nodes = postprocessor.postprocess_nodes(raw_nodes, query_str=QUESTION)

print(f"\n【B · 加后处理后】过滤掉相似度 < {CUTOFF} 的块：")
for i, n in enumerate(filtered_nodes, 1):
    print(f"   {i}. 相似度{n.score:.3f} | {n.node.text[:40].strip()}...")

print(f"\n💡 观察点：从 {len(raw_nodes)} 个过滤到 {len(filtered_nodes)} 个，")
print(f"   被过滤掉的 {len(raw_nodes) - len(filtered_nodes)} 个块是否确实不太相关？\n")

# ---------- 5. 用过滤后的结果生成最终答案 ----------
query_engine = index.as_query_engine(
    similarity_top_k=TOP_K,
    node_postprocessors=[SimilarityPostprocessor(similarity_cutoff=CUTOFF)],
)
print("=" * 60)
response = query_engine.query(QUESTION)
print(f"🤖 最终回答（基于过滤后的 {len(filtered_nodes)} 个块）：\n{response}\n")
print("📚 实际引用的块：")
for i, src in enumerate(response.source_nodes, 1):
    print(f"   [{i}] 相似度{src.score:.3f} | {src.node.text[:50].strip()}...")
