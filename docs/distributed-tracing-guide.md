# 微服务链路追踪（Distributed Tracing）系统化学习笔记

> 本文档系统梳理微服务分布式链路追踪的核心概念、数据流转流程、标准协议演进、主流开源项目对比，以及一套可落地的学习路径与实战 Demo（Go + OpenTelemetry + Jaeger）。
> 链路追踪是可观测性（Observability）三大支柱之一，另两个是 Metrics（指标）与 Logging（日志）。

---

## 一、为什么需要链路追踪

单体应用中，一个请求的完整调用栈都在一个进程内，打日志、看堆栈即可定位问题。但在微服务架构下，一次用户请求可能横跨十几个服务、多次 RPC/HTTP 调用，还涉及消息队列、缓存、数据库：

```
用户 → 网关 → 订单服务 → 库存服务 → 支付服务 → 风控服务
                  ↓            ↓
               用户服务      消息队列 → 通知服务
```

由此带来四个经典难题：

- **延迟定位**：整个请求耗时 3 秒，到底慢在哪个服务、哪一跳？
- **错误定位**：最终报错，是哪个下游服务最先失败的？
- **依赖梳理**：这个服务到底依赖哪些下游？调用拓扑是什么样？
- **故障传播**：某个服务抖动，影响了哪些上游链路？

链路追踪的目标：把"一次请求在分布式系统中的完整路径"串联、还原、可视化。

---

## 二、核心概念

术语基本源自 Google 2010 年的 **Dapper 论文**，后被各家系统沿用。

| 概念 | 含义 |
|------|------|
| **Trace（链路）** | 一次完整请求的全局视图，由全局唯一的 Trace ID 标识，包含一棵 Span 树 |
| **Span（跨度）** | 链路中的一个工作单元（如"调用库存服务"），含开始/结束时间、名称 |
| **Span ID** | 单个 Span 的唯一标识 |
| **Parent Span ID** | 指向父 Span，用于把 Span 串成树/有向图 |
| **Trace Context** | 服务间传递的上下文，核心是 `trace_id + span_id + 采样标记` |
| **Tags / Attributes** | Span 上的键值对元数据，如 `http.method=GET`、`http.status_code=500` |
| **Logs / Events** | Span 内某时间点发生的事件（带时间戳），如异常、重试 |
| **Baggage** | 跨 Span 透传的业务数据（如 user_id），有性能成本，慎用 |
| **Sampling（采样）** | 是否记录某条链路的决策，用于控制数据量与成本 |

一个 Trace 与其 Span 的关系如下：

```
Trace (trace_id = abc123)
└── Span A: 网关处理 [0ms ────────────────── 300ms]
    ├── Span B: 订单服务 [10ms ──────── 250ms]   parent=A
    │   ├── Span C: 查库存 [20ms ─ 80ms]          parent=B
    │   └── Span D: 调支付 [90ms ─── 240ms]       parent=B
    └── Span E: 写日志 [255ms ─ 270ms]            parent=A
```

可视化后即为熟悉的**火焰图 / 甘特图**：每条横杠是一个 Span，长度代表耗时，缩进代表父子关系。一眼即可看出 Span D（支付）是耗时大头。

---

## 三、完整流程（数据如何流转）

链路追踪系统的端到端流程分六步：

### 1. 埋点（Instrumentation）
在代码中生成 Span，分两种方式：
- **自动埋点**：通过 Agent / SDK 拦截框架（HTTP 客户端、gRPC、数据库驱动、消息中间件），无侵入或低侵入自动生成 Span。主流方式。
- **手动埋点**：业务关键逻辑里手写 `span := tracer.Start(ctx, "name")`。

### 2. 上下文传播（Context Propagation）⭐ 最关键
请求跨服务时必须透传 Trace Context，否则链路会断。
- **进程内**：靠 ThreadLocal（Java）、`context.Context`（Go）、AsyncLocalStorage（Node）传递。
- **跨进程**：把 trace_id/span_id 注入请求头。现行标准是 **W3C Trace Context**，对应 HTTP header：
  ```
  traceparent: 00-{trace_id}-{parent_span_id}-{flags}
  tracestate: ...
  ```
  下游服务从 header 取出，作为自身 Span 的 parent，链路即接上。

### 3. 采集（Collection）
SDK 把生成的 Span 先缓存在内存，批量上报，避免阻塞业务线程。

### 4. 上报与处理（Export / Pipeline）
通过 Collector（如 OpenTelemetry Collector）接收数据，做批处理、过滤、采样、格式转换、属性丰富，再转发到后端存储。Collector 解耦了"应用怎么发"与"后端怎么存"。

### 5. 存储（Storage）
海量 Span 写入存储，常见后端：Elasticsearch、Cassandra、ClickHouse、对象存储（Grafana Tempo 用对象存储省钱）。

### 6. 查询与可视化（Query & UI）
按 trace_id 检索整条链路，渲染成火焰图、服务依赖拓扑图、耗时分布等。

### 采样策略（成本控制核心）
- **头部采样（Head-based）**：请求一进来就决定采不采，简单、低成本，但可能漏掉出错链路。
- **尾部采样（Tail-based）**：整条链路完成后再决定，可"只保留出错的、慢的链路"，更智能但需 Collector 缓存全链路，成本高。

---

## 四、标准与协议的演进

```
OpenTracing (API 标准)  ─┐
                          ├──→ 合并为 OpenTelemetry (OTel) —— 当前事实标准
OpenCensus (SDK+采集)    ─┘

W3C Trace Context —— 跨服务传播的 HTTP header 标准（已成 W3C 正式标准）
```

**OpenTelemetry（OTel）是当下最该重点学的**：CNCF 项目，统一了 Tracing / Metrics / Logging 的 API、SDK、协议（OTLP）与 Collector。几乎所有后端（Jaeger、Zipkin、Tempo、云厂商）都支持它。学会 OTel，后端可随意更换。

---

## 五、主流开源项目对比

| 项目 | 定位 | 特点 | 适合 |
|------|------|------|------|
| **OpenTelemetry** | 标准 + SDK + Collector | 事实标准，厂商中立，多语言，最该学 | 所有人，作为埋点与采集层 |
| **Jaeger** | 追踪后端 + UI | Uber 开源，CNCF 毕业项目，原生支持 OTel，社区活跃 | 追踪后端首选 |
| **Zipkin** | 追踪后端 + UI | Twitter 开源，最早期，轻量、上手简单、资料多 | 入门、轻量场景 |
| **Apache SkyWalking** | 全栈 APM | 国产之光，Java 自动探针强大，含 metrics/告警/拓扑 | Java 技术栈、想要开箱即用 |
| **Grafana Tempo** | 追踪后端 | 仅靠对象存储，成本极低，与 Grafana/Loki/Prometheus 深度集成 | 已用 Grafana 全家桶 |

**推荐实践组合**：OpenTelemetry（埋点 + Collector）+ Jaeger 或 Tempo（后端 + 展示）。这是目前最主流、最有前途的搭配。

---

## 六、学习路径与资源推荐

### 第一步：读经典理论（建立心智模型）
- **Google Dapper 论文**（必读，一切的源头）：搜索 "Dapper, a Large-Scale Distributed Systems Tracing Infrastructure"，Google Research 官网有 PDF。
- 《Distributed Systems Observability》（Cindy Sridharan，O'Reilly 免费电子书）——讲清可观测性三支柱关系。

### 第二步：啃官方文档（最权威、最新）
- **OpenTelemetry 官方文档**：`opentelemetry.io/docs/` —— 重点看 Concepts（Traces / Context Propagation / Sampling）与对应语言的 SDK 指南。
- **W3C Trace Context 规范**：`www.w3.org/TR/trace-context/`，理解传播标准。
- **Jaeger 官方文档**：`jaegertracing.io/docs/`，重点看 Architecture 页。

### 第三步：上手 GitHub 项目（边跑边学）
- `open-telemetry/opentelemetry-collector` —— 采集层核心。
- `open-telemetry/opentelemetry-demo` ⭐ —— 官方多语言微服务电商 Demo，Docker Compose 一键起，自带 Jaeger/Grafana，最高效的实战入口。
- `jaegertracing/jaeger` —— 后端实现。
- `apache/skywalking` —— Java 栈可看其 Agent 自动探针实现。

### 第四步：动手做最小实验
1. 用 `docker compose` 跑起 `opentelemetry-demo`，在 Jaeger UI 点开一条 trace，理解火焰图。
2. 自写两个最简单的服务（A 调 B），接入 OTel SDK，制造跨服务调用，在 Jaeger 看到链路被串起。
3. 故意在 B 里 sleep 制造延迟，再在 UI 里定位出来——这一步会让"链路追踪到底有什么用"彻底通透。

> 本仓库配套实战 Demo 见 `demo/distributed-tracing/`（Go + OpenTelemetry + Jaeger，Docker Compose 一键启动），详见该目录 README。
