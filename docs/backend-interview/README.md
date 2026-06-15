# 后端高级面试知识架构 — 总索引

> **团队知识库入口文档**  
> 汇聚 13 个技术领域的深度面试知识体系，覆盖语言基础、数据存储、中间件、容器编排、架构设计等方向。  
> 每份文档面向 5-8 年经验的高级后端开发 / 架构师，兼顾面试备战与生产实践参考。

---

## 目录

- [文档定位与使用指南](#文档定位与使用指南)
- [技术栈分组索引](#技术栈分组索引)
  - [语言栈](#语言栈)
  - [数据库](#数据库)
  - [缓存与消息队列](#缓存与消息队列)
  - [容器与编排](#容器与编排)
  - [实时通信](#实时通信)
  - [架构设计](#架构设计)
- [推荐学习路径](#推荐学习路径)
- [高频交叉知识点索引](#高频交叉知识点索引)
- [版本说明与更新日志](#版本说明与更新日志)

---

## 文档定位与使用指南

### 目标受众

- **高级后端开发工程师**（5-8 年经验），正在准备大厂高级 / 资深 / 架构师级别面试
- **技术负责人 / 架构师**，需要体系化知识图谱作为团队技能矩阵参考
- **PHP / Go 双栈开发者**，文档特别考虑了从 PHP 到 Go 的技术演进路线

### 如何使用

| 场景 | 建议 |
|------|------|
| **面试冲刺** | 按"推荐学习路径"中的快速路线，优先攻克语言栈 + 架构设计 + 数据库 |
| **日常查漏补缺** | 通过"高频交叉知识点索引"快速定位涉及多个技术领域的问题 |
| **团队培训** | 每个文档均可作为独立模块，按技术栈分组组织读书会或内部分享 |
| **生产参考** | 各文档均包含生产最佳实践、踩坑经验、性能调优参数说明 |

### 难度说明

每份文档标注了难度等级，从 ⭐⭐⭐ 到 ⭐⭐⭐⭐⭐：

- ⭐⭐⭐：掌握核心概念与常见面试题，适合快速复习
- ⭐⭐⭐⭐：深入原理与生产实践，适合深度备战
- ⭐⭐⭐⭐⭐：涉及源码分析与架构决策，适合架构师级别

### 文档命名规范

```
NN-{tech}-advanced.md
```

`NN` 为序号，不反映学习顺序；`{tech}` 为技术领域英文名。

---

## 技术栈分组索引

### 语言栈

| # | 文档 | 难度 | 简介 |
|---|------|------|------|
| 01 | [PHP 高级面试知识架构](./01-php-advanced.md) | ⭐⭐⭐⭐ | 覆盖 PHP 基础语法（类型系统、命名空间、Traits、闭包、生成器）、运行原理（Zend 引擎执行流程、OPcache、内存管理）、主流框架核心（Laravel 服务容器、生命周期、Eloquent ORM 原理）、设计模式、性能调优（Xdebug 分析、慢查询、Opcache）、安全防护（SQL 注入、XSS、CSRF、SSRF）、架构设计（分层架构、领域驱动、CQRS、事件溯源）。适合 PHP 主栈开发者深度备战。 |
| 02 | [Go 高级面试知识架构](./02-golang-advanced.md) | ⭐⭐⭐⭐⭐ | 覆盖 Go 语言核心（Goroutine 与 Channel、内存模型、反射原理）、并发编程（GMP 调度模型、sync 包源码、并发模式）、运行时原理（GC 演进、逃逸分析、栈扩张）、标准库深度（net/http、database/sql、context）、框架与微服务（Gin / Kitex / 自研框架对比）、数据库与缓存（GORM 原理、连接池、缓存模式）、性能调优（pprof 使用、火焰图、benchmark 编写）、消息队列集成、Go vs PHP 高阶对比。适合 PHP 转 Go 或 Go 主栈的架构师。 |

### 数据库

| # | 文档 | 难度 | 简介 |
|---|------|------|------|
| 03 | [MySQL 高级面试知识架构](./03-mysql-advanced.md) | ⭐⭐⭐⭐⭐ | 深度剖析 InnoDB 存储引擎架构（Buffer Pool、Redo Log、Undo Log、Double Write）、索引优化（B+ 树原理、联合索引最左匹配、索引下推、覆盖索引、索引失效场景）、SQL 优化（慢查询分析、EXPLAIN 详解、分页优化）、锁机制（行锁、间隙锁、Next-Key Lock、死锁分析）、事务与隔离级别（MVCC 实现、RC/RR 区别、长事务危害）、高可用架构（主从复制、半同步复制、MGR、读写分离、分库分表）、生产运维（备份策略、监控体系、大表 DDL）、与 PostgreSQL 对比分析。 |
| 09 | [PostgreSQL 高级面试知识架构](./09-postgresql-advanced.md) | ⭐⭐⭐⭐ | 深入 PG 核心特性（MVCC 元组级多版本机制、VACUUM 原理与调优、可见性映射表）、索引体系（B-tree、Hash、GiST、GIN、BRIN 索引选择策略、部分索引与覆盖索引）、SQL 高级特性（CTE 与递归查询、窗口函数全解、分区表高级用法）、数据类型与扩展（JSONB 全文检索、PostGIS、自定义类型）、锁机制（表级锁与行级锁、死锁检测、咨询锁）、高可用复制（流复制、逻辑复制、Failover 策略）、性能调优（配置参数详解、查询计划分析、连接池管理）、与 MySQL 全面对比（架构差异、锁与 MVCC 对比、复制对比、索引对比、生态对比）。 |
| 10 | [Hologres 高级面试知识架构](./10-hologres-advanced.md) | ⭐⭐⭐ | 介绍 Hologres 实时交互式分析引擎的定位（HSAP 系统）、核心概念（存储计算分离架构、读写分离设计、实时写入原理）、存储引擎（行存与列存选择、Segment File 结构、Compaction 机制）、查询优化（SQL 调优、索引选择、查询计划解读）、数据导入（Flink 实时写入、批量导入、数据集成）、场景应用（实时报表、用户画像、实时 OLAP 大屏）、与 ClickHouse / Doris / StarRocks 对比分析。适合涉及实时数仓场景的后端或大数据工程师。 |

### 缓存与消息队列

| # | 文档 | 难度 | 简介 |
|---|------|------|------|
| 04 | [Redis 高级面试知识架构](./04-redis-advanced.md) | ⭐⭐⭐⭐⭐ | 覆盖 Redis 数据结构底层编码演进（从 ziplist 到 listpack、quicklist、skiplist）、核心原理（IO 多路复用、Reactor 模型、单线程 vs 多线程、持久化 RDB/AOF 深度对比、过期策略与内存淘汰）、高可用架构（主从复制原理、Sentinel 故障转移、Cluster 分片与请求路由、数据倾斜处理）、缓存设计（穿透/击穿/雪崩解决方案、更新一致性策略）、分布式场景（分布式锁 Redlock 争议、分布式限流滑窗、Lua 脚本原子性）、性能调优（内存优化、pipeline、bigkey 治理）、大厂综合案例。 |
| 05 | [RabbitMQ 高级面试知识架构](./05-rabbitmq-advanced.md) | ⭐⭐⭐⭐ | 讲解 RabbitMQ 核心概念（Exchange 四种类型详解、Binding 路由规则）、消息可靠性（生产者确认 Confirm、持久化策略、消费者 Ack 机制及重试、死信队列与死信交换机）、高级特性（延迟队列实现方式、优先级队列、TTL）、集群与高可用（普通集群与镜像队列、Quorum Queue、Federation 与 Shovel）、性能调优（预取计数、连接与通道管理、流控机制）、生产实践（消息幂等性、顺序消息保证、大规模集群运维）、与 Kafka 全面对比。 |
| 06 | [Kafka 高级面试知识架构](./06-kafka-advanced.md) | ⭐⭐⭐⭐⭐ | 深度剖析 Apache Kafka 消息模型与架构演进、存储原理（分区与日志分段、索引文件结构、零拷贝技术）、生产者原理（分区策略、ACK 参数调优、幂等与事务）、消费者原理（Rebalance 机制、位移提交策略、静态消费组）、副本机制（ISR 设计、Leader/Follower 数据一致性、Unclean Leader 选举）、控制器与协调器（Controller 选举与变更、Group Coordinator 协议）、KRaft 模式（去 ZooKeeper 架构、Quorum 共识算法）、性能调优与生产运维、与 RabbitMQ 场景对比。 |

### 容器与编排

| # | 文档 | 难度 | 简介 |
|---|------|------|------|
| 07 | [Docker 高级面试知识架构](./07-docker-advanced.md) | ⭐⭐⭐⭐ | 覆盖 Docker 核心原理（Namespace 隔离、Cgroups 资源限制、UnionFS 文件系统层叠与 COW 机制）、Dockerfile 最佳实践（多阶段构建、层缓存优化、安全编写检查）、网络模型（Bridge / Host / Overlay 网络、DNS 与端口映射）、存储管理（Volume 与 Bind Mount 对比、存储驱动选型）、资源限制（CPU 与内存配额、磁盘 IO 限制）、Docker Compose 生产化（多容器编排、健康检查与依赖管理）、镜像仓库管理（Harbor 搭建与 GC、镜像安全扫描）、安全最佳实践（Rootless 模式、Seccomp 配置）、与 Kubernetes 的关系与演进路径。 |
| 08 | [Kubernetes 高级面试知识架构](./08-kubernetes-advanced.md) | ⭐⭐⭐⭐⭐ | 详解 Kubernetes 架构原理（API Server 认证授权准入、Controller Manager 控制器模式、Scheduler 调度框架与算法）、核心资源（Pod 生命周期与探针、Deployment 滚动更新与回滚、Service 与 Ingress、ConfigMap/Secret）、网络模型（CNI 插件、网络策略、Service Mesh 集成）、存储管理（PV/PVC 动态供给、StorageClass 与 CSI）、调度与资源管理（资源配额与 LimitRange、PriorityClass、节点亲和性与污点容忍）、安全机制（RBAC 纵深设计、Pod Security Admission、NetworkPolicy 微隔离）、可观测性（Metrics Server / Prometheus 监控体系、Loki 日志聚合）、服务网格（Istio 核心组件、流量管理、mTLS）、生产运维（集群升级、备份与灾备、成本优化）、对后端开发者的核心要求。 |

### 实时通信

| # | 文档 | 难度 | 简介 |
|---|------|------|------|
| 11 | [WebSocket 高级面试知识架构](./11-websocket-advanced.md) | ⭐⭐⭐⭐ | 覆盖 WebSocket 协议原理（HTTP Upgrade 握手、帧格式与 Masking、关闭握手）、服务端实现（连接管理、心跳与保活、消息编解码）、分布式 WebSocket 架构（Gateway 层设计、Redis Pub/Sub 广播、一致性哈希路由）、可靠性保障（消息确认与重传、离线消息存储、QoS 级别设计）、安全防护（WSS/TLS 配置、Origin 校验与 CSWSH 防御、连接数限流与鉴权）、性能优化（内存管理、Goroutine 模型/C10M 优化、零拷贝数据传输）、场景实战（IM 系统、实时协作编辑、游戏同步、实时推送）、与 SSE / gRPC Stream / WebTransport 替代方案对比。 |

### 架构设计

| # | 文档 | 难度 | 简介 |
|---|------|------|------|
| 12 | [微服务架构高级面试知识架构](./12-microservices-advanced.md) | ⭐⭐⭐⭐⭐ | 系统讲解微服务基础理论（服务拆分原则、DDD 战略设计、演进式架构）、通信机制（REST vs gRPC vs GraphQL 选型、序列化对比、异步消息解耦）、服务治理（注册发现、负载均衡、熔断降级、重试与超时）、数据管理（分布式事务 Saga / TCC / 本地消息表与 Outbox 模式、CQRS 与事件溯源）、网关与入口（Kong / APISIX / Spring Cloud Gateway 对比、限流与鉴权、BFF 设计模式）、可观测性（Metrics / Logging / Tracing 三大支柱、OpenTelemetry 实践）、CI/CD 与 GitOps 流水线、生产实践（容器化部署、分布式配置中心、全链路压测）、面试加分项（Serverless 与 FaaS、多活架构、混沌工程）。 |
| 13 | [系统设计高级面试知识架构](./13-system-design-advanced.md) | ⭐⭐⭐⭐⭐ | 提供系统设计面试完整方法论与答题框架（需求澄清-场景估算-数据模型-核心流程-组件选型-架构纵深）、8 道经典题目深度剖析（短 URL、分布式 ID 生成器、分布式限流器、IM 系统、秒杀系统、Feed 流系统、分布式任务调度、实时排行榜）、核心组件选型指南（数据库、缓存、消息队列、微服务框架、分布式协调服务、对象存储的全方位选型决策树）、架构评审能力（评审流程、检查清单、反模式识别）、CAP/BASE 理论在架构设计中的实践（CP vs AP 权衡、最终一致性多种实现策略）、面试答题框架与技巧（功能需求与非功能需求拆解、估算方法、引导式面试技巧）。 |

---

## 推荐学习路径

### 快速面试准备路线（1-2 周）

适合基础扎实、需要在短时间内系统回顾并聚焦高频考点的高级开发。

```
Week 1 ─── 核心基础
├── Day 1-2  语言栈：PHP（01）或 Go（02），选主栈语言
├── Day 3-4  数据库：MySQL（03）索引优化 + 事务隔离级别
├── Day 5    缓存：Redis（04）数据结构 + 缓存设计三大坑
├── Day 6    消息队列：RabbitMQ（05）或 Kafka（06），选一个掌握核心
└── Day 7    架构设计：系统设计方法论（13）答题框架

Week 2 ─── 广度补齐 + 实战
├── Day 8    容器化：Docker（07）核心原理 + Dockerfile 优化
├── Day 9    编排：K8s（08）核心资源 + Pod 生命周期
├── Day 10   架构：微服务（12）服务拆分 + 分布式事务
├── Day 11   实时通信：WebSocket（11）协议原理 + 分布式架构
├── Day 12   系统设计：任选 2 道经典题目手写架构图
├── Day 13   综合复盘 + 交叉知识点索引回顾
└── Day 14   模拟面试（以系统设计题目为主）
```

### 系统学习路线（1-2 月）

适合希望建立完整知识体系、深入源码层面理解的架构师候选人。

```
Phase 1 ─── 语言深层（第 1-2 周）
├── PHP（01）+ Go（02）双栈对比学习
│   ├── 并发模型对比：PHP 多进程 vs Go Goroutine
│   ├── 内存管理对比：Zend 引用计数 vs Go GC
│   └── 性能调优对比：Xdebug + Blackfire vs pprof + flamegraph
└── 每日基础练习：LeetCode + 语言特性编码

Phase 2 ─── 数据存储（第 3-4 周）
├── MySQL（03）+ PostgreSQL（09）双库深度
│   ├── MVCC 实现机制对比
│   ├── 索引体系与优化策略
│   ├── 高可用架构方案对比
│   └── 分库分表 vs 原生分区
├── Redis（04）源码级理解
└── Hologres（10）实时数仓概念补齐

Phase 3 ─── 中间件与基础设施（第 5-6 周）
├── 消息队列：RabbitMQ（05）业务场景 + Kafka（06）高吞吐场景
├── 容器化：Docker（07）原理 + Compose 生产化
├── 编排：K8s（08）核心 API + 运维实操
└── 实时通信：WebSocket（11）IM 场景实现

Phase 4 ─── 架构与综合（第 7-8 周）
├── 微服务架构（12）+ 系统设计（13）融合学习
│   ├── 每个系统设计题目同时标注关联的微服务知识点
│   └── 每周 2 次架构白板练习
├── 交叉知识点专题查漏补缺
└── 以 3-5 道大厂真题做完整模拟（从需求澄清到架构图交付）
```

---

## 高频交叉知识点索引

以下高频面试 / 架构话题涉及多个技术领域，标注了关联文档编号，方便交叉查阅。

| 话题 | 关联文档 | 说明 |
|------|----------|------|
| **分布式事务** | 03-MySQL, 05-RabbitMQ, 06-Kafka, 12-微服务 | MySQL 事务基础（ACID、XA）-> 消息队列的事务消息 / 最终一致性 -> 微服务 Saga / TCC / Outbox 模式 |
| **分布式锁** | 04-Redis, 09-PostgreSQL, 12-微服务 | Redis SETNX + Redlock、PG 咨询锁、ZooKeeper 临时节点方案对比及选型取舍 |
| **分布式唯一 ID** | 02-Go, 03-MySQL, 04-Redis, 13-系统设计 | 雪花算法（Snowflake）在 Go 中的实现、MySQL 自增 ID / 号段模式、Redis INCR 方案、Leaf / UidGenerator |
| **缓存一致性** | 03-MySQL, 04-Redis, 09-PostgreSQL | Cache-Aside / Read-Through / Write-Through 模式、延迟双删、订阅 binlog 同步、本地缓存与分布式缓存协同 |
| **消息可靠性** | 05-RabbitMQ, 06-Kafka | 生产端确认、Broker 持久化、消费端 Ack / 重试 / 死信、Exactly-Once 语义在不同 MQ 中的实现差异 |
| **顺序消息** | 03-MySQL, 04-Redis, 05-RabbitMQ, 06-Kafka | Kafka 分区内顺序 + 生产者幂等、RabbitMQ 单一队列顺序、数据库乐观锁实现、Redis List 保证消息有序消费 |
| **高可用架构** | 03-MySQL, 04-Redis, 05-RabbitMQ, 06-Kafka, 08-K8s, 12-微服务 | 各组件 HA 方案横向对比：MySQL MGR / Redis Sentinel & Cluster / RabbitMQ Quorum Queue / Kafka ISR / K8s 自愈 |
| **限流设计** | 04-Redis, 08-K8s, 12-微服务, 13-系统设计 | Redis 滑动窗口 / Token Bucket、K8s HPA + LimitRange、网关层限流（全局 vs 分布式）、Guava RateLimiter |
| **服务发现** | 08-K8s, 12-微服务 | K8s Service + CoreDNS vs 传统注册中心（Nacos / Consul / Etcd），K8s 环境中的服务发现最佳实践 |
| **可观测性** | 02-Go, 08-K8s, 12-微服务 | Metrics（Prometheus + Grafana）、Logging（Loki / ELK）、Tracing（OpenTelemetry + Jaeger）、Go pprof 集成 |
| **Docker 化部署** | 07-Docker, 08-K8s, 12-微服务 | 多阶段构建、基础镜像选型（Alpine / Distroless）、Docker Compose 开发 -> K8s 生产、微服务容器化注意事项 |
| **实时推送** | 05-RabbitMQ, 06-Kafka, 11-WebSocket, 12-微服务 | WebSocket 集群 + MQ 广播：RabbitMQ Fanout Exchange 或 Kafka 多消费者组实现实时消息推送的技术选型 |
| **事务消息** | 05-RabbitMQ, 06-Kafka, 12-微服务 | RabbitMQ 确认机制 + 本地消息表 vs Kafka 事务 API + 幂等生产者，在微服务最终一致性场景中的实践对比 |
| **数据分片与分库分表** | 03-MySQL, 04-Redis, 06-Kafka, 09-PostgreSQL | MySQL 分库分表中间件（ShardingSphere / MyCat）、Redis Cluster 哈希槽、Kafka 分区机制、PG 原生分区表对比 |
| **秒杀系统** | 04-Redis, 06-Kafka, 12-微服务, 13-系统设计 | Redis 预扣库存 + 异步削峰（Kafka / RabbitMQ）、服务隔离与熔断、动静分离、系统设计完整方法论应用 |

---

## 版本说明与更新日志

### 当前版本：v1.0.0

| 文档 | 版本 | 更新日期 | 备注 |
|------|------|----------|------|
| 01-PHP 高级面试知识架构 | v1.0 | 2026-06 | 初版完成 |
| 02-Go 高级面试知识架构 | v1.0 | 2026-06 | 初版完成 |
| 03-MySQL 高级面试知识架构 | v1.0 | 2026-06 | 初版完成 |
| 04-Redis 高级面试知识架构 | v1.0 | 2026-06 | 初版完成 |
| 05-RabbitMQ 高级面试知识架构 | v1.0 | 2026-06 | 初版完成 |
| 06-Kafka 高级面试知识架构 | v1.0 | 2026-06 | 初版完成 |
| 07-Docker 高级面试知识架构 | v1.0 | 2026-06 | 初版完成 |
| 08-Kubernetes 高级面试知识架构 | v1.0 | 2026-06 | 初版完成 |
| 09-PostgreSQL 高级面试知识架构 | v1.0 | 2026-06 | 初版完成 |
| 10-Hologres 高级面试知识架构 | v1.0 | 2026-06 | 初版完成 |
| 11-WebSocket 高级面试知识架构 | v1.0 | 2026-06 | 初版完成 |
| 12-微服务架构高级面试知识架构 | v1.0 | 2026-06 | 初版完成 |
| 13-系统设计高级面试知识架构 | v1.0 | 2026-06 | 初版完成 |

### 更新日志

```
2026-06-15 | v1.0.0
  - 初始版本发布，覆盖 13 个技术领域
  - 首个总索引 README 创建
```

---

> **维护说明**：本文档由团队技术委员会维护。新增技术领域文档时，请同步更新总索引 README 中的分组索引、交叉知识点索引和版本说明。  
> **目录路径**：`F:\study\aiagent-explore\docs\backend-interview\`
