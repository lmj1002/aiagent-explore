"""
============================================================
 最小 RAG 主干 —— LlamaIndex 学习用
============================================================
这一份就是你"必须亲手跑一遍"的主干代码。它完整覆盖 RAG 五个阶段：
    加载 → 切分 → 索引(嵌入) → 检索(+重排) → 合成回答

跑通之后，重点不是再抄一遍，而是去改下面标了 【🔧 改我】 的参数，
观察检索结果和答案怎么变 —— 这才是真正理解框架的方式。

运行：
    cd F:\study\aiagent-explore
    .venv\Scripts\python.exe llamaIndex\01_最小RAG.py
"""

import sys

# Windows 控制台默认 GBK，打印 emoji/特殊字符会报错，强制改用 UTF-8
sys.stdout.reconfigure(encoding="utf-8")

from llama_index.core import SimpleDirectoryReader, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from utils import setup_models

# ============================================================
# 0. 配置模型（LLM + 嵌入模型，详见 utils.py）
# ============================================================
print("⏳ 正在加载模型（首次加载 BGE 嵌入模型会慢一点）...")
setup_models()
print("✅ 模型就绪\n")

# ============================================================
# 1. 加载 —— 把文件读成 Document 对象
# ============================================================
# SimpleDirectoryReader 是最常用的加载器，能自动识别 txt/pdf/docx 等格式
documents = SimpleDirectoryReader(
    input_files=["data/三国小知识.txt"]
).load_data()
print(f"📄 加载完成：{len(documents)} 个 Document")

# ============================================================
# 2. 切分 —— 把 Document 切成一个个 Node(文本块)
# ============================================================
# 【🔧 改我①】chunk_size: 每块多大。调小(如128)→块更碎更精准但可能丢上下文；
#            调大(如1024)→上下文全但容易混入无关内容。
# 【🔧 改我②】chunk_overlap: 相邻块重叠多少，防止把一句话从中间切断。
splitter = SentenceSplitter(chunk_size=128, chunk_overlap=20)
nodes = splitter.get_nodes_from_documents(documents)
print(f"✂️  切分完成：{len(nodes)} 个 Node\n")

# ============================================================
# 3. 索引 —— 把每个 Node 向量化并建立可检索的索引
# ============================================================
# 这一步会调用 BGE 嵌入模型，把每个 Node 转成向量存进内存向量库
index = VectorStoreIndex(nodes)
print("🗂️  索引构建完成\n")

# ============================================================
# 4 + 5. 检索 + 合成 —— 用查询引擎一步到位
# ============================================================
# as_query_engine 内部 = 检索器 + 响应合成器，最省事的高级接口
# 【🔧 改我③】similarity_top_k: 检索回几个最相似的块交给大模型。
#            调大→信息更全但噪声多、更慢；调小→更聚焦但可能漏信息。
query_engine = index.as_query_engine(similarity_top_k=3)

# ============================================================
# 开始提问
# ============================================================
questions = [
    "赤壁之战是哪一年发生的？结果如何？",
    "诸葛亮是怎么去世的？",
    "关羽为什么被称为武圣？",
    "曹操写过哪些诗？",  # 文中有提到，考检索
    "刘备最后是在哪里去世的？",  # 答案藏在夷陵之战段落，考语义检索
]

for q in questions:
    print("=" * 60)
    print(f"❓ 问题：{q}")
    response = query_engine.query(q)
    print(f"🤖 回答：{response}")

    # 看看 RAG 到底检索到了哪些块（理解"答案从哪来"的关键）
    print("📚 引用的文档块：")
    for i, src in enumerate(response.source_nodes, 1):
        preview = src.node.text[:50].replace("\n", " ")
        print(f"   [{i}] 相似度{src.score:.3f} | {preview}...")
    print()
