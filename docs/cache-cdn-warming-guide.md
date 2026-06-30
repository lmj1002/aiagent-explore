# 缓存预热与 CDN 预热实战指南 —— 海外短剧场景

> 本文以**海外短剧平台**为业务背景，系统梳理缓存预热（Cache Warming）与 CDN 预热（Content Delivery Network Preloading）的落地方案。内容覆盖：分级缓存（本地缓存 / Redis / 服务端缓存）的预热策略、H5 活动页等静态数据预热、热门剧 / 目标投放剧 / 新剧的剧集数据预热，以及与**阿里云视频点播（VOD）** 在转码、播放、CDN 分发链路上的组合使用。
>
> 核心目标：在流量高峰（新剧上线、投放放量）到来之前，把数据提前"焐热"到离用户最近的缓存层，避免冷启动击穿后端与源站。

---

## 一、为什么需要预热：海外短剧的流量特征

短剧业务与传统长视频、电商有显著差异，这些差异直接决定了预热策略：

| 特征 | 说明 | 对预热的影响 |
|------|------|-------------|
| **单集短、追剧连续** | 单集 1~2 分钟，用户常一口气连刷十几集 | 命中第 1 集后，后续集大概率被访问 → 可顺序预热后续集 |
| **头部效应极强** | Top 5% 的剧贡献 80%+ 的播放量 | 预热集中在头部剧，性价比最高 |
| **投放驱动、流量突发** | 买量投放的目标剧集，广告点击瞬间涌入 | 投放配置即是预热信号，必须在放量前完成 |
| **新剧有明确上线时刻** | 运营排期，定点上线 | 可定时（上线前 N 分钟）批量预热 |
| **海外多地域** | 东南亚 / 中东 / 欧美等，CDN 节点全球分散 | 需按地域分别预热，热点剧因地区而异 |
| **冷启动代价高** | 首次访问要回源 DB / 调 VOD API / CDN 回源站 | 冷启动叠加突发流量 = 雪崩风险 |

**不预热会发生什么（冷启动雪崩链路）：**

```
投放广告点击 → 海量用户瞬时涌入某新剧
   → 本地缓存 miss → Redis miss → 打到 DB（剧集元数据）
   → 同时 CDN 边缘节点无视频分片 → 回源到 VOD/OSS 源站
   → DB 连接打满 + 源站带宽打满 → 接口超时 → 用户白屏/转圈 → 投放预算打水漂
```

预热的本质：**把"被动回源"变成"主动推送"**，用可控的预热流量，换取高峰期的稳定命中。

---

## 二、分级缓存架构与预热分工

短剧平台的读路径是一条**多级缓存漏斗**，预热要在每一层都有对应动作。从离用户最近到最远：

```
用户 App / H5
   │
   ▼
① CDN 边缘缓存 ──── 静态资源、H5 页面、视频分片（m3u8 / ts）
   │  (miss 回源)
   ▼
② 接入层 / 网关本地缓存 ── 路由配置、AB 实验、限流规则
   │
   ▼
③ 服务进程内本地缓存（Local Cache）── 超热点：首页榜单、配置字典
   │  (miss)
   ▼
④ Redis 分布式缓存 ──── 剧集元数据、播放地址、用户态、计数器
   │  (miss)
   ▼
⑤ 服务端缓存（DB 前的查询缓存 / 物化）── 复杂聚合结果、榜单快照
   │  (miss)
   ▼
⑥ 源数据：MySQL / Hologres / 阿里云 VOD
```

### 2.1 各级缓存的定位与预热内容

| 层级 | 典型载体 | 容量 / 命中特征 | 预热内容 | 失效策略 |
|------|---------|----------------|---------|----------|
| **① CDN 边缘** | 阿里云 CDN / VOD 加速域名 | 海量、地域分散 | H5 静态资源、剧封面图、视频 m3u8 + 前若干 ts 分片 | TTL + 主动刷新 |
| **② 网关本地** | Nginx/OpenResty `lua_shared_dict` | 小、毫秒级 | 域名路由、灰度规则、全局开关 | 主动 push + 短 TTL |
| **③ 进程内本地** | Caffeine(Java) / go-cache / `sync.Map` | 极小、纳秒级 | 首页榜单 ID 列表、配置字典、热门剧基础信息 | 短 TTL + 订阅失效 |
| **④ Redis** | Redis Cluster | 大、亚毫秒级 | 剧集详情、剧集列表、播放凭证、活动配置 | TTL + 主动更新 |
| **⑤ 服务端缓存** | 应用内查询缓存 / 预计算物化表 | 中 | 榜单聚合、推荐结果、统计快照 | 定时重算 |
| **⑥ 源数据** | MySQL / Hologres / VOD | —（兜底） | 不预热，作为回源终点 | — |

### 2.2 分级预热的核心原则

1. **由远及近、自底向上预热**：先把数据写入 Redis（④），再回填本地缓存（③），最后推 CDN（①）。顺序反了会导致上层预热时下层还是 miss，预热请求自己就把后端打挂。
2. **本地缓存只放"超热点 + 小数据"**：本地缓存有容量上限且每个实例一份，只预热 Top-N 头部剧与配置类数据，避免内存膨胀。
3. **预热限流，分批推进**：预热本身是流量，必须限速（令牌桶），分批灰度，否则预热 = 自我 DDoS。
4. **预热可观测**：每一层预热都要记录命中率、耗时、覆盖量，验证预热是否真正生效。

### 2.3 防止预热放大与缓存击穿

预热阶段大量 key 同时写入、同时过期，是缓存雪崩的高发期，三个必备措施：

- **TTL 加随机抖动**：`ttl = baseTTL + rand(0, jitter)`，避免同一批预热数据同时过期。
- **逻辑过期 + 异步重建**：热点剧采用"永不物理过期，value 内置逻辑过期时间"，过期后由后台线程异步重建，读请求始终返回旧值，杜绝击穿。
- **单飞（singleflight）回源**：同一 key 的并发 miss 只放一个请求回源，其余等待结果，防止预热遗漏的 key 被瞬时打穿。

```go
// Go：逻辑过期 + singleflight 回源（剧集详情示例）
type DramaCache struct {
    sf singleflight.Group
}

func (c *DramaCache) GetDrama(ctx context.Context, dramaID int64) (*Drama, error) {
    raw, _ := redisGet(ctx, dramaKey(dramaID))
    if raw != nil {
        d := decode(raw)
        if d.LogicalExpireAt.Before(time.Now()) {
            // 已逻辑过期：异步重建，本次仍返回旧值（不阻塞、不击穿）
            go c.rebuild(context.Background(), dramaID)
        }
        return d, nil
    }
    // 物理 miss（预热漏掉的冷数据）：singleflight 合并并发回源
    v, err, _ := c.sf.Do(dramaKey(dramaID), func() (any, error) {
        return c.loadFromDBAndCache(ctx, dramaID)
    })
    if err != nil {
        return nil, err
    }
    return v.(*Drama), nil
}
```

---

## 三、静态数据预热：H5 活动页与配置

短剧平台的拉新、留存高度依赖 H5 活动页（充值返利、签到、抽奖、节日活动）。这类页面有两部分需要分别预热：**静态资源**（走 CDN）和**页面动态数据**（走 Redis/接口）。

### 3.1 H5 静态资源预热（CDN 层）

活动页的 HTML/JS/CSS/图片在构建发布后，CDN 边缘节点初始是空的。运营活动定点开始（如整点开抢），首批用户会全部回源，源站瞬时压力极大。

**预热做法：发布即推送（PushObjectCache）**

```bash
# 发布流水线最后一步：把活动页资源 URL 推送到 CDN 边缘节点
# 阿里云 CDN OpenAPI: PushObjectCache（预热）
POST /  Action=PushObjectCache
  ObjectPath=
    https://cdn.example.com/act/spring/index.html
    https://cdn.example.com/act/spring/app.[hash].js
    https://cdn.example.com/act/spring/app.[hash].css
    https://cdn.example.com/act/spring/banner.webp
  Area=overseas          # 海外节点
```

要点：
- **预热与刷新区分**：`PushObjectCache`（预热）是把资源**主动拉到**边缘节点；`RefreshObjectCaches`（刷新）是把边缘**已有的旧资源标记失效**。版本更新时：先 Refresh 旧 URL，再 Push 新 URL。
- **用 hash 文件名 + 长 TTL**：JS/CSS 带内容 hash，`Cache-Control: max-age=31536000, immutable`，更新即换 URL，无需刷新。
- **HTML 短 TTL + 预热**：入口 HTML 用短 TTL（如 60s），每次发布后预热。
- **按地域预热**：海外活动按目标市场选 `Area`，只预热实际投放的地域节点。

### 3.2 H5 页面动态数据预热（Redis 层）

活动页打开后要拉取的动态数据——活动配置、奖品库存、楼层结构、个性化文案——在活动开始前写入 Redis。

```
活动开始 T-10min
  → 运营在后台点击"活动预热"
  → 预热任务读取活动配置（楼层、奖品池、规则）
  → 批量写入 Redis（带随机抖动 TTL，覆盖活动周期）
  → 回填网关/本地缓存中的"活动开关、灰度名单"
  → 校验：模拟请求活动接口，确认全部命中缓存
```

**静态化兜底**：对完全不依赖用户的活动配置，可在预热时直接渲染成 JSON 快照存 Redis（甚至生成静态 JSON 文件推 CDN），活动接口直接吐快照，DB 零压力。

### 3.3 配置类静态数据预热（多级）

App 启动、首页加载强依赖的配置字典（剧集分类、地区语言映射、付费档位、客户端开关），适合贯穿多级预热：

| 数据 | 预热层级 | 触发时机 |
|------|---------|---------|
| 剧集分类 / 标签字典 | 本地缓存 + Redis | 服务启动时主动加载 + 配置变更时推送失效 |
| 地区/语言/币种映射 | 本地缓存 | 服务启动时全量加载 |
| 付费档位 / 商品配置 | Redis + 本地 | 变更后由配置中心推送，预热新值 |
| 客户端开关 / 灰度 | 网关本地缓存 | 发布前推送 |

```go
// 服务启动时主动预热本地缓存（配置字典）
func (s *Server) warmupOnBoot(ctx context.Context) error {
    // 1. 全量加载分类字典到进程内本地缓存
    cats, err := s.repo.LoadAllCategories(ctx)
    if err != nil {
        return fmt.Errorf("预热分类字典失败: %w", err)
    }
    s.localCache.SetCategories(cats)

    // 2. 加载地区/语言映射（海外多市场）
    regions, _ := s.repo.LoadRegionConfig(ctx)
    s.localCache.SetRegions(regions)

    // 3. 订阅配置中心，后续变更增量更新（避免再次全量回源）
    s.configCenter.Subscribe("category.*", s.onCategoryChanged)
    return nil
}
```

> **就绪探针联动**：预热未完成前，服务的 readiness probe 应返回未就绪，避免 K8s 把流量打到"缓存还是空"的新实例上（典型的滚动发布冷启动问题）。

---

## 四、剧集数据预热：热门剧 / 投放剧 / 新剧

剧集数据预热是短剧平台预热的核心，分三种触发场景，策略各有侧重。

### 4.1 数据结构：一部剧涉及的缓存 Key 体系

预热前要先梳理一部剧涉及的所有缓存 key，防止遗漏：

```
剧集详情          drama:detail:{dramaID}          → 剧名、简介、封面、评分、标签
集数列表          drama:episodes:{dramaID}         → [{episodeID, title, duration, coverURL}]
单集详情          episode:detail:{episodeID}       → 分辨率列表、时长、播放凭证参数
播放凭证          play:token:{episodeID}:{uid}     → VOD 加密播放凭证（短 TTL，用户级）
剧封面图          CDN 预热 URL 列表
剧相关推荐        drama:recommend:{dramaID}        → 相似剧集 ID 列表
投放剧标记        ad:target:drama:{dramaID}        → 是否当前投放中、对应广告计划
```

> **播放凭证（play token）是用户级的**，不能全量预热，见第五节 VOD 集成部分。

### 4.2 热门剧预热（定时 + 流量驱动）

**来源**：按播放量/完播率排序的 Top-N 剧集，通常由推荐系统或数据平台每小时产出一个榜单。

**预热频率**：榜单每小时更新 → 新晋榜单剧触发一次预热，跌出榜单的剧让 TTL 自然过期。

```
每小时 热门榜单任务
   │
   ├── 从 Hologres / Redis Sorted Set 取 Top 100 dramaID
   ├── diff 上一小时榜单，找出新增的 dramaID（只预热增量）
   │
   ├── [本地缓存层] 前 20 名 dramaID + 基础信息推送到各服务实例
   │              （发布到消息总线，由服务订阅者异步更新本地缓存）
   │
   ├── [Redis 层] 批量写入 drama:detail / drama:episodes
   │             TTL = 1h + rand(0, 10min)（避免同批过期）
   │
   └── [CDN 层] 封面图 / 第 1 集 m3u8 PushObjectCache
```

**本地缓存的"前 20 名"选择策略**：

- 本地缓存容量有限，只放最热的 Top-20，其余命中 Redis
- 各服务实例的本地缓存保持最终一致：写入 Redis 后发一条 `cache.invalidate.drama:{id}` 消息，各实例监听并刷新本地缓存

### 4.3 目标投放剧预热（事件驱动、最高优先级）

**来源**：运营/投放系统配置"某剧集从 T 时刻开始放量，预计 X 万次点击/天"。这是**流量最集中、最可预期**的场景，预热优先级最高。

**预热触发时机**：投放计划审批通过，且距离放量时间 ≤ 30 分钟时，触发预热。

```
投放计划审批通过
   │
   ├─ 写入投放配置 DB
   ├─ 发送事件: AdCampaignApproved { dramaID, startAt, estimatedQPS }
   │
   └─ PrewarmConsumer 消费事件
         ├── 计算预热窗口：startAt - 15min 执行预热
         ├── 投放剧专属预热内容（比热门剧更完整）：
         │     drama:detail + drama:episodes（所有集）
         │     episode:detail（每集分辨率信息）
         │     ad:target:drama:{id} 写入投放标记
         │     CDN 推送：封面图 + 前 3 集 m3u8 + 前 3 集首个 ts 分片
         └── 写入监控：预热完成时间、命中率预期
```

**投放剧的 CDN 预热粒度**：

- 封面图、剧集列表页图片 → 全量推送（体积小，用户到达前就会看到）
- 视频内容 → 只推前 3 集的 m3u8 manifest + 每集前 5 个 ts 分片
  - 原因：用户被广告吸引后，90% 流失在前 3 集；推太多反而浪费 CDN 推送配额
- 按用户目标地域选择 CDN 节点：东南亚投放只预热 `Area=ap-southeast`

### 4.4 新剧上线预热（定时 + 运营排期）

**来源**：运营在内容管理后台排期，新剧上线时间确定后，由预热调度器在上线前执行。

**预热时间线**：

```
T-30min: 预热 Redis（剧集详情、集数列表、分类归属）
T-15min: 预热本地缓存（首页新剧推荐位）
T-10min: CDN 推送封面图、H5 分享图
T-5min:  CDN 推送第 1 集 m3u8 + 前 5 个 ts 分片
T-0:     上线，首批用户全部命中缓存
T+1h:    根据实际播放数据，判断是否追加后续集的 CDN 预热
```

**上线前校验（预热验收）**：

```go
// 新剧上线前：自动化预热验收
func (v *WarmupValidator) ValidateDrama(ctx context.Context, dramaID int64) (*ValidationResult, error) {
    checks := []check{
        {name: "Redis drama:detail",  fn: func() bool { return v.redis.Exists(dramaKey(dramaID)) }},
        {name: "Redis episodes list", fn: func() bool { return v.redis.Exists(episodesKey(dramaID)) }},
        {name: "CDN cover image",     fn: func() bool { return v.cdnHit(coverURL(dramaID)) }},
        {name: "CDN ep1 m3u8",        fn: func() bool { return v.cdnHit(ep1M3u8URL(dramaID)) }},
    }
    var failures []string
    for _, c := range checks {
        if !c.fn() { failures = append(failures, c.name) }
    }
    if len(failures) > 0 {
        // 发告警：预热未完成，上线时间需延后或降级处理
        v.alert.Warn("新剧预热验收失败", dramaID, failures)
    }
    return &ValidationResult{Passed: len(failures) == 0, Failures: failures}, nil
}
```

---

## 五、与阿里云视频点播（VOD）的组合预热

阿里云 VOD 不只是转码工具，它自带 CDN 加速域名、OSS 源站、DRM 加密和防盗链体系。理解 VOD 的分发链路，才能在正确的位置做正确的预热动作。

### 5.1 VOD 的完整分发链路

短剧视频从上传到用户播放的全链路：

```
[上传/制作]
  运营上传视频源文件 → 阿里云 VOD 存储（OSS）
          │
          ▼
[转码/处理]
  VOD 工作流：转码 → 多码率 HLS 切片（240p/480p/720p/1080p）
              每个码率 = 1 个 m3u8 + N 个 ts 分片（每分片约 5~10s）
              可选：DRM 加密 / 水印 / 字幕烧录
              → 输出 videoId（VOD 的资产 ID）
          │
          ▼
[元数据存储]
  平台 DB：episode 表保存 videoId，不直接保存播放 URL
           （URL 通过 VOD API 动态换取，带时效性）
          │
          ▼
[播放鉴权]
  用户请求播放 → 服务端调用 VOD GetPlayInfo 或 GetVideoPlayAuth
               → 返回：带签名的播放 URL / 防盗链 token
               → 客户端用此 URL 向 VOD CDN 拉流
          │
          ▼
[CDN 分发]
  VOD 加速域名（如 vod-{region}.example.com）→ 阿里云 VOD CDN 边缘节点
  边缘有缓存 → 直接返回 ts 分片                    ↑
  边缘无缓存 → 回源到 OSS（ts 分片体积大，回源慢）  │
                                                  CDN 预热
```

### 5.2 VOD + CDN 预热的两个入口

预热有两个 API，针对不同场景：

| API | 作用 | 适用场景 |
|-----|------|---------|
| `PushObjectCache` | 把指定 URL 的资源主动推到 CDN 边缘节点 | **视频分片预热**（新剧上线、投放前推前几集） |
| `RefreshObjectCaches` | 标记 CDN 上的旧资源失效，强制下次请求回源 | **版本更新**（转码重新出了更好质量的分片） |

**VOD 场景下的 PushObjectCache**：

```go
// 推送某集视频的 m3u8 + 前 N 个 ts 分片到 CDN
func (w *VODWarmer) PushEpisodeToCDN(ctx context.Context, episodeID int64, prefetchTsCount int) error {
    // 1. 查 episode 表，取 videoId
    ep, err := w.episodeRepo.Get(ctx, episodeID)
    if err != nil {
        return err
    }

    // 2. 调 VOD API 取实际 CDN URL（注意：这里用无鉴权的公共 m3u8 地址，
    //    或者用内部服务账号的签名 URL，不要用最终用户播放凭证）
    playInfo, err := w.vodClient.GetPlayInfo(ep.VideoId, "m3u8")
    if err != nil {
        return err
    }

    urls := []string{playInfo.M3u8URL} // 主 m3u8

    // 3. 解析 m3u8，取前 N 个 ts 分片 URL
    tsURLs, err := parseM3u8(playInfo.M3u8URL, prefetchTsCount)
    if err == nil {
        urls = append(urls, tsURLs...)
    }

    // 4. 调阿里云 CDN PushObjectCache
    return w.cdnClient.PushObjectCache(ctx, &cdn.PushObjectCacheRequest{
        ObjectPath: strings.Join(urls, "\n"),
        Area:       "overseas",
    })
}
```

### 5.3 VOD 鉴权方式详解：PlayAuth vs URL 鉴权

阿里云 VOD 提供两种鉴权体系，面向不同场景，缓存策略截然不同：

| 鉴权方式 | 核心机制 | 适用场景 | 是否可预热 |
|---------|---------|---------|-----------|
| **播放凭证（PlayAuth）** | 服务端调用 VOD API 生成短时 token，Aliplayer SDK 用 token 内部换取流地址 | 需要精确控制每个用户的播放权限（付费剧、会员内容） | ❌ token 用户级 + 100s 过期，不可预热 |
| **URL 鉴权（URL Signing）** | CDN URL 本身携带签名参数和过期时间戳，CDN 边缘节点验证签名 | 内容有一定防盗链需求，但不需要用户级精细控制（免费剧、预告片） | ✅ 可预热，但需处理过期问题（见下） |

---

#### 5.3.1 PlayAuth 鉴权方式

```
流程：用户请求播放
  → 服务端调 GetVideoPlayAuth(videoId) → 返回 playAuth token（有效期 100s）
  → 客户端 Aliplayer SDK 初始化：player.init({ playAuth: token })
  → Aliplayer 内部用 token 向 VOD 换取实际带签名的流地址
  → 拉取 m3u8 / ts 分片播放
```

特征：
- token **绑定调用方的 AccessKey**，有效期 100s（可配置，最大 3600s）
- **用户级**：不同用户的 token 不能共享，也不反映在 URL 里
- Aliplayer SDK 负责鉴权细节，业务层只管下发 token

**缓存策略**：PlayAuth 本身不可全量预热，但可做两级拆分：

```
阶段一（可预热，集级别）：
  episode:play_meta:{episodeID} = {
    videoId,        ← VOD 资产 ID，静态
    qualityList,    ← 分辨率列表，静态
    subtitles,      ← 字幕轨道，静态
    drmKeyId        ← DRM 密钥，静态
  }
  TTL: 24h（转码信息变化时主动失效）

阶段二（不预热，用户 × 集 维度）：
  用户进入播放页 → 服务端即时调 GetVideoPlayAuth
  → 返回 token（Redis 按 user×episode 缓存 80s，防同用户重复调 VOD API）
```

```go
// 用户维度短时复用，避免重复调 VOD API（降费用）
func (s *PlayService) GetPlayAuth(ctx context.Context, userID, episodeID int64) (string, error) {
    key := fmt.Sprintf("play:auth:%d:%d", userID, episodeID)
    if auth, _ := s.redis.Get(ctx, key); auth != "" {
        return auth, nil
    }
    videoID, _ := s.getVideoID(ctx, episodeID)
    auth, err := s.vodClient.GetVideoPlayAuth(videoID)
    if err != nil {
        return "", err
    }
    // 有效期 100s，缓存 80s：留 20s 余量防止 token 在传输途中过期
    s.redis.SetEX(ctx, key, auth, 80*time.Second)
    return auth, nil
}
```

---

#### 5.3.2 URL 鉴权方式（Type A / B / C）

URL 鉴权不需要 Aliplayer SDK 参与，鉴权逻辑由 CDN 边缘节点完成。阿里云 VOD 支持三种签名格式：

**Type A（最常用）**：

```
http://{Domain}/{FilePath}?auth_key={timestamp}-{rand}-{uid}-{md5}

参数说明：
  timestamp  Unix 时间戳（10位），= URL 失效时刻（非生成时刻）
  rand       随机无符号整数
  uid        用户标识，一般填 0
  md5        MD5("{FilePath}-{timestamp}-{rand}-{uid}-{PrivateKey}")

示例：
  http://vod.example.com/drama/ep1_hd.m3u8?auth_key=1751300000-1234-0-a3f2c1d9e8b7...
                                                       ↑ 这个时间戳到期后 CDN 返回 403
```

**Type B**（时间戳在路径中）：

```
http://{Domain}/{YYYYMMDDHHMMSS}/{md5}/{FilePath}
示例：
  http://vod.example.com/20260629183000/a3f2c1d9.../drama/ep1_hd.m3u8
```

**Type C**（md5 + 时间戳十六进制在路径中）：

```
http://{Domain}/{md5}/{hex_timestamp}/{FilePath}
示例：
  http://vod.example.com/a3f2c1d9.../68610780/drama/ep1_hd.m3u8
                                    ↑ 0x68610780 = Unix timestamp 的 16 进制
```

三种类型鉴权强度相近，区别主要是 URL 格式；推荐短剧场景使用 **Type A**，参数在 query string 中，便于 CDN 忽略签名参数做缓存（见下）。

---

#### 5.3.3 URL 鉴权下的过期问题与缓存/预热策略

这是 URL 鉴权模式最容易踩坑的地方。

**问题根源**：签名 URL 含过期时间戳 → URL 每次生成都不同 → CDN 默认把不同 URL 当作不同缓存 key → 预热一个 URL，用户用另一个 URL 访问 → CDN miss，预热白做。

```
预热时生成：.../ep1.m3u8?auth_key=1751300000-xxx-0-AAA   ← 预热写入边缘节点
用户访问时：.../ep1.m3u8?auth_key=1751300010-yyy-0-BBB   ← 不同签名 = 不同 URL = miss
```

**解决方案：CDN 配置"忽略鉴权参数做缓存 Key"**

在阿里云 CDN 控制台 → 缓存配置 → 过滤参数（忽略 URL 参数），将 `auth_key` 加入忽略列表：

```
CDN 缓存 Key = URL 去掉 auth_key 后的部分
即 http://vod.example.com/drama/ep1_hd.m3u8

效果：
  - 边缘节点仍然会验证 auth_key 签名（鉴权不受影响）
  - 验证通过后，以文件路径作为缓存 key，命中预热内容
  - 不同用户不同签名，只要路径相同，都命中同一份缓存
```

**签名 URL 的过期时间设置原则**：

```
生成签名 URL 时 timestamp 的选取：

场景                      推荐 timestamp（从现在起的有效期）
──────────────────────────────────────────────────────────
CDN 预热用（prewarm）    now + 24h（足够覆盖当天流量）
下发给客户端播放         now + 1h ~ 4h（足够一次播放会话）
Redis 中缓存的播放 URL   timestamp - now - 5min 作为 Redis TTL
                         （Redis 过期时间 < URL 过期时间）
```

**Redis 缓存签名 URL 的刷新策略**（主动续期，避免用到过期 URL）：

```go
type SignedURLCache struct {
    redis  RedisClient
    signer *VODURLSigner
}

func (c *SignedURLCache) GetPlayURL(ctx context.Context, episodeID int64, quality string) (string, error) {
    key := fmt.Sprintf("play:url:%d:%s", episodeID, quality)

    type cachedURL struct {
        URL       string    `json:"url"`
        ExpiresAt time.Time `json:"expires_at"` // URL 本身的过期时刻
    }

    raw, _ := c.redis.Get(ctx, key)
    if raw != "" {
        var cu cachedURL
        json.Unmarshal([]byte(raw), &cu)
        // 距 URL 过期还有 5 分钟以上：直接返回
        if time.Until(cu.ExpiresAt) > 5*time.Minute {
            return cu.URL, nil
        }
        // 不足 5 分钟：异步续期，本次仍先返回旧 URL（还没过期，可用）
        go c.refresh(context.Background(), episodeID, quality)
        return cu.URL, nil
    }
    // 缓存不存在：同步生成
    return c.refresh(ctx, episodeID, quality)
}

func (c *SignedURLCache) refresh(ctx context.Context, episodeID int64, quality string) (string, error) {
    key := fmt.Sprintf("play:url:%d:%s", episodeID, quality)
    urlExpiry := time.Now().Add(2 * time.Hour)           // URL 有效 2h
    signedURL := c.signer.Sign(episodeID, quality, urlExpiry)

    val, _ := json.Marshal(map[string]any{
        "url":        signedURL,
        "expires_at": urlExpiry,
    })
    // Redis TTL = URL 有效期 - 5min 安全余量
    c.redis.SetEX(ctx, key, string(val), 115*time.Minute)
    return signedURL, nil
}
```

**CDN 预热（PushObjectCache）用长时效 URL**：

```go
// 预热时生成过期时间足够长的签名 URL（不下发给用户，只用于预热）
func (w *VODWarmer) PushWithURLSigning(ctx context.Context, filePath string) error {
    // 预热专用：24h 有效期，覆盖整个预热生效窗口
    warmURL := w.signer.Sign(filePath, time.Now().Add(24*time.Hour))
    return w.cdnClient.PushObjectCache(ctx, &cdn.PushObjectCacheRequest{
        ObjectPath: warmURL,
    })
    // CDN 验证签名通过后，以 filePath（去掉 auth_key）为 key 缓存内容
    // 后续用户请求携带自己的签名，CDN 验签通过 → 命中预热缓存
}
```

---

#### 5.3.4 两种鉴权方式的选型建议（短剧场景）

| 内容类型 | 推荐鉴权方式 | 理由 |
|---------|------------|------|
| 付费剧、会员专属剧 | **PlayAuth** | 需要精确控制每个用户的权限，token 由服务端管控 |
| 免费剧、试看集、预告片 | **URL 鉴权 Type A** | 防盗链即可，无需用户级控制，可配合 CDN 预热 |
| 投放剧的目标集（前 N 集免费） | URL 鉴权（前 N 集）+ PlayAuth（付费集） | 混用，按集数切换鉴权方式 |
| H5 活动页视频（宣传片） | URL 鉴权或无鉴权 | 公开传播内容，宽松处理 |

> **关键结论**：URL 鉴权模式下，CDN 预热才能真正生效（配合 CDN 忽略 auth_key 参数）。PlayAuth 模式无法在 CDN 层预热视频内容，只能靠 Redis 预热元数据 + 用户访问时 CDN 懒加载。选型时优先按"是否需要用户级权限控制"来决定，而非性能。

### 5.4 转码完成后的自动预热（VOD 回调 + 预热联动）

VOD 转码完成后，会通过**消息服务（MNS）或 HTTP 回调**通知业务方。这是触发预热的最佳时机：

```
VOD 转码完成
   → 回调事件: { videoId, status: "success", formats: ["m3u8_hd","m3u8_sd",...] }
   │
   └─ VideoTranscodeCallback 处理器
         ├── 1. 写入 episode.videoId 到 DB（如果是新集）
         ├── 2. 更新 episode:play_meta 缓存（播放元信息）
         ├── 3. 查询此视频关联的剧集是否在投放计划或新剧列表中
         │     ├── 是投放剧 → 立即触发 CDN 预热（PushObjectCache）
         │     ├── 是新剧   → 写入"待预热队列"，按上线时间窗口调度
         │     └── 普通剧   → 只预热 Redis，CDN 按需懒加载
         └── 4. 清除封面图 CDN 缓存（如果封面同步更新）
```

**关键配置：VOD 消息回调**

```json
// 阿里云 VOD 控制台 → 回调设置
{
  "CallbackType": "HTTP",
  "CallbackURL": "https://internal.example.com/vod/callback",
  "EventTypeList": ["FileUploadComplete", "StreamTranscodeComplete", "TranscodeComplete"]
}
```

### 5.5 VOD CDN 域名与预热配额管理

阿里云 CDN `PushObjectCache` 有每日配额（默认 500 条 URL/天，可申请扩容），海外短剧集数多，需要精打细算：

| 内容类型 | 预热策略 | 配额占用估算 |
|---------|---------|------------|
| 剧封面图 | 每部剧 1 张，新剧/投放剧必推 | Top 100 剧 × 1 = 100 URL |
| 集数列表缩略图 | 按需，热门剧前 10 集 | Top 50 剧 × 10 = 500 URL |
| 视频 m3u8 manifest | 每个码率 1 个，推 720p + 1080p | 投放剧 × 3 集 × 2 = N URL |
| ts 分片 | 每集前 5 片，6min 以下短剧 | 最消耗配额，优先级最低 |

**节省配额的技巧**：
- m3u8 预热 > ts 分片预热：m3u8 命中后 Aliplayer 会自动拉取 ts（ts 回源可以接受，m3u8 回源才是首屏延迟元凶）
- 使用**预热优先级队列**：投放剧 > 新剧 > 热门 Top20 > 热门 Top100，按优先级消耗配额
- 超配额时只推 m3u8，不推 ts

---

## 六、预热调度系统设计

预热不是一次性脚本，而是一个需要**调度、限流、重试、优先级**的后台系统。

### 6.1 预热任务分类与触发源

```
触发源                        预热任务类型              目标层级
─────────────────────────────────────────────────────────────
投放计划审批通过     →    AdTargetWarmup（最高优先）   Redis + CDN
新剧上线排期        →    NewDramaWarmup（高优先）      Redis + 本地 + CDN
每小时热门榜单更新   →    HotRankWarmup（常规）         Redis + 本地
服务实例启动        →    BootWarmup（自动）            本地缓存
H5 活动发布        →    ActivityWarmup（事件驱动）    CDN + Redis
VOD 转码完成        →    MediaReadyWarmup（事件驱动）  Redis + CDN（条件）
```

### 6.2 预热调度器核心实现

```go
type WarmupScheduler struct {
    queue    chan *WarmupTask          // 优先级队列（可换 heap 实现）
    limiter  *rate.Limiter            // 全局限流：防止预热成为自我 DDoS
    cdnQuota *QuotaManager            // CDN PushObjectCache 每日配额
    workers  int
}

// 优先级：投放剧(3) > 新剧(2) > 热门榜单(1) > 其他(0)
type WarmupTask struct {
    Type     string
    DramaID  int64
    Priority int
    Layers   []WarmupLayer   // 需要预热的层：Local / Redis / CDN
    Meta     map[string]any
}

func (s *WarmupScheduler) Run(ctx context.Context) {
    for i := 0; i < s.workers; i++ {
        go func() {
            for task := range s.queue {
                s.limiter.Wait(ctx)      // 全局限速
                s.execute(ctx, task)
            }
        }()
    }
}

func (s *WarmupScheduler) execute(ctx context.Context, t *WarmupTask) {
    for _, layer := range t.Layers {
        switch layer {
        case LayerLocal:
            s.warmLocal(ctx, t)
        case LayerRedis:
            s.warmRedis(ctx, t)
        case LayerCDN:
            if s.cdnQuota.Consume(1) {  // 扣减配额，超配额降级跳过
                s.warmCDN(ctx, t)
            }
        }
    }
}
```

### 6.3 分批预热防止打垮后端

多部剧同时预热时，需要分批执行，避免 DB 和 VOD API 被预热请求本身打满：

```go
// 批量预热时的分批 + 并发控制
func (s *WarmupScheduler) WarmBatch(ctx context.Context, dramaIDs []int64, concurrency int) {
    sem := make(chan struct{}, concurrency) // 信号量限制并发数
    var wg sync.WaitGroup
    for _, id := range dramaIDs {
        wg.Add(1)
        sem <- struct{}{}
        go func(dramaID int64) {
            defer func() { <-sem; wg.Done() }()
            s.warmRedis(ctx, &WarmupTask{DramaID: dramaID})
        }(id)
    }
    wg.Wait()
}
```

并发数推荐值（参考起点，按实际 QPS 上限调整）：

| 场景 | Redis 写并发 | CDN 推送并发 | VOD API 并发 |
|------|------------|------------|------------|
| 投放剧（1~3 部） | 5 | 2 | 2 |
| 新剧批量（10~20 部） | 10 | 3 | 3 |
| 热门榜单（100 部） | 20 | 5 | 5 |

### 6.4 预热任务的幂等与去重

同一剧集可能被多个触发源重复触发预热（如同时出现在新剧列表和投放计划里），必须做去重：

```go
// 预热去重：同一 dramaID + layer，N 分钟内只执行一次
func (s *WarmupScheduler) Enqueue(task *WarmupTask) {
    dedupeKey := fmt.Sprintf("warmup:dedup:%d:%s", task.DramaID, task.Type)
    ok, _ := s.redis.SetNX(ctx, dedupeKey, 1, 5*time.Minute)
    if !ok {
        return  // 5 分钟内已预热过，跳过
    }
    s.queue <- task
}
```

---

## 七、预热全链路监控与验收

### 7.1 核心监控指标

| 指标 | 采集点 | 告警阈值 |
|------|--------|---------|
| Redis 预热覆盖率 | 预热完成后 sampling check | < 95% 告警 |
| CDN 边缘命中率 | 阿里云 CDN 控制台 / API | < 80% 告警（海外） |
| 预热任务队列积压 | 调度器 queue length | > 100 告警 |
| CDN 配额消耗率 | QuotaManager 计数 | > 80% 告警（避免超配） |
| 预热执行耗时 | P99 | 新剧 > 10min 告警（留不到 5min 窗口） |
| 投放剧首帧耗时 | 客户端埋点 | > 3s 告警（反映 CDN 未命中） |

### 7.2 上线前预热验收流程

```
新剧 / 投放剧 预热完成后，自动触发验收：

验收项 1：Redis key 存在性检查
  EXIST drama:detail:{id}       → 必须存在
  EXIST drama:episodes:{id}     → 必须存在
  EXIST episode:play_meta:{ep1} → 必须存在（至少第 1 集）

验收项 2：CDN 命中检查（Probe Request）
  HEAD https://cdn.example.com/{cover_image}   → X-Cache: HIT
  HEAD https://vod.example.com/{ep1.m3u8}      → X-Cache: HIT

验收项 3：接口响应时间
  GET /api/drama/{id}   → P99 < 50ms（应全部命中缓存）
  GET /api/play/{ep1}   → P99 < 100ms

验收结果：
  全部通过 → 允许上线 / 放量
  部分失败 → 告警运营，延后上线或降级预案启动
```

### 7.3 预热未生效的降级策略

预热是加速手段，不是必要条件，系统必须能在预热失败时优雅降级：

```
降级策略（优先级由高到低）
  1. singleflight：多并发 miss → 合并为一个 DB 查询，防止缓存击穿
  2. 熔断：DB/VOD API 响应超时 → 熔断器打开，返回兜底数据（服务降级）
  3. 空值缓存：查 DB 确实不存在的 key → 写短 TTL 空值，防穿透
  4. 限流：上游流量超过 QPS 上限 → 返回 429，前端提示稍后重试
  5. 兜底页：视频播放失败 → 前端展示「视频加载中，请稍候」而非白屏
```

---

## 八、完整架构图

```
                    ┌──────────────────────────────────────────────────────┐
                    │                  预热触发源                           │
                    │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐  │
                    │  │ 投放系统 │ │ 内容排期 │ │ 热门榜单 │ │VOD回调 │  │
                    │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘  │
                    └───────┼────────────┼────────────┼───────────┼────────┘
                            │            │            │           │
                            ▼            ▼            ▼           ▼
                    ┌──────────────────────────────────────────────────────┐
                    │           WarmupScheduler（预热调度器）               │
                    │   优先级队列 | 限流(rate.Limiter) | 并发控制          │
                    │   去重(Redis SetNX) | 配额管理(CDN quota)            │
                    └────────────────────┬─────────────────────────────────┘
                                         │
              ┌──────────────────────────┼──────────────────────────┐
              │                          │                          │
              ▼                          ▼                          ▼
  ┌───────────────────┐      ┌───────────────────┐      ┌─────────────────────┐
  │  本地缓存预热       │      │   Redis 预热        │      │   CDN 预热           │
  │  (进程内 Top-N)    │      │  drama:detail      │      │  PushObjectCache    │
  │  通过消息总线广播   │      │  drama:episodes    │      │  m3u8 manifest      │
  │  到各服务实例      │      │  episode:play_meta │      │  首 N 个 ts 分片     │
  │                   │      │  活动/配置数据      │      │  封面图/活动图片      │
  └───────────────────┘      └───────────────────┘      └──────────┬──────────┘
                                                                    │
                                                         ┌──────────▼──────────┐
                                                         │   阿里云 VOD / CDN   │
                                                         │  ┌─────────────────┐│
                                                         │  │ 转码: 多码率 HLS ││
                                                         │  │ 存储: OSS 源站   ││
                                                         │  │ 分发: CDN 加速   ││
                                                         │  │ 鉴权: playAuth  ││
                                                         │  └─────────────────┘│
                                                         │  VOD CDN 边缘节点    │
                                                         │  (全球覆盖，海外节点) │
                                                         └─────────────────────┘

  用户访问链路（预热生效后）：
  App/H5 → CDN 边缘（HIT）→ 直接返回视频分片 / 静态资源
         → 服务接口 → 本地缓存（HIT）→ 直接返回剧集数据
                    → Redis（HIT）→ 直接返回
                    → DB（极少回源，兜底）
```

---

## 九、各场景预热策略速查

| 场景 | 触发方式 | 预热层级 | CDN 推送内容 | Redis TTL | 优先级 |
|------|---------|---------|------------|-----------|--------|
| 新剧上线 | 运营排期定时 | 本地 + Redis + CDN | 封面 + 第1集 m3u8 + 前5 ts | 24h + jitter | 高 |
| 投放剧放量 | 投放审批事件 | Redis + CDN（全） | 前3集 m3u8 + 前3集各5 ts | 6h + jitter | **最高** |
| 热门榜单更新 | 每小时定时 | 本地(Top20) + Redis | 封面图 | 1h + jitter | 常规 |
| H5 活动页发布 | CI/CD 流水线 | Redis + CDN | 全量静态资源 | 活动周期 | 高 |
| 服务实例启动 | 服务 Boot | 本地缓存（全量配置） | — | — | 自动 |
| VOD 转码完成 | VOD 回调 | Redis（play_meta） | 条件推送（投放/新剧） | 24h | 事件 |
| 配置变更 | 配置中心推送 | 本地 + Redis | — | 配置周期 | 实时 |

---

> **延伸阅读**：
> - [阿里云 VOD 开发文档 — 播放器集成](https://help.aliyun.com/zh/vod/developer-reference/overview-1)
> - [阿里云 CDN PushObjectCache API](https://help.aliyun.com/zh/cdn/developer-reference/api-cdn-2018-05-10-pushobjectcache)
> - [Redis 逻辑过期 + singleflight 防击穿实践](./backend-interview/04-redis-advanced.md)

