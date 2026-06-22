# AppsFlyer 广告归因对接 — 面试高频考点整理

> 基于 `appsflyer-attribution-integration.md` 提取，按面试关注维度重组。

---

## 目录

1. [基础概念（必问）](#1-基础概念必问)
2. [客户端 SDK（高频）](#2-客户端-sdk高频)
3. [后端对接（高频）](#3-后端对接高频)
4. [架构与流程（进阶）](#4-架构与流程进阶)
5. [异常与容错（进阶）](#5-异常与容错进阶)
6. [数据与对账（进阶）](#6-数据与对账进阶)
7. [场景设计题（综合）](#7-场景设计题综合)
8. [快速自查速记卡](#8-快速自查速记卡)

---

## 1. 基础概念（必问）

### Q1: 什么是 MMP？AppFlyer 的核心能力有哪些？

**考点**: 是否理解 MMP 在整个广告生态中的位置。

**参考答案**:

- MMP = Mobile Measurement Partner，移动广告归因与营销分析平台
- 核心能力五个维度：
  1. **广告归因** — 判断安装/付费来自哪个渠道/素材
  2. **深度链接** — Deferred Deep Linking（未安装跳商店→安装后还原落地页）
  3. **防作弊** — 设备指纹 + 点击时间 + IP 多维信号识别假量
  4. **LTV/ROAS** — 生命周期价值与广告支出回报
  5. **全漏斗分析** — 曝光→点击→安装→付费→留存全链路

---

### Q2: 确定性归因 vs 概率归因的区别？什么场景会触发概率归因？

**考点**: 归因引擎的核心匹配逻辑。

**参考答案**:

| | 确定性归因 | 概率归因 |
|---|---|---|
| **匹配方式** | 设备 ID 精确匹配（GAID/IDFA） | IP + UserAgent + 时间窗口模糊匹配 |
| **准确率** | 高 | 中 |
| **触发场景** | 设备 ID 可获取时 | iOS ATT 被拒绝 / 设备无 Google Play Services / 受限追踪 |

> **关键面试点**: iOS 14.5+ 后 ATT 弹窗授权率通常只有 30-50%，意味着 **50%+ 的 iOS 用户落在概率归因**，准确度天然受损。

---

### Q3: SAN 和 Non-SAN 的区别？为什么 SAN 的归因逻辑不经过 MMP？

**考点**: 是否理解自归因渠道的特殊性。

**参考答案**:

| | SAN (自归因渠道) | Non-SAN (非自归因渠道) |
|---|---|---|
| **代表** | Meta / Google / Apple Search Ads / TikTok | 大部分 DSP / Ad Network |
| **归因方** | 渠道自己完成归因 | AppsFlyer 完成归因 |
| **AF 角色** | 通过 API 拉取渠道的归因结果 | 自己匹配点击数据与安装数据 |
| **数据差异** | AF 数据可能与渠道后台不一致（常见坑） | 以 AF 为准 |

> **延伸追问**: "如果 Facebook 后台显示的安装数和 AppsFlyer 差 20%，可能的原因是什么？"
> — 归因窗口不同 / 统计口径不同（Facebook 按展示时间，AF 按安装时间）/ 数据延迟 / ATT 限制

---

### Q4: 归因窗口是什么？各个窗口的默认值和意义？

**考点**: 对归因时效性的理解。

**参考答案**:

| 窗口 | 默认 | 含义 |
|------|:--:|------|
| 点击归因窗口 | **7 天** | 点广告后 7 天内安装 → 归因给该点击 |
| 展示归因窗口 | **1 天** | 看广告后 1 天内安装 → 归因给该展示 |
| 再归因窗口 | **90 天** | 沉默用户再次激活 → 可重新归因 |
| 归因过期 | **30 天** | 安装事件上报后 30 天仍未匹配 → 放弃归因，降级为自然量 |

> **延伸追问**: "为什么点击窗口比展示窗口长？" — 点击是高意图信号，用户在安装前可能需要时间比较/下载；展示是被动曝光，信号弱所以窗口短。

### Q5: GAID / IDFA / IDFV / AppsFlyer ID / Customer User ID 各自的用途和区别？

**考点**: 对归因中各个 ID 体系的理解。

**参考答案**:

| 标识 | 平台 | 用途 | 是否可重置 |
|------|:--:|------|:--:|
| **GAID** | Android | 广告标识，归因核心 ID | ✅ 用户可重置 |
| **IDFA** | iOS | 广告标识，需 ATT 授权 | ✅ 用户可重置/关闭 |
| **IDFV** | iOS | 同厂商内唯一，卸载后重置 | ❌ 卸载即变 |
| **AppsFlyer ID** | 双端 | AF 内部唯一 ID（设备+App 维度） | ❌ 由 AF 管理 |
| **Customer User ID** | 双端 | 业务方用户 ID，跨设备关联 | ❌ 由业务方管理 |

> **关键面试点**: `setCustomerUserId` 必须在 `start()` 之前调用，否则本次 Session 不带此 ID。

---

## 2. 客户端 SDK（高频）

### Q6: SDK 初始化的关键步骤，以及 Android 和 iOS 的关键差异？

**考点**: 是否真正做过 SDK 集成。

**参考答案**:

**Android**:
```
Application.onCreate() → setDevKey → setAppId → init(conversionListener) → start()
```

**iOS**:
```
didFinishLaunching → set devKey + appleAppID → ATT 授权 → sceneDidBecomeActive 中 start()
```

**关键差异**:

| 差异点 | Android | iOS |
|--------|---------|-----|
| Conversion Data | 有同步回调 `onConversionDataSuccess` | **无回调！**需等服务端 Push API |
| ATT 弹窗 | 不需要 | iOS 14.5+ 必须，否则无 IDFA |
| 初始化时机 | Application.onCreate() | SceneDelegate.sceneDidBecomeActive |

> **面试高频追问**: "iOS 没有 Conversion Data 回调，那客户端和运营怎么拿到渠道信息？"
> — 靠后端 Push API 接收 AF 归因推送 → 业务后端落库 → 客户端通过业务接口查询

---

### Q7: SDK 自动上报的事件有哪些？哪些必须手动上报？

**考点**: 事件体系的完整度。

**参考答案**:

| 自动事件 | 触发时机 |
|----------|----------|
| `install` | 首次启动（SDK 自动，不需要任何代码） |
| `af_start` | 每次启动 |
| `re-attribution` | 再归因发生 |
| `uninstall` | 卸载推断（静默推送） |

**必须手动上报**:
- 🔴 `af_purchase` — 付费（含 revenue / currency / content_id / order_id）
- 🔴 `af_complete_registration` — 注册完成
- 🟡 `af_login` / `af_level_achieved` / `af_tutorial_completion`
- 🟢 自定义业务事件

---

### Q8: 深度链接（OneLink）的 Delayed Deep Link 原理？

**考点**: 对 OneLink 延迟深链机制的理解。

**参考答案**:

```
用户点击 OneLink
    ├─ App 已安装 → 直接拉起 → onDeepLinking()
    └─ App 未安装 → 跳 App Store / Google Play
                        → 下载安装
                        → 首次打开时 AF SDK 自动拉取"延迟深度链接数据"
                        → onDeepLinking() 回调
                        → 路由到目标页面
```

> **关键点**: Deferred Deep Linking 不需要额外代码，SDK 在首次 install 请求中自动携带 OneLink 点击信息。

---

### Q9: Revenue 事件上报需要注意哪些字段？

**考点**: 对付费归因数据完整性的敏感度。

**参考答案**:

| 字段 | 必要性 | 原因 |
|------|:--:|------|
| `af_revenue` | 🔴 必须 | 金额，用于 ROAS |
| `af_currency` | 🔴 必须 | 币种，避免多币种混算 |
| `af_order_id` | 🔴 必须 | 去重键，防止重复计数 |
| `af_content_id` | 🟡 建议 | 商品/订阅 ID |
| `af_receipt` | 🟡 建议 | iOS 支付回执（验真） |
| `af_content_type` | 🟢 可选 | subscription / consumable |

> **面试追问**: "为什么 af_order_id 这么重要？"
> — 客户端 SDK + 后端 S2S 双端都可能上报付费事件，AF 侧 + 业务侧都依赖 af_order_id 去重。没有它，同一笔订单可能被计为 2 次付费，LTV 翻倍。

---

## 3. 后端对接（高频）

### Q10: Push API、S2S API、Pull API 分别用于什么场景？

**考点**: 三大 API 的分工是否清晰。

**参考答案**:

| API | 方向 | 场景 | 时效性 |
|-----|------|------|:--:|
| **Push API** | AF → 业务后端 | 归因完成时实时推送归因结果 | 实时（秒级） |
| **S2S API** | 业务后端 → AF | 服务端主动上报事件（付费/注册等） | 实时 |
| **Pull API** | 业务后端 → AF | 定时拉取汇总报表（安装/事件/留存/卸载） | T+1 / 每小时 |

**使用策略**:
- Push API 是**主通道**，归因数据靠它
- S2S 是**兜底 + 付费事件主通道**（服务端有支付验证能力）
- Pull API 是**对账 + 补全通道**（定时拉缺失数据）

---

### Q11: Push API 回调的后端处理流程怎么写？（白板题）

**考点**: 能否写出可信、可用的回调处理逻辑。

**参考答案要点**（按顺序）:

```
1. 签名校验 → HMAC-SHA256(X-AppsFlyer-Signature, dev_key)
2. 去重检查 → 基于 appsflyer_id + event_type + event_time
3. 字段校验 → appsflyer_id / event_type / event_time / media_source 必填
4. 异步投递 → 立即返回 200（AF 要求 2s 内响应），入队列异步处理
5. 数据落库 → users_attribution upsert + attribution_events append
6. 关联用户 → 如果有 customer_user_id，关联业务用户表
```

> **面试追问**: "为什么不能同步处理？为什么要立即返回 200？"
> — AF 回调有超时限制（通常 2s）。如果同步入库/调外部服务导致超时，AF 侧会认为推送失败触发重试，加剧压力。

---

### Q12: 为什么付费事件推荐后端 S2S 上报而非客户端 SDK？

**考点**: 对"信任边界"的认知。

**参考答案**:

1. **支付验证能力** — 服务端有 Apple/Google 支付回执（Receipt）验证，客户端可伪造
2. **防作弊** — 客户端被破解后可直接伪造付费事件，服务端是可信环境
3. **网络可靠性** — 服务端网络稳定，不像移动端可能断网/切后台
4. **复杂场景支持** — 订阅续费/退款/补单等只有服务端能感知
5. **幂等性** — 服务端可以通过 order_id 精确去重

> **核心逻辑**: 客户端是**不可信环境**，金额相关数据必须以服务端为准。

---

### Q13: 如何设计去重机制？

**考点**: 对消息重复投递的理解和应对。

**参考答案**:

**AF 侧去重**（S2S 上报）:
- 使用 `af_order_id` 作为去重键，AF 内部 30 天内同 order_id 只计一次

**业务侧去重**（Push API 接收）:
1. 构建 dedup_key: `{appsflyer_id}|{event_type}|{event_time}`
2. 写入时用数据库唯一索引（`UNIQUE KEY uk_dedup`）天然防重
3. 或 Redis `SETNX` 做轻量去重（TTL 24h 足够，归因窗口内不会重复）

**双端上报去重**:
- SDK 和 S2S 同时上报时，以 `af_order_id` 为关联键
- AF 侧有内置去重，业务侧按 order_id 做最后一次写入覆盖

---

## 4. 架构与流程（进阶）

### Q14: 用户从点击广告到归因完成的全链路是怎样的？（白板题）

**考点**: 全局视野，能否串起所有节点。

**参考答案**:

```
T0: 用户点击 Facebook 广告
     → 渠道记录 click_id + 设备指纹 → 发送给 AppsFlyer

T1: 跳转 App Store 下载 → 安装 → 首次打开
     → AF SDK 自动上报 install（含设备指纹 + IP + AF ID）
     
T2: AF 归因引擎匹配
     → click 数据 ↔ install 数据
     → 匹配成功 → ATTRIBUTED
     → 匹配失败 → ORGANIC
     
T3: AF 推送归因结果
     → Push API → 业务后端 → 签名校验 → 去重 → 落库
     → Android: Conversion Data 回调 → 客户端也拿到归因数据
     → iOS: 只能等 Push API 结果
     
T4: 用户后续行为
     → 注册/付费 → SDK + S2S 双端上报 → AF 归因给原始渠道
     → 后端接收 Push API 付费事件 → 更新 LTV
```

---

### Q15: 归因状态机是怎么设计的？哪些是终端态？

**考点**: 对状态流转的全局把控。

**参考答案**:

```
NOT_INIT → ATTRIBUTING → ATTRIBUTED / ORGANIC / ATTRIBUTION_FAILED
                                │
                         (90天沉默后)
                                │
                        RE_ATTRIBUTING → RE_ATTRIBUTED
                                │
                         (卸载重装)
                                │
                           RE_INSTALL → 重新开始
```

**终端态**（不会再自动变化）:
- `ORGANIC` — 自然量
- `ATTRIBUTED` — 针对某次安装的归因已确认
- `ATTRIBUTION_FAILED` — 最终降级为 ORGANIC

**非终端态**（仍可能变化）:
- `ATTRIBUTING` — 等待 AF 匹配中
- `RE_ATTRIBUTING` — 等待再归因结果

---

### Q16: iOS 和 Android 的归因链路有何本质差异？

**考点**: 对平台差异的深度理解。

**参考答案**:

| 维度 | Android | iOS |
|------|---------|-----|
| **设备 ID** | GAID（几乎 100% 可用） | IDFA（需 ATT 授权，授权率 30-50%） |
| **Conversion Data 回调** | ✅ 有同步回调 | ❌ 无回调 |
| **归因准确率** | 高（确定性归因为主） | 中（大量概率归因） |
| **客户端获知渠道** | 可立即获知 | 需等 Push API 或轮询业务后端 |
| **首次启动 Scenario** | onConversionDataSuccess 就能拿到 campaign | getAttributionData() 返回不完整数据 |

> **设计启示**: 永远不要在前端根据归因数据做即时决策（比如首屏展示），iOS 必然拿不到。

---

### Q17: Customer User ID 的作用是什么？什么时机设置？

**考点**: 跨设备/跨平台用户关联。

**参考答案**:

- **作用**: 将 AF 的设备级归因与业务的用户级数据打通
- **场景**: 
  - 用户先在 Web 浏览商品 → 在 App 内完成购买 → 需要关联同一用户
  - 用户换手机 → 需要保留原归因数据（通过登录态关联）
- **设置时机**: 必须在 `start()` 之前
  - 登录 → `setCustomerUserId(user_id)` → `start()`
  - 登出 → `setCustomerUserId(null)`

> **坑**: 如果先 `start()` 后 `setCustomerUserId`，本次 Session 不会携带 CUID，只能等下次启动。

---

## 5. 异常与容错（进阶）

### Q18: iOS ATT 弹窗被拒后，归因数据怎么办？

**考点**: 对 iOS 隐私政策的应对经验。

**参考答案**:

| 影响 | 应对 |
|------|------|
| 无 IDFA | 使用 IDFV + IP + UA 做概率归因 |
| 准确度下降 | Push API 收到的归因结果优先级高于客户端 |
| 无法确定到设备级 | 接受"渠道级别"归因即可，不奢求精确到素材 |
| LTV 计算误差 | 用 cohort 维度而非单用户维度 |
| ATT 弹窗时机 | 在需要 IDFA 的功能场景自然触达（如个性化推荐），比冷启动强制弹窗转化率高 |

---

### Q19: 用户安装 App 时无网络，联网后还能拿到归因吗？

**考点**: 对归因窗口和 SDK 本地缓存的了解。

**参考答案**:

- ✅ 可以，但有条件：
  - AF SDK 有本地事件缓存机制，install 事件会在本地持久化
  - 网络恢复后，SDK 自动补报
  - **关键限制**: 必须在归因窗口过期前（最长 30 天）补报成功
  - 超过 30 天 → 归因引擎放弃匹配 → ORGANIC

---

### Q20: Push API 推送失败怎么兜底？

**考点**: 对数据可靠性保障的设计。

**参考答案**:

三层兜底：

| 层级 | 机制 | 时效 |
|:--:|------|:--:|
| L1 | AF 侧自动重试 3 次（间隔 15 分钟） | 45 分钟内 |
| L2 | Pull API 定时拉取（每小时） | T+1h |
| L3 | 对账脚本对比 AF Dashboard ↔ 业务库差异 | T+1d |

> **面试追问**: "Push API 连续失败超过 1 小时怎么办？"
> — 触发告警 → 人工介入 → 排查后端服务是否挂了 / 域名是否可解析 / HTTPS 证书是否过期 → 修复后通过 Pull API 补全缺失数据

---

### Q21: 广告欺诈常见手法和防御手段？

**考点**: 对反作弊的了解。

**参考答案**:

| 欺诈手法 | 原理 | 防御 |
|----------|------|------|
| **点击泛滥** | 伪造海量点击，碰概率"撞上"自然安装 | 点击-安装时间分布异常检测 |
| **设备农场** | 大量真机/模拟器刷安装 | 设备指纹去重 + IP 聚集度分析 |
| **SDK 伪造** | 模拟 install 请求 | AF Protect360 + 后端 S2S 校验 |
| **归因劫持** | 在用户下载过程中插入虚假点击，窃取归因 | 点击-安装时间间隔 + IP 一致性 |

> **核心防御思路**: 用 AF Protect360 + 后端异常指标监控（某渠道突然暴涨 / CTR 异常高 / 留存率异常低）

---

## 6. 数据与对账（进阶）

### Q22: 如何进行数据对账？有哪些核心指标？

**考点**: 对数据可靠性的工程化思考。

**参考答案**:

```
每日对账四维度:

1. 安装数对比: AF Dashboard vs 业务库
   告警阈值: 差异 > 2%

2. 归因覆盖率: 有归因安装 / 总安装
   告警阈值: < 85%

3. 付费事件数对比: AF 付费事件 vs 支付网关订单数
   告警阈值: 差异 > 1%

4. 渠道成本对比: AF 成本 vs 渠道端成本
   告警阈值: 差异 > 5%
```

---

### Q23: LTV 怎么计算？归因数据如何参与？

**考点**: 理解归因→LTV 的数据链路。

**参考答案**:

```
LTV = SUM(该渠道所有用户在一定时间窗口内的总收入) / 该渠道安装数

关键点:
- 每个用户的每笔付费都归因到其 install 时的渠道（media_source）
- 即使该用户 90 天后通过再营销重新激活，原始渠道仍然保留为 contributor1
- LTV 的时间窗口通常看 D7 / D30 / D90 / D180
- 对于自然量(organic)，LTV 用于对比评估买量效率
```

---

### Q24: 数据库表怎么设计才能支撑按渠道/国家/时间的多维度分析？

**考点**: 对 OLTP + OLAP 的设计经验。

**参考答案**:

索引策略见文档第 7 章的 DDL：

```sql
-- OLTP 查询：按用户查归因
INDEX idx_user_id (user_id)

-- OLAP 查询：按渠道 + 国家 + 时间
INDEX idx_media_source (media_source)
INDEX idx_platform_country (platform, country_code)
INDEX idx_install_time (install_time)
```

> **延伸**: 如果分析查询量很大（BI 看板），建议 CDC 同步到 ClickHouse / Hologres 等 OLAP 引擎，不在 MySQL 上跑聚合。

---

## 7. 场景设计题（综合）

### Q25: 一个用户在 Facebook 点了广告，但在下载 App 的过程中又点了 Google 广告，最终归因给谁？

**考点**: Last Click 归因模型的理解。

**参考答案**:

**默认归因给 Google（Last Click 模型）**，因为 Google 是最后一个触点。

但在 Push API 的 Payload 中：
- `media_source` = Google（最后点击的渠道）
- `contributor1_media_source` = Facebook（辅助归因，第一个渠道）

> **延伸**: 不同 MMP 支持配置不同归因模型（Last Click / 多触点加权 / 时间衰减），通常是渠道侧或运营在 AF 后台配置。

---

### Q26: 假设你接手一个已有项目，发现 AF 后台的安装数比业务库多 30%，你会如何排查？

**考点**: 结构化故障排查能力。

**参考答案**:

```
排查清单（从高概率到低概率）:

1. ❓ Push API 是否有丢数据？
   → 检查 attribution_events 表的最近 24h 记录数 vs AF Dashboard

2. ❓ 去重是否正确？
   → 检查 dedup_key 是否设计合理，是否因去重导致丢数据

3. ❓ 统计口径是否一致？
   → AF 统计的是 install 事件数，业务库统计的是什么？
   → AF 可能包含 re-install + re-attribution

4. ❓ 是否有自然量未入库？
   → AF 的自然量是否也通过 Push API 推送了？

5. ❓ 时间窗口问题？
   → AF 按事件时间统计，业务库可能按写入时间统计

6. ❓ SDK 版本不一致？
   → 有些设备用的旧版 SDK 可能不上报某些事件
```

---

### Q27: 设计一个"新用户首单奖励"功能，如何确保归因正确，避免被刷？

**考点**: 归因+风控的综合设计。

**参考答案**:

```
设计要点:

1. 归因来源验证:
   └── 不信任客户端声称的渠道，以后端 Push API 接收的 media_source 为准

2. 防刷策略:
   ├── 设备指纹去重（一台设备只能享受一次）
   ├── IP 聚集度（同一 IP 大量新用户 → 可疑）
   ├── 行为轨迹（安装后按正常路径走完新手引导，而非直接购买）
   └── 最小时间间隔（安装到购买必须 > N 分钟）

3. 奖励发放:
   └── 必须有服务端验证，永远不信任客户端判断

4. 回滚机制:
   └── 如果 AF 后续推送归因类型变更为 re-install 或检测到作弊
      → 撤销奖励
```

---

## 8. 快速自查速记卡

| # | 问题 | 一句话要点 |
|:--:|------|------|
| 1 | MMP 是什么 | 移动广告归因平台，判定"哪个渠道带来了这个用户" |
| 2 | SAN vs Non-SAN | SAN 自己归因（Meta/Google/TikTok），Non-SAN 由 AF 归因 |
| 3 | 点击归因窗口 | 默认 7 天 |
| 4 | iOS Conversion Data 回调 | **没有！** iOS 没这个回调，等 Push API |
| 5 | ATT 授权被拒后 | 走概率归因（IDFV + IP + UA） |
| 6 | Push API 处理 | 验签 → 去重 → 校验 → 入队 → 返回 200 |
| 7 | 付费事件上报 | **S2S 为主，SDK 为辅**（服务端可信，防欺诈） |
| 8 | 去重键 | `appsflyer_id|event_type|event_time` |
| 9 | Customer User ID 时机 | **必须在 start() 之前**调用 |
| 10 | Push API 兜底 | AF 重试 3 次 + Pull API 补拉 + 每日对账 |
| 11 | 归因状态机终点 | ORGANIC / ATTRIBUTED / 降级后 ORGANIC |
| 12 | Deferred Deep Link | 未安装 → 跳商店 → 安装后 SDK 自动还原落地页 |
| 13 | GAID vs IDFA | GAID 几乎 100% 可用，IDFA 需 ATT 授权（30-50% 授权率） |
| 14 | LTV 归因规则 | 始终归因给首次安装的渠道（contributor1），再营销不覆盖 |
| 15 | 数据对账阈值 | 安装差异 < 2%，归因覆盖率 ≥ 85% |
| 16 | 防作弊核心 | AF Protect360 + 后端异常指标（CTR 暴涨/留存异常） |
| 17 | OneLink 原理 | 点击链接 → AF 判定已装/未装 → 拉起 App 或跳商店 |
| 18 | af_order_id 重要性 | 付费去重的唯一依据，没它 LTV 可能翻倍 |
| 19 | SDK 内置自动事件 | install / af_start / re-attribution / uninstall |
| 20 | 双端上报冲突解决 | AF 侧 order_id 去重 + 业务侧 dedup_key 唯一索引 |

---

> **面试准备建议**: 
> - 前 10 个概念题必须能流畅回答（基础面一定会问）
> - 流程题（Q14/Q15/Q20）建议在白板上画图练 3 遍
> - 场景题（Q25/Q26/Q27）展示的是"解决实际问题的能力"，是区分高级工程师和初级的核心
> - 每道题都可以追问"你这个项目里具体怎么做/遇到什么坑"，所以要对文档中涉及的细节心中有数
