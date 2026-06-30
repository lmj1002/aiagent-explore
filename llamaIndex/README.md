# LlamaIndex 动手学习区

这个目录是配合 `docs/LlamaIndex.md` 的**动手实践**区。理念很简单：

> **主干敲一遍 + 零件看一遍 + 拿自己的数据调一遍**，比从头抄到尾快得多。

## 目录内容

| 文件 | 作用 |
|------|------|
| `加载模型.py` | 统一配置 LLM + 嵌入模型（均用阿里百炼 DashScope） |
| `01_最小RAG.py` | **必跑主干**：完整覆盖 RAG 五阶段，带"改我"参数 |
| `data/三国小知识.txt` | 示例语料，开箱即用 |

## 一、环境准备（只需一次）

### 1) 安装依赖包

```bash
cd F:\study\aiagent-explore

# 走阿里云镜像（直连 PyPI 会被网络拦截）
.venv\Scripts\python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com llama-index-core llama-index-llms-dashscope llama-index-embeddings-dashscope
```

### 2) 配置 DashScope API Key

LLM 和嵌入都用阿里百炼，共用一个 Key：

1. 去 [阿里云百炼控制台](https://bailian.console.aliyun.com/) → 右上角头像 → API-KEY → 创建
2. 在项目根目录 `.env` 文件里加一行：

```
DASHSCOPE_API_KEY=sk-你申请到的key
```

> **为什么不用本地模型？** 本机无可用 GPU，Ollama 跑 2B 模型单句要 5 分钟以上，
> 不适合学习，故 LLM + 嵌入全部走云端 DashScope（秒级响应）。
> 以后换带显卡的机器想用本地模型，把 `加载模型.py` 里 LLM 换回 Ollama 即可（文件末尾有注释示例）。

## 二、运行主干

```bash
cd F:\study\aiagent-explore
.venv\Scripts\python.exe llamaIndex\01_最小RAG.py
```

首次运行会加载本地 BGE 模型（稍慢），之后对 5 个问题逐一检索并回答，
还会打印**每个答案引用了哪些文档块及相似度** —— 这是理解"答案从哪来"的关键。

## 三、怎么学（重点）

跑通后**别再抄代码**，去做这几件事：

1. **改参数看变化**（脚本里标了 `🔧 改我`）
   - `chunk_size` 改成 128 / 1024，看切出多少块、答案有没有变化
   - `similarity_top_k` 改成 1 / 5，看引用的块数和答案质量
2. **换自己的数据**：把 `data/` 换成你自己的 txt/pdf，改 `input_files`，问你关心的问题
3. **费曼自检**：合上文档，用自己的话说清楚——
   - Document 和 Node 区别？
   - 向量检索 vs BM25 各强在哪？为什么要重排？
   - `chunk_overlap` 是干嘛的？
   说不清的地方回 `docs/LlamaIndex.md` 对应"📖 概念补充"补。

## 四、下一步可以加的零件（看懂即可，用时再写）

- **重排**：检索后加 `SentenceTransformerRerank` 后处理器，提升精度
- **持久化**：用 Chroma 把索引存到磁盘，避免每次重建
- **混合检索**：向量 + BM25 用 `QueryFusionRetriever` 融合
- **工作流**：把这套流程拆成可观测、可分支的 Workflow
- **评估**：用 `FaithfulnessEvaluator` 给答案打分

这些在 `docs/LlamaIndex.md` 都有示例，是"同一位置可替换的零件"，不必每个都手敲。
