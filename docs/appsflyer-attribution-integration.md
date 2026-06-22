# AppsFlyer 海外广告归因对接流程说明

> **版本**: v1.0  
> **适用范围**: 移动端 App 海外广告归因对接（iOS / Android）  
> **核心 SDK**: AppsFlyer SDK (Native / Unity / React Native / Flutter)  
> **后端接入**: AppsFlyer S2S API + Pull API + Push API (Webhook)

---

## 目录

1. [概述](#1-概述)
2. [核心概念](#2-核心概念)
3. [客户端负责部分](#3-客户端负责部分)
4. [后端负责部分](#4-后端负责部分)
5. [完整业务流转链路](#5-完整业务流转链路)
6. [状态流转链路](#6-状态流转链路)
7. [数据模型设计](#7-数据模型设计)
8. [异常场景与兜底策略](#8-异常场景与兜底策略)
9. [测试与验收清单](#9-测试与验收清单)

---

## 1. 概述

### 1.1 什么是 AppsFlyer

AppsFlyer 是全球领先的移动广告归因与营销分析平台（MMP, Mobile Measurement Partner），核心能力：

| 能力 | 说明 |
|------|------|
| **广告归因** | 准确判断用户的安装/付费行为来自哪个广告渠道、哪条广告素材 |
| **深度链接** | 支持 Deferred Deep Linking（未安装跳商店 → 安装后还原落地页） |
| **防作弊** | 基于设备指纹、点击时间、IP 等多维信号识别假量 |
| **LTV/ROAS** | 用户生命周期价值与广告支出回报分析 |
| **全漏斗分析** | 从曝光 → 点击 → 安装 → 付费 → 留存的全链路追踪 |

### 1.2 对接目标

将 App 内的用户关键行为（安装、注册、付费等）通过 AppsFlyer SDK / S2S API 上报，实现：

- **精准归因**：每个用户的来源渠道 / Campaign / AdSet / Ad 可追溯
- **实时回传**：后端接收 AppsFlyer 实时回传（Webhook / Push API），将归因结果写入业务库
- **数据闭环**：结合 BI 看板，运营可查看「渠道 → 安装 → 留存 → LTV」全漏斗

### 1.3 角色与职责总览

```
┌──────────────────────────────────────────────────────────────┐
│                         对接角色                              │
├────────────┬─────────────────┬───────────────────────────────┤
│   角色     │      负责方     │          核心职责              │
├────────────┼─────────────────┼───────────────────────────────┤
│ SDK 集成   │   客户端        │ SDK 初始化、事件上报、           │
│            │                 │ 归因数据获取                    │
├────────────┼─────────────────┼───────────────────────────────┤
│ S2S 对接   │   后端          │ S2S 事件回传、归因结果接收、     │
│            │                 │ 数据校验与落库                  │
├────────────┼─────────────────┼───────────────────────────────┤
│ 数据消费   │   后端 + 数据    │ 归因数据清洗、ETL、BI 看板      │
│            │                 │ 广告投放决策                    │
├────────────┼─────────────────┼───────────────────────────────┤
│ 渠道配置   │   运营 + 后端   │ AppsFlyer 后台渠道配置、       │
│            │                 │ Tracking Link 生成              │
└────────────┴─────────────────┴───────────────────────────────┘
```

---

## 2. 核心概念

### 2.1 归因方式

| 归因方式 | 说明 | 适用场景 |
|----------|------|----------|
| **确定性归因 (Deterministic)** | 通过唯一标识（GAID/IDFA/IDFV）精确匹配 | 设备 ID 可获取时 |
| **概率归因 (Probabilistic)** | 使用 IP + UserAgent + 时间窗口等模糊匹配 | iOS ATT 拒绝后 / 无设备 ID 时 |
| **自归因渠道 (SAN)** | 渠道自行完成归因，AppsFlyer 通过 API 拉取归因结果，不使用 MMP 归因逻辑 | Meta / Google / Apple Search Ads / TikTok 等 |
| **非自归因渠道 (Non-SAN)** | AppsFlyer 直接完成归因判定 | 大多数 DSP / Ad Network |

### 2.2 关键标识

```
┌────────────────┬──────────────────────────────────────────────┐
│     标识       │                   说明                        │
├────────────────┼──────────────────────────────────────────────┤
│ GAID           │ Google Advertising ID（Android）              │
│ IDFA           │ Identifier for Advertisers（iOS，需 ATT 授权） │
│ IDFV           │ Identifier for Vendor（iOS，同厂商内唯一）     │
│ OAID           │ 国内安卓设备标识                              │
│ AppsFlyer ID   │ AF 生成的唯一用户 ID（每个设备+App 唯一）       │
│ Customer User ID│ 业务方用户 ID（登录后设置，用于跨设备/跨平台关联）│
│ af_dp          │ AppsFlyer 深度链接参数                        │
│ af_media_source│ 归因媒体源（如 facebook、google）             │
│ af_campaign    │ 归因广告系列名称                              │
│ af_channel     │ 归因渠道                                      │
│ af_adset       │ 归因广告组                                    │
│ af_ad          │ 归因具体广告                                   │
└────────────────┴──────────────────────────────────────────────┘
```

### 2.3 归因窗口

| 窗口类型 | 默认值 | 说明 |
|----------|--------|------|
| **点击归因窗口** | 7 天 | 点击广告后 7 天内安装，归因给该点击 |
| **展示归因窗口** | 1 天 | 看完广告后 1 天内安装，归因给该展示 |
| **再归因窗口** | 90 天 | 沉默用户再次激活的归因窗口 |
| **归因过期** | 30 天 | 安装事件上报超过 30 天未完成归因则放弃 |

---

## 3. 客户端负责部分

> 客户端是整个归因链条的**数据生产者**，负责 SDK 初始化、设备数据采集、事件上报、深度链接消费。

### 3.1 SDK 初始化

#### 3.1.1 Android 初始化

```java
// 在 Application.onCreate() 中初始化
AppsFlyerLib appsflyer = AppsFlyerLib.getInstance();

// 1. 设置 Dev Key（从 AppsFlyer 后台获取）
appsflyer.setDevKey("YOUR_DEV_KEY");

// 2. 设置 App ID
appsflyer.setAppId("YOUR_APP_ID");

// 3. 初始化 SDK
appsflyer.init(context, conversionListener);

// 4. 启动（在 Activity.onResume() 中调用）
appsflyer.start(context);
```

**关键配置项**：

| 配置 | 说明 | 示例值 |
|------|------|--------|
| Dev Key | AF 后台分配的应用密钥 | `aBcDe123...` |
| App ID | AF 后台的应用 ID | `1234567890` |
| 超时时间 | SDK 上报超时设定 | 默认 10s |
| 是否开启 ATT | iOS 14.5+ 必须 | 需弹窗授权 |
| SDK 版本 | 建议始终使用最新版 | ≥ 6.x |

#### 3.1.2 iOS 初始化

```swift
// AppDelegate.swift
import AppsFlyerLib

func application(_ application: UIApplication, 
                 didFinishLaunchingWithOptions launchOptions: ...) -> Bool {
    AppsFlyerLib.shared().appsFlyerDevKey = "YOUR_DEV_KEY"
    AppsFlyerLib.shared().appleAppID = "YOUR_APPLE_APP_ID"
    
    // 设置 OneLink 自定义域名
    AppsFlyerLib.shared().onelinkCustomDomains = ["yourbrand.onelink.me"]
    
    // ATT 授权（iOS 14.5+）
    if #available(iOS 14, *) {
        // 实际调用应在合适的时机触发 ATT 弹窗
        ATTrackingManager.requestTrackingAuthorization { status in
            // 处理授权结果
        }
    }
    
    return true
}

// 支持 SceneDelegate
func sceneDidBecomeActive(_ scene: UIScene) {
    AppsFlyerLib.shared().start()
}
```

#### 3.1.3 客户端职责清单

```
┌──────────────────────────────────────────────────────────────────┐
│                    客户端职责 Checklist                           │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ✅ 1.  SDK 初始化（冷启动 / 热启动）                              │
│  ✅ 2.  Dev Key / App ID 配置（区分 Debug / Release）              │
│  ✅ 3.  ATT 弹窗时机选择（iOS）- 在 start() 之前                   │
│  ✅ 4.  首次安装事件上报（自动，SDK 内置）                          │
│  ✅ 5.  业务事件上报（注册、付费、关键行为...）                      │
│  ✅ 6.  深度链接处理（OneLink / UDL）                               │
│  ✅ 7.  获取 AppsFlyer ID（本地 + 异步回调）                        │
│  ✅ 8.  获取归因数据（Conversion Data 回调）                        │
│  ✅ 9.  设置 Customer User ID（用户登录 / 登出时）                  │
│  ✅ 10. 广告收入上报（adRevenue）                                  │
│  ✅ 11. 推送通知 token 上报（用于再营销）                           │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 事件上报

#### 3.2.1 SDK 内置事件（自动采集）

| 事件 | 触发时机 | 是否需要手动调用 |
|------|----------|:---:|
| `install` | 首次启动 App | ❌ 自动 |
| `af_start` | 每次启动 | ❌ 自动 |
| `re-attribution` | 再归因发生 | ❌ 自动 |
| `uninstall` | 卸载（通过静默推送推断） | ❌ 自动 |

#### 3.2.2 自定义事件上报

```java
// Android
Map<String, Object> eventValues = new HashMap<>();
eventValues.put(AFInAppEventParameterName.REVENUE, 9.99);
eventValues.put(AFInAppEventParameterName.CURRENCY, "USD");
eventValues.put(AFInAppEventParameterName.CONTENT_ID, "item_123");

AppsFlyerLib.getInstance().logEvent(
    context,
    AFInAppEventType.PURCHASE,  // 事件名称
    eventValues                  // 事件参数
);
```

```swift
// iOS
AppsFlyerLib.shared().logEvent(
    AFEventPurchase,
    withValues: [
        AFEventParamRevenue: 9.99,
        AFEventParamCurrency: "USD",
        AFEventParamContentId: "item_123"
    ]
)
```

**必须上报的业务事件**：

| 事件名 | 含义 | 优先级 | 参数要求 |
|--------|------|:---:|----------|
| `af_purchase` | 付费 | 🔴 必报 | `af_revenue`, `af_currency`, `af_content_id` |
| `af_complete_registration` | 注册完成 | 🔴 必报 | `af_registration_method` |
| `af_login` | 登录 | 🟡 建议 | `af_login_method` |
| `af_level_achieved` | 达成关卡 | 🟡 建议 | `af_level` |
| `af_tutorial_completion` | 新手引导完成 | 🟡 建议 | `af_success` (true/false) |
| `custom_event_xxx` | 自定义关键行为 | 🟢 可选 | 按业务定义 |

#### 3.2.3 Revenue 事件完整数据

```json
{
  "eventName": "af_purchase",
  "eventValue": {
    "af_revenue": 29.99,
    "af_currency": "USD",
    "af_content_id": "subscription_monthly",
    "af_content_type": "subscription",
    "af_order_id": "ORDER-123456",
    "af_receipt": "base64_encoded_receipt",
    "af_quantity": 1,
    "af_payment_info_available": "yes",
    "af_extra_param_1": "custom_value"
  },
  "eventTime": "2026-06-20T10:30:00Z"
}
```

### 3.3 归因数据获取

#### 3.3.1 获取 Conversion Data（首次安装）

```java
// Android
appsFlyerLib.init(
    devKey,
    new AppsFlyerConversionListener() {
        @Override
        public void onConversionDataSuccess(Map<String, Object> conversionData) {
            // 归因成功回调 - 包含渠道信息
            String mediaSource = (String) conversionData.get("media_source");
            String campaign = (String) conversionData.get("campaign");
            String adset = (String) conversionData.get("adset");
            String ad = (String) conversionData.get("ad");
            String afStatus = (String) conversionData.get("af_status");
            
            // 此时应保存到本地 + 传递给后端
            saveAttributionData(conversionData);
        }
        
        @Override
        public void onConversionDataFail(String errorMessage) {
            // 归因失败 - 通常为网络问题，需要重试/兜底
            // 归因失败 → 标记为有机量
            saveAttributionDataAsOrganic();
        }
        
        @Override
        public void onAppOpenAttribution(Map<String, String> attributionData) {
            // 再互动归因（再营销场景）
        }
        
        @Override
        public void onAttributionFailure(String errorMessage) {
            // 归因请求失败
        }
    }
);
```

#### 3.3.2 iOS 异步归因获取（异步返回，无回调）

```swift
// iOS 无 onConversionDataSuccess 回调
// 归因数据异步返回，需等待 AppsFlyerLib 内部完成归因后再读取
// 通常策略：延迟若干秒后读取，或监听从 AF 后台推送的归因结果

// 读取归因数据（等待 ready）
DispatchQueue.main.asyncAfter(deadline: .now() + 5.0) {
    let attributionData = AppsFlyerLib.shared().getAttributionData()
    // 注意：此方法返回的数据可能不完整，详见 AF 文档
}
```

> ⚠️ **重要差异**：iOS 没有同步的 Conversion Data 回调！归因结果主要由服务端 Webhook（Push API）推送。客户端只能通过 `getAttributionData()` 获取不完整数据。

### 3.4 深度链接 (Deep Linking)

#### 3.4.1 OneLink 流程

```
用户点击广告链接
    │
    ├─ App 已安装 → 直接拉起 App → 解析深度链接参数 → 跳转目标页
    │
    └─ App 未安装 → 跳转 App Store/Google Play
                        │
                        └─ 安装后首次打开 → SDK 自动获取延迟深度链接 → 跳转目标页
```

#### 3.4.2 UDL (Unified Deep Linking)

```java
// Android
AppsFlyerLib.getInstance().subscribeForDeepLink(new DeepLinkListener() {
    @Override
    public void onDeepLinking(@NonNull DeepLinkResult deepLinkResult) {
        // 处理深度链接结果
        String deepLinkValue = deepLinkResult.getDeepLink().getStringValue();
        
        // 根据 af_dp 参数跳转到对应业务页面
        if (deepLinkResult.getStatus() == DeepLinkResult.Status.FOUND) {
            routeToContent(deepLinkValue);
        }
    }
});
```

### 3.5 Customer User ID 管理

```java
// 用户登录后设置
AppsFlyerLib.getInstance().setCustomerUserId("user_123456");

// 用户登出时清除
AppsFlyerLib.getInstance().setCustomerUserId(null);
```

> ⚠️ **关键规则**：`setCustomerUserId` 必须在 `start()` 之前调用，否则不会随当前 Session 上报。

---

## 4. 后端负责部分

> 后端是整个归因链条的**数据消费者 + 二次分发者**，负责接收归因回传、校验数据、落库存储、提供 BI 查询。

### 4.1 后端职责总览

```
┌────────────────────────────────────────────────────────────────┐
│                    后端职责 Checklist                           │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ✅ 1.  Push API (Webhook) — 实时接收归因回调                    │
│  ✅ 2.  S2S API — 服务端事件回传（归因失败兜底）                  │
│  ✅ 3.  Pull API — 定时拉取归因/事件汇总数据                     │
│  ✅ 4.  Conversion Data 接收 — 客户端归因数据上报到业务后端        │
│  ✅ 5.  归因数据校验（签名/去重/字段完整性）                       │
│  ✅ 6.  归因数据落库 + 关联用户业务 ID                            │
│  ✅ 7.  LTV/留存等计算链路对接                                    │
│  ✅ 8.  异常监控 + 告警                                           │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### 4.2 Push API — 实时归因回传（核心接口）

#### 4.2.1 接口规格

| 项目 | 说明 |
|------|------|
| 方式 | AppsFlyer → 业务后端 HTTP POST |
| 配置位置 | AppsFlyer 后台 → Integration → Push API |
| URL | `https://your-domain.com/api/attribution/af-callback` |
| 触发时机 | 归因完成时（首次归因 / 再归因 / 重新安装） |
| 重试策略 | AF 侧最多重试 3 次，间隔 15 分钟 |
| 签名验证 | HMAC-SHA256（`X-AppsFlyer-Signature` Header） |
| Content-Type | `application/json` |

#### 4.2.2 请求体结构

```json
{
  "app_id": "id1234567890",
  "app_name": "MyApp",
  "advertising_id": "xxxx-xxxx-xxxx-xxxx",
  "idfa": "xxxx-xxxx-xxxx-xxxx",
  "amazon_aid": "xxxx-xxxx-xxxx-xxxx",
  "android_id": "xxxx-xxxx-xxxx-xxxx",
  "oaid": "xxxx-xxxx-xxxx-xxxx",
  "idfv": "xxxx-xxxx-xxxx-xxxx",
  "customer_user_id": "user_123456",
  "appsflyer_id": "1641234567890-1234567890123456789",
  
  "attribution_type": "install",
  "af_status": "organic",
  "media_source": "facebook",
  "campaign": "summer_sale_2026",
  "campaign_id": "12345678",
  "adset": "US_lookalike_1%",
  "adset_id": "98765432",
  "ad": "creative_A_video_30s",
  "ad_id": "55555555",
  "ad_type": "video",
  "channel": "facebook",
  "agency": "agency_name",
  "cost_currency": "USD",
  "cost_value": "0.85",
  
  "site_id": "fb_site_123",
  "sub_site_id": "fb_sub_456",
  "sub1": "",
  "sub2": "",
  "sub3": "",
  "sub4": "",
  "sub5": "",
  
  "is_retargeting": false,
  "is_primary_attribution": true,
  "re_targeting_conversion_type": "re-install",
  
  "event_type": "install",
  "event_name": "install",
  "event_time": "2026-06-20T10:30:00.000Z",
  "event_revenue_amount": null,
  "event_revenue_currency": "USD",
  
  "install_time": "2026-06-20T10:29:50.000Z",
  "attributed_touch_type": "click",
  "attributed_touch_time": "2026-06-19T18:00:00.000Z",
  
  "ip": "192.0.2.1",
  "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0...)",
  "country_code": "US",
  "city": "San Francisco",
  "postal_code": "94105",
  "dma": "807",
  "operator": "AT&T",
  "platform": "ios",
  "language": "en",
  "device_type": "iPhone 14 Pro",
  "os_version": "16.0",
  "device_brand": "Apple",
  "device_model": "iPhone15,2",
  "wifi": true,
  
  "is_lat": false,
  "is_limited_ad_tracking": false,
  "contributor1_match_type": "id_matching",
  "contributor1_media_source": "facebook",
  "contributor1_campaign": "summer_sale_2026",
  "contributor1_touch_type": "click",
  "contributor1_touch_time": "2026-06-19T18:00:00.000Z",
  
  "custom_data": {},
  "original_url": "https://yourbrand.onelink.me/AbCd123"
}
```

#### 4.2.3 后端处理逻辑

```php
// 示例：Laravel 控制器
class AttributionCallbackController extends Controller
{
    public function handle(Request $request): JsonResponse
    {
        // 1. 签名校验
        $signature = $request->header('X-AppsFlyer-Signature');
        if (!$this->verifySignature($request->getContent(), $signature)) {
            Log::warning('AF callback signature mismatch', [
                'ip' => $request->ip()
            ]);
            return response()->json(['status' => 'rejected'], 403);
        }
        
        // 2. 去重检查（基于 appsflyer_id + event_type + event_time）
        $payload = $request->all();
        if ($this->isDuplicate($payload)) {
            return response()->json(['status' => 'duplicate'], 200);
        }
        
        // 3. 数据校验
        $validator = Validator::make($payload, [
            'appsflyer_id' => 'required|string',
            'event_type'   => 'required|string',
            'event_time'   => 'required|date',
            'media_source' => 'required|string',
        ]);
        
        if ($validator->fails()) {
            Log::error('AF callback validation failed', [
                'errors' => $validator->errors()->toArray(),
                'payload' => $payload
            ]);
            return response()->json(['status' => 'invalid'], 422);
        }
        
        // 4. 写入队列（异步处理，避免超时）
        ProcessAttributionJob::dispatch($payload)
            ->onQueue('attribution');
        
        // 5. 立即返回 200（AF 要求 2s 内响应）
        return response()->json(['status' => 'accepted'], 200);
    }
    
    private function verifySignature(string $body, ?string $signature): bool
    {
        if (empty($signature)) return false;
        
        $devKey = config('services.appsflyer.dev_key');
        $expected = hash_hmac('sha256', $body, $devKey);
        return hash_equals($expected, $signature);
    }
    
    private function isDuplicate(array $payload): bool
    {
        $key = implode('|', [
            $payload['appsflyer_id'] ?? '',
            $payload['event_type'] ?? '',
            $payload['event_time'] ?? ''
        ]);
        return Cache::add("af:dedup:{$key}", 1, 86400) === false;
    }
}
```

### 4.3 S2S API — 服务端事件回传

当客户端 SDK 无法上报时（如用户离线、ATT 拒绝），后端可通过 S2S API 直接向 AppsFlyer 上报事件。

```http
POST https://api2.appsflyer.com/inappevent/{app_id}
Headers:
  Content-Type: application/json
  authentication: {DEV_KEY}
```

```json
{
  "appsflyer_id": "1641234567890-1234567890123456789",
  "advertising_id": "xxxx-xxxx-xxxx-xxxx",
  "customer_user_id": "user_123456",
  "eventName": "af_purchase",
  "eventValue": {
    "af_revenue": "29.99",
    "af_currency": "USD",
    "af_content_id": "subscription_monthly"
  },
  "eventTime": "2026-06-20T10:30:00.000Z",
  "eventCurrency": "USD",
  "bundleIdentifier": "com.myapp.bundle",
  "os": "android"
}
```

**后端 S2S 实现示例**：

```php
class AppsFlyerS2SService
{
    private string $devKey;
    private string $appId;
    private string $baseUrl = 'https://api2.appsflyer.com';
    
    public function sendEvent(string $appsflyerId, string $eventName, array $eventValues): bool
    {
        $payload = [
            'appsflyer_id'    => $appsflyerId,
            'eventName'       => $eventName,
            'eventValue'      => json_encode($eventValues),
            'eventTime'       => now()->toIso8601ZuluString(),
            'bundleIdentifier' => config('app.bundle_id'),
            'os'              => 'android', // or 'ios'
        ];
        
        $response = Http::timeout(10)
            ->withHeaders([
                'Content-Type'  => 'application/json',
                'authentication' => $this->devKey,
            ])
            ->post("{$this->baseUrl}/inappevent/{$this->appId}", $payload);
        
        if ($response->successful()) {
            Log::info('AF S2S event sent', [
                'af_id'   => $appsflyerId,
                'event'   => $eventName,
                'status'  => $response->status()
            ]);
            return true;
        }
        
        Log::error('AF S2S event failed', [
            'af_id'   => $appsflyerId,
            'event'   => $eventName,
            'response' => $response->body()
        ]);
        return false;
    }
}
```

### 4.4 Pull API — 数据拉取

#### 4.4.1 拉取场景

| 场景 | 用途 | 频率 |
|------|------|:---:|
| Installs Report | 拉取安装归因明细 | 每小时 |
| In-App Events Report | 拉取 App 内事件明细 | 每小时 |
| Organic Installs | 拉取自然量安装 | 每小时 |
| Cohort Report | 拉取队列留存数据 | 每天 |
| Ad Revenue Report | 拉取广告收入 | 每天 |
| Uninstall Report | 拉取卸载数据 | 每天 |

#### 4.4.2 API 调用示例

```http
GET https://hq1.appsflyer.com/export/{app_id}/installs_report/v5
    ?api_token={API_TOKEN}
    &from=2026-06-19
    &to=2026-06-20
    &additional_fields=install_app_store,contributor1_match_type,keyword_match_type,keyword_id,att,conversion_type
```

#### 4.4.3 后端定时任务

```php
// 示例：Laravel Command
class PullAttributionData extends Command
{
    protected $signature = 'attribution:pull {date?}';
    
    public function handle(AppsflyerPullService $service)
    {
        $date = $this->argument('date') ?: now()->subDay()->toDateString();
        
        // 1. 拉取安装归因明细
        $installs = $service->fetchInstallsReport($date);
        $this->info("Fetched {$installs->count()} install records for {$date}");
        
        // 2. 入库（upsert，避免重复）
        foreach ($installs as $record) {
            AttributionInstall::updateOrCreate(
                ['appsflyer_id' => $record['appsflyer_id'], 'install_time' => $record['install_time']],
                $record
            );
        }
        
        // 3. 拉取事件数据
        $events = $service->fetchEventsReport($date);
        $this->info("Fetched {$events->count()} event records for {$date}");
        
        // ... 入库逻辑
    }
}
```

---

## 5. 完整业务流转链路

### 5.1 首次安装归因完整流程

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  用户     │    │ 广告渠道  │    │AppsFlyer │    │  客户端   │    │ 业务后端  │
└────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘
     │                │               │               │               │
     │  ① 点击广告    │               │               │               │
     ├───────────────>│               │               │               │
     │                │               │               │               │
     │                │ ② 发送点击数据│               │               │
     │                ├──────────────>│               │               │
     │                │   (含设备ID、  │               │               │
     │                │    渠道信息)   │               │               │
     │                │               │               │               │
     │  ③ 跳转 App Store / Google Play 下载 & 安装   │               │
     ├────────────────┼───────────────┼──────────────>│               │
     │                │               │               │               │
     │                │               │               │ ④ SDK 自动     │
     │                │               │               │ 上报安装事件   │
     │                │               │               │ (含设备指纹)    │
     │                │               │<──────────────┤               │
     │                │               │               │               │
     │                │               │ ⑤ 归因引擎匹配 │               │
     │                │               │ 点击数据 ↔ 安装 │               │
     │                │               │               │               │
     │                │               │ ⑥ 归因结果推送 │               │
     │                │               │ (Push API)    │               │
     │                │               ├──────────────────────────────>│
     │                │               │               │               │
     │                │               │               │ ⑦ 归因数据     │
     │                │               │               │ onSuccess回调  │
     │                │               │               │<──────────────┤
     │                │               │               │               │
     │                │               │               │ ⑧ 客户端上报   │
     │                │               │               │ 归因数据到业务 │
     │                │               │               ├──────────────>│
     │                │               │               │ 后端 (/api/    │
     │                │               │               │ attribution/  │
     │                │               │               │  client-report)│
     │                │               │               │               │
     │                │               │               │               │ ⑨ 双源校验
     │                │               │               │               │ Push + Client
     │                │               │               │               │ 取可信度更高
     │                │               │               │               │
     │                │               │               │               │ ⑩ 落库 + 关联
     │                │               │               │               │ 用户业务ID
     │                │               │               │               │
     │  ⑪ 触发新手体验 / 奖励发放 / 归因分析                       │
     │                │               │               │               │
     ▼                ▼               ▼               ▼               ▼
```

### 5.2 时序图（详细状态）

```
  Client SDK              AppsFlyer                业务后端              DB/Cache
     │                       │                       │                     │
     │──① App 启动──────────>│                       │                     │
     │   (SDK.start)         │                       │                     │
     │                       │                       │                     │
     │<─② AF ID 分配─────────│                       │                     │
     │                       │                       │                     │
     │──③ install 事件──────>│                       │                     │
     │   (dev key+app id)    │                       │                     │
     │   (设备指纹+IP)        │                       │                     │
     │                       │                       │                     │
     │─────────④ 归因引擎匹配（后台异步）───────────│                     │
     │                       │                       │                     │
     │<─⑤ Conversion Data───│                       │                     │
     │   (Android 回调)      │                       │                     │
     │   {                   │                       │                     │
     │     af_status,        │                       │                     │
     │     media_source,     │                       │                     │
     │     campaign, ...     │                       │                     │
     │   }                   │                       │                     │
     │                       │                       │                     │
     │──⑥ 归因数据上报───────┼──────────────────────>│                     │
     │   POST /api/          │                       │                     │
     │   attribution/        │                       │                     │
     │   client-report       │                       │                     │
     │                       │                       │                     │
     │                       │──⑦ Push API──────────>│                     │
     │                       │   POST /api/          │                     │
     │                       │   attribution/        │                     │
     │                       │   af-callback         │                     │
     │                       │                       │                     │
     │                       │                       │──⑧ 签名校验          │
     │                       │                       │   去重检查           │
     │                       │                       │   字段校验           │
     │                       │                       │                     │
     │                       │                       │──⑨ 数据落库────────>│
     │                       │                       │   users_attribution │
     │                       │                       │<─ OK ───────────────│
     │                       │                       │                     │
     │                       │<─⑩ 200 OK─────────────│                     │
     │                       │                       │                     │
     │<─⑪ 回传确认（可选）───│                       │                     │
     │                       │                       │                     │
```

### 5.3 付费事件全链路

```
  Client SDK              AppsFlyer                业务后端             支付网关
     │                       │                       │                    │
     │──① 用户下单───────────┼───────────────────────┼───────────────────>│
     │                       │                       │                    │
     │                       │                       │<─② 支付回调─────────│
     │                       │                       │  (成功/失败)        │
     │                       │                       │                    │
     │                       │                       │──③ 创建订单记录────>│
     │                       │                       │  status=paid       │
     │                       │                       │                    │
     │                       │                       │──④ S2S 上报 AF ───>│
     │                       │                       │  af_purchase       │
     │                       │                       │  +revenue参数       │
     │                       │                       │                    │
     │  ⑤ SDK 也可能上报─────>│                       │                    │
     │  (双保险: S2S + SDK)   │                       │                    │
     │                       │                       │                    │
     │                       │──⑥ AF 去重处理────────│                    │
     │                       │  (基于 af_order_id)   │                    │
     │                       │                       │                    │
     │                       │──⑦ 付费归因推送──────>│                    │
     │                       │  Push API            │                    │
     │                       │  event_type=purchase │                    │
     │                       │                       │                    │
     │                       │                       │──⑧ 更新LTV/ROAS────│
     │                       │                       │                    │
     ▼                       ▼                       ▼                    ▼
```

> ⚠️ **S2S vs SDK 上报策略**：对于付费事件，**强烈建议后端 S2S 上报为主，客户端 SDK 上报为辅**。原因：
> 1. 服务端有支付回执（Receipt）验证能力
> 2. 避免客户端欺诈/重复上报
> 3. 网络可靠性更高
> 4. 支持订阅续费/退款等复杂场景

### 5.4 深度链接流转

```
  用户点击 OneLink
       │
       ▼
  ┌─────────────────────────────────────────────────────┐
  │             AppsFlyer OneLink 服务                    │
  │                                                      │
  │  ① 解析链接参数:                                      │
  │     - af_dp（目标页面路径）                           │
  │     - af_media_source / af_campaign / pid             │
  │     - af_sub1 ~ af_sub5（自定义参数）                 │
  │                                                      │
  │  ② 判断 App 是否已安装                                │
  └───────────┬─────────────────────────────────────────┘
              │
     ┌────────┴────────┐
     │                 │
  已安装             未安装
     │                 │
     ▼                 ▼
  ┌─────────┐    ┌──────────────┐
  │ 直接拉起 │    │ 跳转 App Store │
  │ App      │    │ 或 Google Play │
  └────┬────┘    └──────┬───────┘
       │                │
       ▼                │
  ┌──────────┐          │
  │ SDK.onDeep│          │
  │ Link()   │          │
  └────┬─────┘          │
       │                │
       ▼                ▼
  ┌──────────────────────────┐
  │ 安装后首次启动             │
  │ AppsFlyer 延迟深度链接回调 │
  │ onDeepLinking()           │
  └────┬─────────────────────┘
       │
       ▼
  ┌──────────────────────────┐
  │ 路由到目标页面             │
  │ 例: /product/detail/123  │
  │ 携带 af_media_source 等   │
  └──────────────────────────┘
```

---

## 6. 状态流转链路

### 6.1 归因状态机

```
                    ┌─────────────┐
                    │   NOT_INIT  │  初始状态（未上报安装）
                    └──────┬──────┘
                           │
                           │ SDK.start() 触发 install 事件上报
                           ▼
                    ┌─────────────┐
                    │  ATTRIBUTING │  归因进行中
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
     ┌────────────┐ ┌───────────┐ ┌──────────────┐
     │ ATTRIBUTED │ │  ORGANIC  │ │ ATTRIBUTION  │
     │ (归因成功)  │ │  (自然量)  │ │ _FAILED      │
     └──────┬─────┘ └─────┬─────┘ │ (归因失败)    │
            │             │       └──────┬───────┘
            │             │              │
            │             │        自动降级为 ORGANIC
            │             │◄─────────────┘
            │             │
            │       ┌─────┴──────────────────────┐
            │       │                            │
            ▼       ▼                            ▼
     ┌────────────────────────────────────────────────┐
     │                 RE-ATTRIBUTING                  │
     │  (再归因: 沉默用户 90 天内再次激活)               │
     │  - 首次启动 → 再激活（用户主动行为）              │
     │  - 再营销广告点击 → 再归因（渠道行为）            │
     └────────────┬───────────────────────────────────┘
                  │
          ┌───────┼───────┐
          │               │
          ▼               ▼
   ┌────────────┐  ┌──────────────┐
   │ RE_ATTRIB  │  │ 保持原归因    │
   │ _SUCCESS   │  │  (不覆盖)     │
   └────────────┘  └──────────────┘
```

### 6.2 归因状态枚举定义

```typescript
enum AttributionStatus {
  /** 初始态：未上报安装事件 */
  NOT_INIT = 'not_init',
  
  /** 归因进行中：已上报 install，等待归因引擎匹配 */
  ATTRIBUTING = 'attributing',
  
  /** 归因成功：已完成渠道匹配 */
  ATTRIBUTED = 'attributed',
  
  /** 自然量：无匹配渠道（有机用户） */
  ORGANIC = 'organic',
  
  /** 归因失败：网络/超时等原因，降级为自然量 */
  ATTRIBUTION_FAILED = 'attribution_failed',
  
  /** 再归因成功：沉默用户被重新归因 */
  RE_ATTRIBUTED = 're_attributed',
  
  /** 重新安装：用户卸载后重新安装 */
  RE_INSTALL = 're_install',
}
```

### 6.3 用户归因记录生命周期

```
时间轴 ────────────────────────────────────────────────────────────────>

T0: 用户点击广告
    │
    │  [渠道侧记录 click_id + 设备指纹]
    │
    ▼
T1: 用户下载 App + 首次打开 (install time)
    │
    │  状态: NOT_INIT → ATTRIBUTING
    │  SDK 上报 install 事件到 AF
    │
    │  ┌─────────── 归因窗口内（默认7天）───────────┐
    │  │                                            │
    ▼  ▼
T2: AF 归因引擎匹配成功
    │
    │  状态: ATTRIBUTING → ATTRIBUTED (或 ORGANIC)
    │  - 找到匹配点击 → ATTRIBUTED
    │  - 无匹配点击   → ORGANIC
    │  - 超时未完成   → ATTRIBUTION_FAILED → ORGANIC
    │
    ▼
T3: 用户产生业务行为
    │
    │  ├── 注册 → af_complete_registration → 归因给原始渠道
    │  ├── 付费 → af_purchase → 归因给原始渠道，计入该渠道 LTV
    │  └── 其他事件 → 归因给原始渠道
    │
    ▼
T4: 沉默期（用户 90 天未打开 App）
    │
    ▼
T5: 用户通过再营销广告重新打开
    │
    │  状态: ATTRIBUTED → RE_ATTRIBUTED
    │  - 原始渠道保留在 contributor1
    │  - 再营销渠道记录在 media_source（可能覆盖）
    │  - is_retargeting = true
    │
    ▼
T6: 用户卸载后重新安装
    │
    │  状态: XXX → RE_INSTALL
    │  - 重新走归因流程
    │  - 原始归因信息保留在历史记录
```

### 6.4 关键状态转换表

```
┌────────────────────┬────────────────────────────┬──────────────────────────────┐
│   当前状态          │         触发事件            │          目标状态             │
├────────────────────┼────────────────────────────┼──────────────────────────────┤
│ NOT_INIT           │ SDK 首次上报 install        │ ATTRIBUTING                  │
├────────────────────┼────────────────────────────┼──────────────────────────────┤
│ ATTRIBUTING        │ 归因引擎匹配成功             │ ATTRIBUTED                   │
│ ATTRIBUTING        │ 归因引擎无匹配（自然量）      │ ORGANIC                      │
│ ATTRIBUTING        │ 归因窗口过期（默认 7 天）     │ ATTRIBUTION_FAILED           │
│ ATTRIBUTING        │ 网络失败 / SDK 异常          │ ATTRIBUTION_FAILED           │
├────────────────────┼────────────────────────────┼──────────────────────────────┤
│ ATTRIBUTED         │ 用户沉默 90 天后再次激活      │ RE_ATTRIBUTING               │
│ ATTRIBUTED         │ 用户卸载后重新安装            │ RE_INSTALL                   │
│ ATTRIBUTED         │ Push API 收到 re-attribution │ RE_ATTRIBUTED                │
├────────────────────┼────────────────────────────┼──────────────────────────────┤
│ ORGANIC            │ 再营销广告点击后激活          │ RE_ATTRIBUTED                │
│ ORGANIC            │ 用户卸载后重新安装            │ RE_INSTALL                   │
├────────────────────┼────────────────────────────┼──────────────────────────────┤
│ ATTRIBUTION_FAILED │ 手动/自动降级处理            │ ORGANIC (终端态)              │
├────────────────────┼────────────────────────────┼──────────────────────────────┤
│ RE_ATTRIBUTED      │ 再次沉默后重新激活            │ RE_ATTRIBUTED (再次)          │
├────────────────────┼────────────────────────────┼──────────────────────────────┤
│ RE_INSTALL         │ 重新安装后的归因完成          │ ATTRIBUTED / ORGANIC (重新开始) │
└────────────────────┴────────────────────────────┴──────────────────────────────┘
```

### 6.5 事件上报状态流转

```
                    ┌─────────────────┐
                    │   事件产生       │
                    │ (App 内行为)     │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │                 │
               SDK 上报           S2S 上报
               (客户端)            (后端)
                    │                 │
                    ▼                 ▼
            ┌─────────────────────────────┐
            │        事件状态               │
            ├─────────────────────────────┤
            │                             │
            │  PENDING─── 已生成，等待上报  │
            │     │                       │
            │     ▼                       │
            │  SENDING─── 正在发送中       │
            │     │                       │
            │     ├── SUCCESS ── 成功      │
            │     │                       │
            │     ├── FAILED ──── 失败     │
            │     │    │                  │
            │     │    └── 重试（最多3次）  │
            │     │         │             │
            │     │         ├── SUCCESS    │
            │     │         └── PERMANENT_FAILED │
            │     │                         │
            │     │                  写入死信队列
            │     │                         │
            │     └── TIMEOUT ── 超时      │
            │          │                   │
            │          └── 降级重试         │
            │                             │
            └─────────────────────────────┘
```

---

## 7. 数据模型设计

### 7.1 归因主表

```sql
-- users_attribution: 用户归因主表
CREATE TABLE users_attribution (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT          NOT NULL COMMENT '业务用户ID（注册后关联）',
    appsflyer_id    VARCHAR(64)     NOT NULL COMMENT 'AppsFlyer 用户唯一ID',
    
    -- 归因信息
    af_status       VARCHAR(32)     NOT NULL DEFAULT 'not_init' COMMENT '归因状态: not_init/attributing/attributed/organic/attribution_failed/re_attributed',
    attribution_type VARCHAR(32)    NULL COMMENT '归因类型: install/re-install/re-attribution',
    media_source    VARCHAR(128)    NULL COMMENT '媒体源: facebook/google/tiktok/...',
    campaign        VARCHAR(256)    NULL COMMENT '广告系列名称',
    campaign_id     VARCHAR(64)     NULL COMMENT '广告系列 ID',
    adset           VARCHAR(256)    NULL COMMENT '广告组名称',
    adset_id        VARCHAR(64)     NULL COMMENT '广告组 ID',
    ad              VARCHAR(256)    NULL COMMENT '具体广告名称',
    ad_id           VARCHAR(64)     NULL COMMENT '广告 ID',
    channel         VARCHAR(128)    NULL COMMENT '渠道',
    agency          VARCHAR(128)    NULL COMMENT '代理',
    
    -- 归因时间
    attributed_touch_type VARCHAR(16) NULL COMMENT '触点类型: click/impression',
    attributed_touch_time DATETIME   NULL COMMENT '触点时间（点击/展示时间）',
    install_time    DATETIME        NULL COMMENT '安装时间（首次打开 App）',
    attribution_time DATETIME       NULL COMMENT '归因完成时间（AF 推送到后端的时间）',
    
    -- 归因详情
    is_retargeting  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否再营销归因',
    is_primary_attribution TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否主要归因',
    match_type      VARCHAR(32)     NULL COMMENT '匹配类型: id_matching/fingerprinting/probabilistic',
    original_url    TEXT            NULL COMMENT '原始归因链接',
    
    -- 辅助归因（contributor1: 原始渠道）
    contributor1_media_source VARCHAR(128) NULL,
    contributor1_campaign     VARCHAR(256) NULL,
    contributor1_touch_type   VARCHAR(16)  NULL,
    contributor1_touch_time   DATETIME     NULL,
    
    -- 广告成本
    cost_currency   VARCHAR(8)      NULL COMMENT '成本币种',
    cost_value      DECIMAL(12,4)   NULL COMMENT '成本金额',
    
    -- 设备信息
    platform        VARCHAR(16)     NULL COMMENT '平台: ios/android',
    advertising_id  VARCHAR(128)    NULL COMMENT 'GAID/IDFA',
    device_type     VARCHAR(64)     NULL COMMENT '设备型号',
    os_version      VARCHAR(16)     NULL COMMENT '系统版本',
    country_code    VARCHAR(8)      NULL COMMENT '国家代码',
    city            VARCHAR(64)     NULL COMMENT '城市',
    language        VARCHAR(16)     NULL COMMENT '语言',
    is_lat          TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否限制广告追踪',
    
    -- 自定义参数
    sub1            VARCHAR(256)    NULL,
    sub2            VARCHAR(256)    NULL,
    sub3            VARCHAR(256)    NULL,
    sub4            VARCHAR(256)    NULL,
    sub5            VARCHAR(256)    NULL,
    
    -- 元数据
    raw_payload     JSON            NULL COMMENT '完整 Payload（用于排查）',
    data_source     VARCHAR(16)     NOT NULL DEFAULT 'push' COMMENT '数据来源: push/s2s/client/pull',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_af_id_install_time (appsflyer_id, install_time),
    INDEX idx_user_id (user_id),
    INDEX idx_media_source (media_source),
    INDEX idx_campaign (campaign),
    INDEX idx_install_time (install_time),
    INDEX idx_platform_country (platform, country_code),
    INDEX idx_af_status (af_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户广告归因表';
```

### 7.2 归因事件流水表

```sql
-- attribution_events: 归因事件流水表（Push API 每次推送都记录）
CREATE TABLE attribution_events (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    appsflyer_id    VARCHAR(64)     NOT NULL,
    event_type      VARCHAR(32)     NOT NULL COMMENT 'install/re-attribution/in-app-event/uninstall',
    event_name      VARCHAR(128)    NULL COMMENT '事件名称',
    event_time      DATETIME        NOT NULL COMMENT '事件时间',
    event_value     JSON            NULL COMMENT '事件参数（含 revenue 等）',
    
    -- 回调签名
    callback_signature VARCHAR(256) NULL COMMENT 'AF 回调签名（用于验签）',
    
    -- 去重键
    dedup_key       VARCHAR(256)    NOT NULL COMMENT '去重键: appsflyer_id|event_type|event_time',
    
    -- 处理状态
    process_status  VARCHAR(16)     NOT NULL DEFAULT 'received' COMMENT 'received/processed/failed/ignored',
    process_message TEXT            NULL COMMENT '处理信息/错误原因',
    processed_at    DATETIME        NULL COMMENT '处理完成时间',
    
    -- 原始数据
    raw_payload     JSON            NOT NULL COMMENT '完整 Payload',
    data_source     VARCHAR(16)     NOT NULL DEFAULT 'push' COMMENT 'push/s2s/pull/client',
    
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_dedup (dedup_key),
    INDEX idx_af_id (appsflyer_id),
    INDEX idx_event_type_time (event_type, event_time),
    INDEX idx_process_status (process_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='归因事件流水表';
```

### 7.3 用户事件上报表

```sql
-- user_events: 业务事件上报表
CREATE TABLE user_events (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT          NOT NULL COMMENT '业务用户ID',
    appsflyer_id    VARCHAR(64)     NULL COMMENT 'AppsFlyer ID',
    event_name      VARCHAR(128)    NOT NULL COMMENT '事件名称',
    event_value     JSON            NULL COMMENT '事件参数',
    event_time      DATETIME        NOT NULL COMMENT '事件时间',
    
    -- 上报状态
    report_method   VARCHAR(8)      NOT NULL DEFAULT 'sdk' COMMENT '上报方式: sdk/s2s',
    report_status   VARCHAR(16)     NOT NULL DEFAULT 'pending' COMMENT 'pending/sent/success/failed/dead',
    report_retries  INT             NOT NULL DEFAULT 0 COMMENT '重试次数',
    reported_at     DATETIME        NULL COMMENT '上报成功时间',
    report_response TEXT            NULL COMMENT '上报响应',
    
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_user_event_time (user_id, event_time),
    INDEX idx_af_id (appsflyer_id),
    INDEX idx_report_status (report_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户事件上报表';
```

---

## 8. 异常场景与兜底策略

### 8.1 异常场景矩阵

```
┌────┬──────────────────────────┬──────────────────────────────────┬──────────────────────────────┐
│ #  │        异常场景           │             影响                  │         兜底策略              │
├────┼──────────────────────────┼──────────────────────────────────┼──────────────────────────────┤
│ 1  │ SDK 初始化失败            │ install 事件无法上报              │ 后端 S2S 补报 install 事件     │
│    │ (网络/配置错误)           │                                  │                              │
├────┼──────────────────────────┼──────────────────────────────────┼──────────────────────────────┤
│ 2  │ iOS ATT 被拒绝            │ 无 IDFA，归因准确度下降           │ 概率归因 + IDFV + IP 辅助匹配  │
│    │                          │                                  │ Push API 优先接收 AF 结果     │
├────┼──────────────────────────┼──────────────────────────────────┼──────────────────────────────┤
│ 3  │ 归因窗口内无网络          │ 安装事件延迟上报                  │ 本地队列缓存 + 网络恢复后重试   │
│    │ (用户离线安装后未联网)     │                                  │ 偏移归因窗口（最大允许 30 天）  │
├────┼──────────────────────────┼──────────────────────────────────┼──────────────────────────────┤
│ 4  │ Push API 推送超时/失败    │ 归因数据丢失                      │ AF 侧自动重试 3 次（间隔 15min）│
│    │ (后端服务不可用)          │                                  │ + Pull API 定时补拉           │
├────┼──────────────────────────┼──────────────────────────────────┼──────────────────────────────┤
│ 5  │ 双端上报重复              │ 付费/LTV 重复计数                  │ af_order_id / dedup_key 去重   │
│    │ (SDK+S2S 同时上报)        │                                  │ AF 侧 + 业务侧双重去重         │
├────┼──────────────────────────┼──────────────────────────────────┼──────────────────────────────┤
│ 6  │ 用户切换设备              │ ID 不匹配，归因断裂               │ Customer User ID 关联         │
│    │                          │                                  │ 登录时 setCustomerUserId      │
├────┼──────────────────────────┼──────────────────────────────────┼──────────────────────────────┤
│ 7  │ 渠道数据延迟/缺失         │ LTV/ROAS 计算不准                 │ 定时 Pull + 对账脚本补全        │
│    │ (Facebook/Google API 慢)  │                                  │ 次日补偿修正                   │
├────┼──────────────────────────┼──────────────────────────────────┼──────────────────────────────┤
│ 8  │ 数据劫持                  │ 归因被伪装成渠道量                 │ AF Protect360 防作弊工具       │
│    │ (点击泛滥/设备农场)        │                                  │ + 后端异常指标监控             │
├────┼──────────────────────────┼──────────────────────────────────┼──────────────────────────────┤
│ 9  │ Conversion Data 未回调    │ 客户端无法获取归因数据             │ 后端 Push API 为主通道         │
│    │ (iOS / 网络问题)          │                                  │ 客户端不依赖此回调做核心逻辑     │
├────┼──────────────────────────┼──────────────────────────────────┼──────────────────────────────┤
│ 10 │ OneLink 深度链接故障      │ 延迟深度链接失效，用户到首页       │ 本地缓存 af_dp 参数            │
│    │ (AF 服务异常)             │ 而非目标落地页                    │ 服务端推送后补发落地页          │
└────┴──────────────────────────┴──────────────────────────────────┴──────────────────────────────┘
```

### 8.2 数据对账策略

```
         ┌──────────────────────────────────────────────┐
         │              每日数据对账流程                  │
         └──────────────────────────────────────────────┘

  数据源 A: AppsFlyer Dashboard 数据
       │
       ├──── 1. 安装数对比
       │     AF Dashboard 安装数 vs 业务库安装数
       │     差异 > 2% → 告警
       │
       ├──── 2. 归因覆盖率
       │     有归因的安装 / 总安装 ≥ 85%
       │     低于阈值 → 检查 Push API 成功率
       │
       ├──── 3. 付费事件数对比
       │     AF 付费事件数 vs 支付网关订单数
       │     差异 > 1% → 检查 S2S 上报
       │
       └──── 4. 渠道成本对比
             AF 成本数据 vs 渠道端成本数据
             差异 > 5% → 检查 Cost API 拉取
```

---

## 9. 测试与验收清单

### 9.1 客户端测试

```
┌────────────────────────────────────────────────────────────────┐
│                      客户端测试清单                             │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  □ SDK 初始化成功（Android / iOS）                              │
│  □ 冷启动上报 install 事件                                      │
│  □ 热启动上报 af_start 事件                                     │
│  □ Conversion Data 回调成功（Android）                          │
│  □ 获取 AppsFlyer ID 成功                                       │
│  □ 自定义事件上报成功（af_purchase / af_complete_registration）  │
│  □ Revenue 事件参数完整（revenue / currency / order_id）         │
│  □ Deferred Deep Link 成功跳转目标页面                           │
│  □ UDL (Unified Deep Link) 成功                                   │
│  □ ATT 弹窗正常弹出（iOS 14.5+）                                │
│  □ ATT 拒绝后仍可正常使用（自然量归因）                          │
│  □ Customer User ID 设置/清除正常                               │
│  □ 无网络时事件不丢失（本地缓存）                                │
│  □ 网络恢复后自动补报                                            │
│  □ SDK 版本与 AF 后台一致                                       │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### 9.2 后端测试

```
┌────────────────────────────────────────────────────────────────┐
│                       后端测试清单                              │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  □ Push API 回调接收正常                                        │
│  □ Push API 签名校验通过                                        │
│  □ Push API 签名校验拒绝（防篡改）                               │
│  □ 重复 Push 去重成功                                           │
│  □ 归因数据正确落库（users_attribution）                         │
│  □ 事件流水完整记录（attribution_events）                        │
│  □ S2S 事件回传成功                                             │
│  □ S2S 补充上报（客户端失败时）                                  │
│  □ Pull API 拉取成功（installs_report）                         │
│  □ Pull API 拉取成功（events_report）                           │
│  □ Pull API 拉取成功（organic_installs）                        │
│  □ 数据对账通过（AF ↔ 业务库）                                  │
│  □ 重复上报去重（af_order_id / dedup_key）                       │
│  □ 处理延迟监控 < 1s（P99）                                     │
│  □ 异常告警正常触发                                              │
│  □ 死信队列重试机制正常                                          │
│  □ Customer User ID 关联正确                                    │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### 9.3 端到端测试

```
  1. 全新设备 -> 点击广告 -> 下载 App -> 首次打开 -> 验证归因数据 ✔
  2. 全新设备 -> 直接搜索下载（自然量）-> 打开 -> 验证 organic ✔
  3. 已安装用户 -> 点击再营销广告 -> 重新打开 -> 验证 re-attribution ✔
  4. 卸载用户 -> 点击广告 -> 重新安装 -> 验证 re-install ✔
  5. 付费用户 -> 完成购买 -> 验证 revenue 事件归因到正确渠道 ✔
  6. 深度链接 -> 验证 Deferred Deep Link 落地页正确 ✔
  7. 无网络安装 -> 联网后打开 -> 验证延迟上报归因正确 ✔
```

---

## 附录

### A. 对接环境

| 环境 | AppsFlyer 控制台 | 说明 |
|------|:--:|------|
| Sandbox | 沙箱环境 | 开发/测试用，数据不参与正式报表 |
| Production | 生产环境 | 正式上线环境 |

### B. 关键配置一览

| 配置项 | Android | iOS | 说明 |
|--------|:---:|:---:|------|
| SDK 版本 | ≥ 6.14.x | ≥ 6.14.x | 始终使用最新稳定版 |
| 最小 OS 版本 | Android 5.0+ | iOS 13.0+ | AF SDK 支持的最低 OS |
| Dev Key | ✅ | ✅ | 从 AF 后台获取 |
| App ID | ✅ | — | Android 包名 |
| Apple App ID | — | ✅ | App Store Connect 中的 ID |
| ATT 弹窗 | — | ✅ | iOS 14.5+ 必须 |
| OneLink Domain | ✅ | ✅ | 自定义 OneLink 域名 |
| Push API URL | 后端配置 | 后端配置 | AF 后台配置回调 URL |
| S2S API Token | 后端配置 | 后端配置 | 用于服务端 API 调用 |

### C. 参考资源

- [AppsFlyer 官方文档](https://dev.appsflyer.com/hc/docs)
- [Android SDK 集成指南](https://dev.appsflyer.com/hc/docs/android-sdk)
- [iOS SDK 集成指南](https://dev.appsflyer.com/hc/docs/ios-sdk)
- [Push API 指南](https://dev.appsflyer.com/hc/docs/push-apis)
- [OneLink 深度链接](https://dev.appsflyer.com/hc/docs/onelink-deep-links)
- [S2S API 事件上报](https://dev.appsflyer.com/hc/docs/server-to-server-events-api)

---

> **文档维护者**: 业务后端 + 客户端团队  
> **最后更新**: 2026-06-20
