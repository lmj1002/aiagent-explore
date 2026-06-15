# 高级 WebSocket 面试知识架构

> 目标受众：高级后端开发 / 架构师  
> 版本：v1.0  
> 更新日期：2026-06-15

---

## 目录

1. [协议原理](#1-协议原理)
2. [服务端实现](#2-服务端实现)
3. [分布式 WebSocket 架构](#3-分布式-websocket-架构)
4. [可靠性保障](#4-可靠性保障)
5. [安全防护](#5-安全防护)
6. [性能优化](#6-性能优化)
7. [场景实战](#7-场景实战)
8. [替代方案对比](#8-替代方案对比)

---

## 1. 协议原理

### 1.1 HTTP Upgrade 握手

WebSocket 握手通过 HTTP Upgrade 机制完成，客户端发送一个包含特定头部的 HTTP 请求，服务端返回 101 Switching Protocols 状态码。

**请求报文：**

```
GET /chat HTTP/1.1
Host: server.example.com
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==
Sec-WebSocket-Version: 13
Sec-WebSocket-Protocol: chat, superchat
```

**响应报文：**

```
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
Sec-WebSocket-Protocol: chat
```

**核心校验逻辑：**

服务端将 `Sec-WebSocket-Key` 与固定 GUID `258EAFA5-E914-47DA-95CA-C5AB0DC85B11` 拼接后做 SHA-1 摘要，再进行 Base64 编码得到 `Sec-WebSocket-Accept`。客户端收到后对比该值，确保不是非 WebSocket 中间件代理的请求。

```
Accept = base64(sha1(Key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"))
```

**Go 握手验证实现：**

```go
package main

import (
    "crypto/sha1"
    "encoding/base64"
    "fmt"
    "net/http"
)

var websocketGUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

func wsUpgradeHandler(w http.ResponseWriter, r *http.Request) {
    if r.Method != "GET" {
        http.Error(w, "Method not allowed", 405)
        return
    }

    key := r.Header.Get("Sec-WebSocket-Key")
    if key == "" {
        http.Error(w, "Missing Sec-WebSocket-Key", 400)
        return
    }

    // 计算 Accept
    h := sha1.New()
    h.Write([]byte(key + websocketGUID))
    accept := base64.StdEncoding.EncodeToString(h.Sum(nil))

    // 手动实现 101 响应
    hdr := w.Header()
    hdr.Set("Upgrade", "websocket")
    hdr.Set("Connection", "Upgrade")
    hdr.Set("Sec-WebSocket-Accept", accept)

    // 选择子协议（如果客户端提供了）
    if subproto := r.Header.Get("Sec-WebSocket-Protocol"); subproto != "" {
        hdr.Set("Sec-WebSocket-Protocol", subproto)
    }

    w.WriteHeader(http.StatusSwitchingProtocols)
    // 此处需要 hijack connection 开始 WebSocket 通信
}

func main() {
    http.HandleFunc("/ws", wsUpgradeHandler)
    http.ListenAndServe(":8080", nil)
}
```

**PHP Swoole WebSocket 服务器：**

```php
<?php
use Swoole\WebSocket\Server;
use Swoole\Http\Request;
use Swoole\Http\Response;

$server = new Server("0.0.0.0", 9501);

// HTTP 请求回调 — 也可以在此处理握手逻辑
$server->on("request", function (Request $req, Response $resp) {
    $resp->end("<h1>WebSocket Server</h1>");
});

// WebSocket 握手事件（可在此做自定义鉴权）
$server->on("handshake", function (Request $request, Response $response): bool {
    // 自定义鉴权逻辑
    $token = $request->get['token'] ?? '';
    if (empty($token)) {
        $response->status(403);
        $response->end("Forbidden");
        return false; // 拒绝握手
    }

    // 可以在此验证 Sec-WebSocket-Key（Swoole 默认处理）
    // 返回 true 表示 Swoole 接管后续通信
    return true;
});

$server->on("message", function (Server $server, $frame) {
    echo "收到消息: {$frame->data}\n";
    $server->push($frame->fd, "Server: " . $frame->data);
});

$server->on("open", function (Server $server, $request) {
    echo "新连接: {$request->fd}\n";
    $server->push($request->fd, "欢迎连接！");
});

$server->on("close", function (Server $server, $fd) {
    echo "连接关闭: {$fd}\n";
});

$server->start();
```

**高频面试题：**

| 问题 | 要点 |
|------|------|
| WebSocket 握手为什么需要 Sec-WebSocket-Key？ | 防止缓存代理误升级非 WS 请求，确保请求是客户端主动发起的 |
| 101 状态码的含义？ | Switching Protocols，表示服务端同意切换协议 |
| WebSocket 可以跨域吗？ | 可以，浏览器不会对其施加同源策略限制，但服务端应校验 Origin |
| 握手失败的处理方式？ | 服务端返回 4xx 状态码而非 101，客户端 WebSocket.onerror 触发 |

---

### 1.2 帧协议

WebSocket 数据传输以帧（Frame）为单位，帧结构如下：

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-------+-+-------------+-------------------------------+
|F|R|R|R| opcode|M| Payload len |    Extended payload length    |
|I|S|S|S|  (4)  |A|     (7)     |             (16/64)           |
|N|V|V|V|       |S|             |   (if payload len==126/127)   |
| |1|2|3|       |K|             |                               |
+-+-+-+-+-------+-+-------------+ - - - - - - - - - - - - - - -+
|     Extended payload length continued, if payload len == 127  |
+ - - - - - - - - - - - - - - -+-------------------------------+
|                               |Masking-key, if MASK set to 1  |
+-------------------------------+-------------------------------+
| Masking-key (continued)       |          Payload Data         |
+-------------------------------- - - - - - - - - - - - - - - -+
:                     Payload Data continued ...                :
+ - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -+
|                     Payload Data (continued)                  |
+---------------------------------------------------------------+
```

**重要字段：**

| 字段 | 长度 | 说明 |
|------|------|------|
| FIN | 1 bit | 是否为最后一帧（用于分片） |
| RSV1-3 | 各1 bit | 扩展使用，不设置必须为0 |
| Opcode | 4 bits | 帧类型标识 |
| MASK | 1 bit | 是否掩码（客户端->服务端必须为1） |
| Payload Len | 7 bits | 载荷长度（126+2字节扩展，127+8字节扩展） |
| Masking-Key | 32 bits | 掩码密钥（仅MASK=1时存在） |

**Opcode 定义：**

| Opcode | 含义 |
|--------|------|
| 0x0 | 继续帧（分片续传） |
| 0x1 | 文本帧（UTF-8） |
| 0x2 | 二进制帧 |
| 0x8 | 关闭帧（Close Frame） |
| 0x9 | Ping |
| 0xA | Pong |
| 0x3-0x7 | 预留非控制帧 |
| 0xB-0xF | 预留控制帧 |

**掩码（Masking）机制：**

客户端发送到服务端的数据必须掩码，服务端到客户端不需要。掩码使用 XOR 算法：

```
for i := 0; i < len(payload); i++ {
    payload[i] ^= maskingKey[i % 4]
}
```

设计目的：防止早期 HTTP 代理的缓存污染攻击（Cache Poisoning）。通过随机掩码确保攻击者无法构造出可控的HTTP响应。

**Go 帧解包演示：**

```go
package main

import (
    "encoding/binary"
    "errors"
    "io"
)

type Frame struct {
    Fin         bool
    Opcode      byte
    Mask        bool
    MaskingKey  [4]byte
    Payload     []byte
}

func ReadFrame(r io.Reader) (*Frame, error) {
    header := make([]byte, 2)
    if _, err := io.ReadFull(r, header); err != nil {
        return nil, err
    }

    f := &Frame{}
    f.Fin = (header[0] & 0x80) != 0
    f.Opcode = header[0] & 0x0F
    f.Mask = (header[1] & 0x80) != 0

    payloadLen := int64(header[1] & 0x7F)
    switch {
    case payloadLen == 126:
        ext := make([]byte, 2)
        io.ReadFull(r, ext)
        payloadLen = int64(binary.BigEndian.Uint16(ext))
    case payloadLen == 127:
        ext := make([]byte, 8)
        io.ReadFull(r, ext)
        payloadLen = int64(binary.BigEndian.Uint64(ext))
    }

    if f.Mask {
        io.ReadFull(r, f.MaskingKey[:])
    }

    f.Payload = make([]byte, payloadLen)
    io.ReadFull(r, f.Payload)

    if f.Mask {
        for i := 0; i < len(f.Payload); i++ {
            f.Payload[i] ^= f.MaskingKey[i%4]
        }
    }

    return f, nil
}

// 构建帧（服务端到客户端，不掩码）
func WriteFrame(w io.Writer, opcode byte, data []byte) error {
    header := []byte{0x80 | opcode, 0} // FIN + opcode

    if len(data) < 126 {
        header[1] = byte(len(data))
    } else if len(data) < 65536 {
        header[1] = 126
        ext := make([]byte, 2)
        binary.BigEndian.PutUint16(ext, uint16(len(data)))
        header = append(header, ext...)
    } else {
        header[1] = 127
        ext := make([]byte, 8)
        binary.BigEndian.PutUint64(ext, uint64(len(data)))
        header = append(header, ext...)
    }

    if _, err := w.Write(header); err != nil {
        return err
    }
    _, err := w.Write(data)
    return err
}

func main() {
    // 使用示例（略）
    _ = errors.New
    _ = Frame{}
}
```

**PHP Swoole 帧处理：**

```php
<?php
use Swoole\WebSocket\Server;
use Swoole\WebSocket\Frame;

$server = new Server("0.0.0.0", 9502);

// Swoole 默认自动处理帧编解码，以下为底层帧对象操作示例
$server->on("message", function (Server $server, Frame $frame) {
    // Swoole Frame 属性
    $fd = $frame->fd;       // 连接描述符
    $data = $frame->data;   // 解码后的数据
    $opcode = $frame->opcode; // 1=text, 2=binary, 9=ping, 10=pong
    $finish = $frame->finish; // 是否最后一帧

    // 获取原始帧（如有特殊需求）
    // $server->getClientInfo($fd);

    // 发送二进制数据（opcode=2）
    $binaryData = pack("N", 42);
    $server->push($fd, $binaryData, SWOOLE_WEBSOCKET_OPCODE_BINARY);

    // 发送 Ping
    $server->push($fd, "ping", SWOOLE_WEBSOCKET_OPCODE_PING);
});

// Swoole 内置心跳支持
$server->set([
    'heartbeat_idle_time' => 600,   // 最大空闲时间（秒）
    'heartbeat_check_interval' => 60, // 检测间隔
]);
```

**高频面试题：**

| 问题 | 要点 |
|------|------|
| 为什么客户端到服务端必须掩码？ | 防止 HTTP 代理缓存污染攻击，服务端无法伪造 JS 发起的 WebSocket 请求 |
| 为什么要分片（FIN=0 的连续帧）？ | 支持流式传输大消息，避免头部过大影响小消息延迟 |
| Opcode 0x0 何时使用？ | 分片传输时，第一帧指定 opcode，后续帧用 0x0 |
| Payload Length 扩展规则？ | <=125 直接表示；126 表示后跟 2 字节；127 表示后跟 8 字节 |

---

### 1.3 心跳 Ping/Pong

WebSocket 协议内置 Ping/Pong 控制帧，用于检测连接活性。

- Ping 帧：Opcode=0x9，可以带 Application Data
- Pong 帧：Opcode=0xA，必须与收到的 Ping 数据一致（回复相同数据）
- 浏览器 WebSocket API 不暴露 Ping/Pong，由底层自动处理

**Go 心跳实现（gorilla/websocket）：**

```go
package main

import (
    "log"
    "net/http"
    "time"
    "github.com/gorilla/websocket"
)

var upgrader = websocket.Upgrader{
    ReadBufferSize:  4096,
    WriteBufferSize: 4096,
    CheckOrigin: func(r *http.Request) bool {
        return true // 生产环境应校验 Origin
    },
}

func wsHandler(w http.ResponseWriter, r *http.Request) {
    conn, err := upgrader.Upgrade(w, r, nil)
    if err != nil {
        log.Printf("Upgrade failed: %v", err)
        return
    }
    defer conn.Close()

    // 设置读写超时
    conn.SetReadDeadline(time.Now().Add(60 * time.Second))

    // 设置 Pong 处理器（自动回复由协议层处理，这里只需更新 deadline）
    conn.SetPongHandler(func(appData string) error {
        conn.SetReadDeadline(time.Now().Add(60 * time.Second))
        log.Printf("收到 pong: %s", appData)
        return nil
    })

    // 启动协程发送 Ping
    ticker := time.NewTicker(30 * time.Second)
    defer ticker.Stop()

    go func() {
        for range ticker.C {
            if err := conn.WriteMessage(websocket.PingMessage, []byte("ping")); err != nil {
                log.Printf("ping 失败: %v", err)
                return
            }
        }
    }()

    // 主读循环
    for {
        _, msg, err := conn.ReadMessage()
        if err != nil {
            if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
                log.Printf("读取错误: %v", err)
            }
            break
        }
        log.Printf("收到: %s", msg)
    }
}

func main() {
    http.HandleFunc("/ws", wsHandler)
    log.Fatal(http.ListenAndServe(":8080", nil))
}
```

**PHP Swoole 心跳机制：**

```php
<?php
use Swoole\WebSocket\Server;

$server = new Server("0.0.0.0", 9503);

// 方式一：Swoole 内置心跳
$server->set([
    'heartbeat_idle_time' => 120,       // 超过 120 秒无数据视为死连
    'heartbeat_check_interval' => 30,   // 每 30 秒检查一次
]);

// 方式二：自定义心跳（更灵活）
$server->on("open", function (Server $server, $request) {
    // 记录连接时间
    $server->fdTable[$request->fd] = time();
});

$server->on("message", function (Server $server, $frame) {
    if ($frame->data === "pong") {
        // 更新活跃时间（忽略业务消息由 swoole 的定时器处理）
        return;
    }

    // 给客户端发送 ping
    $server->push($frame->fd, "ping", SWOOLE_WEBSOCKET_OPCODE_PING);
});

// 定时器检测死连
$server->tick(30000, function () use ($server) {
    $now = time();
    foreach ($server->connections as $fd) {
        $connInfo = $server->getClientInfo($fd);
        if ($connInfo && ($now - $connInfo['last_time']) > 120) {
            $server->push($fd, "心跳超时，即将断开");
            $server->disconnect($fd, 1000, "心跳超时");
        }
    }
});

$server->on("close", function (Server $server, $fd) {
    unset($server->fdTable[$fd]);
});

$server->start();
```

**Go 心跳实现（nhooyr.io/websocket，推荐的 gorilla 替代）：**

```go
package main

import (
    "context"
    "log"
    "net/http"
    "time"
    "nhooyr.io/websocket"
)

func wsHandler(w http.ResponseWriter, r *http.Request) {
    conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{
        InsecureSkipVerify: true,
    })
    if err != nil {
        log.Printf("accept: %v", err)
        return
    }
    defer conn.Close(websocket.StatusNormalClosure, "bye")

    ctx, cancel := context.WithCancel(r.Context())
    defer cancel()

    // 30 秒心跳
    ticker := time.NewTicker(30 * time.Second)
    defer ticker.Stop()

    go func() {
        for range ticker.C {
            ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
            err := conn.Ping(ctx)
            cancel()
            if err != nil {
                log.Printf("ping error: %v", err)
                return
            }
        }
    }()

    for {
        _, msg, err := conn.Read(ctx)
        if err != nil {
            log.Printf("read error: %v", err)
            break
        }
        log.Printf("收到: %s", string(msg))
    }
}
```

**高频面试题：**

| 问题 | 要点 |
|------|------|
| 心跳与 TCP Keep-Alive 的区别？ | TCP KA 由系统层发送，时间粒度过粗（默认2小时），无法在应用层感知 |
| 心跳间隔如何设置？ | 一般 25-60 秒，需平衡网络流量与及时性；考虑 NAT 超时（通常 5 分钟） |
| Pong 不回应该如何处理？ | 连续 2-3 次无响应则判定连接失效，触发重连 |
| 心跳与消息复用？ | 高流量场景可将心跳与消息合并，避免额外帧的开销 |

---

### 1.4 关闭握手 Close Frame

WebSocket 关闭握手是一个协作过程，由 Close Frame（Opcode=0x8）完成。

**关闭流程：**

1. A 发送 Close Frame（可包含状态码和原因）
2. B 收到后发送 Close Frame 作为响应
3. TCP 连接随后关闭

**状态码：**

| 状态码 | 含义 |
|--------|------|
| 1000 | 正常关闭（Normal Closure） |
| 1001 | 端点离开（Going Away） |
| 1002 | 协议错误（Protocol Error） |
| 1003 | 不支持的数据类型（Unsupported Data） |
| 1005 | 未收到状态码（保留） |
| 1006 | 异常关闭（保留） |
| 1007 | 数据不一致（Invalid Frame Payload Data） |
| 1008 | 策略违规（Policy Violation） |
| 1009 | 消息过大（Message Too Big） |
| 1010 | 缺少扩展（Mandatory Extension） |
| 1011 | 服务器内部错误（Internal Error） |
| 1012-1014 | 预留 |
| 1015 | TLS 握手失败（保留） |
| 4000-4999 | 应用自定义 |

**最佳实践：**

```php
// PHP Swoole 关闭处理
$server->on("close", function (Server $server, $fd, $reactorId) {
    $info = $server->getClientInfo($fd);
    $closeCode = $info['close_code'] ?? 1000;
    $closeReason = $info['close_reason'] ?? '';

    echo "连接 {$fd} 关闭, 代码: {$closeCode}, 原因: {$closeReason}\n";
    // 清理会话数据
    SessionManager::remove($fd);
});

// 主动关闭连接
$server->disconnect($fd, 1001, "服务重启");
```

```go
// Go 主动关闭
conn.WriteMessage(
    websocket.CloseMessage,
    websocket.FormatCloseMessage(websocket.CloseGoingAway, "server shutdown"),
)
// 或
conn.Close()
// nhooyr.io/websocket
conn.Close(websocket.StatusGoingAway, "server shutdown")
```

**高频面试题：**

| 问题 | 要点 |
|------|------|
| 1005 和 1006 的特殊性？ | 不能显式发送，只能出现在协议层—1005 表示没有状态码帧，1006 表示连接意外断开 |
| 被动断开的检测？ | 心跳超时 + 读错误（EOF/ECONNRESET） |
| 半开连接的处理？ | 心跳机制 + TCP Keep-Alive（SO_KEEPALIVE）|

---

### 1.5 WebSocket 与 HTTP/2、HTTP/3 的关系

**HTTP/2：**

- HTTP/2 的多路复用并不适合 WebSocket，因为 WebSocket 是单流、全双工的
- HTTP/2 定义了自己的 WebSocket 桥接机制（RFC 8441）：通过 `CONNECT` 方法在 HTTP/2 流上建立 WebSocket
- 浏览器已支持 h2 WebSocket（HTTP/2 之上的 WS）

```
:method = CONNECT
:protocol = websocket
:scheme = https
:path = /chat
sec-websocket-version = 13
sec-websocket-key = ...
```

**HTTP/3 (QUIC)：**

- HTTP/3 基于 QUIC（UDP），天然解决队头阻塞问题
- WebSocket 可以通过 QUIC 流传输，获得更低延迟
- WebTransport（详见第 8 节）是基于 QUIC 的下一代方案，但 WebSocket 短期内仍是主流

**兼容性矩阵：**

| 协议 | 传输层 | 多路复用 | WebSocket 支持 |
|------|--------|----------|----------------|
| HTTP/1.1 | TCP | 否 | 原生支持 |
| HTTP/2 | TCP | 是 | CONNECT 桥接（RFC 8441）|
| HTTP/3 | QUIC (UDP) | 是 | CONNECT 桥接（试验阶段） |

---

## 2. 服务端实现

### 2.1 PHP Swoole/Swow WebSocket Server

**Swoole 完整示例：**

```php
<?php
use Swoole\WebSocket\Server;
use Swoole\Http\Request;
use Swoole\Table;

// 创建内存表存储连接映射
$fdTable = new Table(1024);
$fdTable->column('uid', Table::TYPE_INT, 8);
$fdTable->column('room_id', Table::TYPE_INT, 8);
$fdTable->column('last_heartbeat', Table::TYPE_INT, 8);
$fdTable->create();

$server = new Server("0.0.0.0", 9501);

$server->set([
    'worker_num' => 4,                 // 工作进程数
    'task_worker_num' => 2,            // 异步任务进程
    'heartbeat_idle_time' => 120,
    'heartbeat_check_interval' => 30,
    'log_file' => '/tmp/swoole_ws.log',
    'open_websocket_close_frame' => true, // 接收关闭帧
    'open_websocket_ping_frame' => true,  // 接收 ping 帧
    'open_websocket_pong_frame' => true,  // 接收 pong 帧
]);

// 连接路由
$server->on("open", function (Server $server, Request $request) use ($fdTable) {
    $uid = (int)($request->get['uid'] ?? 0);
    $roomId = (int)($request->get['room_id'] ?? 0);

    if ($uid <= 0) {
        $server->disconnect($request->fd, 4001, "Invalid UID");
        return;
    }

    $fdTable->set($request->fd, [
        'uid' => $uid,
        'room_id' => $roomId,
        'last_heartbeat' => time(),
    ]);

    // 添加到房间群组
    if ($roomId > 0) {
        $server->bind($request->fd, $roomId);
    }

    $server->push($request->fd, json_encode([
        'type' => 'welcome',
        'fd' => $request->fd,
        'time' => time(),
    ]));
});

// 消息路由
$server->on("message", function (Server $server, $frame) use ($fdTable) {
    $data = json_decode($frame->data, true);
    if (!$data) {
        $server->push($frame->fd, json_encode(['error' => 'invalid json']));
        return;
    }

    $fdTable->incr($frame->fd, 'last_heartbeat', 0);
    $fdTable->set($frame->fd, ['last_heartbeat' => time()]);

    switch ($data['type'] ?? '') {
        case 'chat':
            // 群聊消息
            $roomId = $fdTable->get($frame->fd, 'room_id');
            $msg = json_encode([
                'type' => 'chat',
                'from_uid' => $fdTable->get($frame->fd, 'uid'),
                'message' => $data['message'],
                'time' => time(),
            ]);
            foreach ($server->connections as $fd) {
                if ($fdTable->get($fd, 'room_id') === $roomId) {
                    $server->push($fd, $msg);
                }
            }
            break;

        case 'ping':
            $server->push($frame->fd, json_encode(['type' => 'pong']));
            break;

        default:
            // 投递到 Task 进程处理耗时任务
            $server->task([
                'fd' => $frame->fd,
                'data' => $data,
            ]);
    }
});

// 异步任务处理
$server->on("task", function (Server $server, $taskId, $workerId, $data) {
    // 耗时处理（如 AI 推理、消息转发、持久化）
    $result = processMessage($data);
    $server->push($data['fd'], json_encode($result));
    return true;
});

$server->on("finish", function (Server $server, $taskId, $data) {
    // 任务完成回调
});

$server->on("close", function (Server $server, $fd) use ($fdTable) {
    $fdTable->del($fd);
});

$server->start();
```

**Swow（Swoole 的现代替代）示例：**

```php
<?php
use Swow\WebSocket\WebSocket;
use Swow\Psr7\Server\Server;

$server = new Server();
$server->bind("0.0.0.0", 9502);

while (true) {
    $connection = $server->accept();
    // 每个连接一个协程
    $connection->upgrade();

    $query = $connection->getRequest()->getUri()->getQuery();
    parse_str($query, $params);

    // 鉴权
    if (empty($params['token'])) {
        $connection->close();
        continue;
    }

    $connection->send("欢迎连接 Swow!");

    // 消息循环
    while (true) {
        try {
            $frame = $connection->recv();
            if ($frame->getOpcode() === WebSocket::OPCODE_PING) {
                $connection->pong();
                continue;
            }
            $connection->send("收到: " . $frame->getData());
        } catch (\Swow\Socket\Exception $e) {
            break;
        }
    }
}
```

---

### 2.2 Go gorilla/websocket + nhooyr.io/websocket

**gorilla/websocket（最广泛使用的库，注意已归档但功能稳定）：**

```go
package main

import (
    "encoding/json"
    "log"
    "net/http"
    "sync"
    "time"
    "github.com/gorilla/websocket"
)

type Client struct {
    conn *websocket.Conn
    uid  int64
    send chan []byte
}

type Hub struct {
    sync.RWMutex
    clients map[int64]*Client
    rooms   map[int64]map[int64]*Client // roomId -> uid -> Client
}

var hub = &Hub{
    clients: make(map[int64]*Client),
    rooms:   make(map[int64]map[int64]*Client),
}

var upgrader = websocket.Upgrader{
    ReadBufferSize:   4096,
    WriteBufferSize:  4096,
    HandshakeTimeout: 5 * time.Second,
    CheckOrigin: func(r *http.Request) bool {
        return true
    },
}

func (h *Hub) Register(client *Client) {
    h.Lock()
    defer h.Unlock()
    h.clients[client.uid] = client
}

func (h *Hub) Unregister(client *Client) {
    h.Lock()
    defer h.Unlock()
    delete(h.clients, client.uid)
    for _, room := range h.rooms {
        delete(room, client.uid)
    }
}

func (h *Hub) SendToUser(uid int64, msg []byte) bool {
    h.RLock()
    defer h.RUnlock()
    if client, ok := h.clients[uid]; ok {
        select {
        case client.send <- msg:
            return true
        default:
            // 发送缓冲区满，丢弃
            return false
        }
    }
    return false
}

func (h *Hub) BroadcastToRoom(roomId int64, msg []byte) {
    h.RLock()
    defer h.RUnlock()
    if room, ok := h.rooms[roomId]; ok {
        for _, client := range room {
            select {
            case client.send <- msg:
            default:
            }
        }
    }
}

// 读协程
func (c *Client) readPump() {
    defer func() {
        hub.Unregister(c)
        c.conn.Close()
    }()

    c.conn.SetReadLimit(4096) // 限制最大消息大小
    c.conn.SetReadDeadline(time.Now().Add(60 * time.Second))
    c.conn.SetPongHandler(func(string) error {
        c.conn.SetReadDeadline(time.Now().Add(60 * time.Second))
        return nil
    })

    for {
        _, msg, err := c.conn.ReadMessage()
        if err != nil {
            if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
                log.Printf("read error: %v", err)
            }
            break
        }

        // 消息路由
        var req map[string]interface{}
        if err := json.Unmarshal(msg, &req); err != nil {
            continue
        }

        switch req["type"] {
        case "chat":
            roomId := int64(req["room_id"].(float64))
            msgBytes, _ := json.Marshal(map[string]interface{}{
                "type": "chat",
                "from_uid": c.uid,
                "message": req["message"],
                "time": time.Now().Unix(),
            })
            hub.BroadcastToRoom(roomId, msgBytes)
        }
    }
}

// 写协程
func (c *Client) writePump() {
    ticker := time.NewTicker(30 * time.Second)
    defer func() {
        ticker.Stop()
        c.conn.Close()
    }()

    for {
        select {
        case msg, ok := <-c.send:
            if !ok {
                c.conn.WriteMessage(websocket.CloseMessage, []byte{})
                return
            }
            c.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
            if err := c.conn.WriteMessage(websocket.TextMessage, msg); err != nil {
                return
            }
        case <-ticker.C:
            c.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
            if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
                return
            }
        }
    }
}

func wsHandler(w http.ResponseWriter, r *http.Request) {
    uid := int64(r.URL.Query().Get("uid"))
    if uid == 0 {
        http.Error(w, "unauthorized", 401)
        return
    }

    conn, err := upgrader.Upgrade(w, r, nil)
    if err != nil {
        log.Printf("upgrade error: %v", err)
        return
    }

    client := &Client{
        conn: conn,
        uid:  uid,
        send: make(chan []byte, 256),
    }
    hub.Register(client)

    go client.writePump()
    go client.readPump()
}

func main() {
    http.HandleFunc("/ws", wsHandler)
    log.Fatal(http.ListenAndServe(":8080", nil))
}
```

**nhooyr.io/websocket（现代替代，支持 context、并发安全、更简洁）：**

```go
package main

import (
    "context"
    "encoding/json"
    "log"
    "net/http"
    "nhooyr.io/websocket"
    "nhooyr.io/websocket/wsjson"
)

func wsHandler(w http.ResponseWriter, r *http.Request) {
    conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{
        InsecureSkipVerify: true,
        Subprotocols:       []string{"chat"},
    })
    if err != nil {
        log.Printf("accept: %v", err)
        return
    }
    defer conn.Close(websocket.StatusInternalError, "connection closed")

    ctx, cancel := context.WithCancel(r.Context())
    defer cancel()

    // 消息循环
    for {
        var msg map[string]interface{}
        err := wsjson.Read(ctx, conn, &msg)
        if err != nil {
            log.Printf("read: %v", err)
            break
        }

        // 回复
        response := map[string]interface{}{
            "type": "echo",
            "data": msg,
        }
        if err := wsjson.Write(ctx, conn, response); err != nil {
            log.Printf("write: %v", err)
            break
        }
    }
}

func main() {
    http.HandleFunc("/ws", wsHandler)
    log.Fatal(http.ListenAndServe(":8081", nil))
}
```

**nhooyr vs gorilla 对比：**

| 特性 | gorilla/websocket | nhooyr.io/websocket |
|------|-------------------|---------------------|
| 维护状态 | 归档（只读） | 活跃维护 |
| API 风格 | 回调式 | Context 驱动 |
| 并发安全 | 读写需自行同步 | 内置支持 |
| 性能 | 优秀 | 更优（零分配读路径）|
| 子协议 | 支持 | 支持 |
| 自定义框架 | 更多选择 | 需要手动拼接 |

---

### 2.3 Node.js ws / Socket.IO

**ws 库（底层高性能库）：**

```javascript
const WebSocket = require('ws');
const http = require('http');
const url = require('url');

const server = http.createServer();
const wss = new WebSocket.Server({ server, maxPayload: 1024 * 1024 });

// 连接状态管理
const clients = new Map();

wss.on('connection', (ws, req) => {
    const params = url.parse(req.url, true).query;
    const uid = params.uid;

    clients.set(uid, ws);

    // 心跳
    ws.isAlive = true;
    ws.on('pong', () => { ws.isAlive = true; });

    ws.on('message', (data) => {
        try {
            const msg = JSON.parse(data);
            // 消息路由
            handleMessage(uid, msg);
        } catch (e) {
            ws.send(JSON.stringify({ error: 'invalid message' }));
        }
    });

    ws.on('close', () => {
        clients.delete(uid);
    });
});

// 心跳检测定时器
const interval = setInterval(() => {
    wss.clients.forEach((ws) => {
        if (ws.isAlive === false) return ws.terminate();
        ws.isAlive = false;
        ws.ping();
    });
}, 30000);

wss.on('close', () => clearInterval(interval));

server.listen(8080);
```

**Socket.IO（提供自动重连、房间、ACK、回退等高级功能）：**

```javascript
const io = require('socket.io')({
    transports: ['websocket', 'polling'], // 首选 WS，兼容长轮询
    pingInterval: 25000,
    pingTimeout: 20000,
});

io.use((socket, next) => {
    const token = socket.handshake.auth.token;
    jwt.verify(token, process.env.JWT_SECRET, (err, decoded) => {
        if (err) return next(new Error('auth error'));
        socket.userId = decoded.uid;
        next();
    });
});

io.on('connection', (socket) => {
    socket.join(`user:${socket.userId}`);

    socket.on('chat', (data, ack) => {
        // ack 函数实现消息确认
        const msg = saveMessage(data);
        io.to(`room:${data.roomId}`).emit('chat', msg);
        ack?.({ status: 'ok', msgId: msg.id });
    });

    socket.on('disconnect', (reason) => { /* cleanup */ });
});
```

**高频面试题：**

| 问题 | 要点 |
|------|------|
| WebSocket 和 Socket.IO 的关系？ | Socket.IO 基于 WS 封装，提供回退、重连、房间、ACK 等上层能力 |
| 为什么要用 go 的 nhooyr 替代 gorilla？ | gorilla 已归档，nhooyr 有 context 支持、并发安全、更优性能 |
| Swoole 的 worker_num 如何设置？ | 一般设为 CPU 核心数 1-2 倍，I/O 密集可更大 |
| Node.js 事件循环对 WS 的影响？ | 避免阻塞事件循环（CPU 密集任务使用 worker_threads 或拆分） |

---

### 2.4 连接管理架构

**三种管理模式：**

#### 2.4.1 注册中心（Registry）

维护全局 `fd -> 用户信息` 映射，支持查询、删除、批量操作。

```go
type ConnectionRegistry struct {
    mu       sync.RWMutex
    conns    map[string]*Connection  // connectionId -> Connection
    userConn map[string]map[string]bool // userId -> set of connectionIds
}

func (r *ConnectionRegistry) Register(conn *Connection) {
    r.mu.Lock()
    defer r.mu.Unlock()
    r.conns[conn.ID] = conn
    if _, ok := r.userConn[conn.UserID]; !ok {
        r.userConn[conn.UserID] = make(map[string]bool)
    }
    r.userConn[conn.UserID][conn.ID] = true
}

func (r *ConnectionRegistry) GetUserConnections(userID string) []*Connection {
    r.mu.RLock()
    defer r.mu.RUnlock()
    var result []*Connection
    for id := range r.userConn[userID] {
        if conn, ok := r.conns[id]; ok {
            result = append(result, conn)
        }
    }
    return result
}

func (r *ConnectionRegistry) Unregister(connID string) {
    r.mu.Lock()
    defer r.mu.Unlock()
    if conn, ok := r.conns[connID]; ok {
        delete(r.userConn[conn.UserID], connID)
        if len(r.userConn[conn.UserID]) == 0 {
            delete(r.userConn, conn.UserID)
        }
        delete(r.conns, connID)
    }
}
```

#### 2.4.2 连接池（Connection Pool）

控制服务端同时维持的连接数上限，防止资源耗尽。

```go
type ConnPool struct {
    sem      chan struct{} // 信号量
    maxConns int
}

func NewConnPool(maxConns int) *ConnPool {
    return &ConnPool{
        sem:      make(chan struct{}, maxConns),
        maxConns: maxConns,
    }
}

func (p *ConnPool) Acquire() bool {
    select {
    case p.sem <- struct{}{}:
        return true
    default:
        return false // 达到连接上限
    }
}

func (p *ConnPool) Release() {
    <-p.sem
}
```

#### 2.4.3 连接路由（Connection Router）

根据消息类型将不同的消息分发到对应的处理 Handler。

```go
type MessageHandler func(client *Client, msg []byte) error

type Router struct {
    handlers map[string]MessageHandler
}

func NewRouter() *Router {
    return &Router{
        handlers: make(map[string]MessageHandler),
    }
}

func (r *Router) Handle(msgType string, handler MessageHandler) {
    r.handlers[msgType] = handler
}

func (r *Router) Dispatch(client *Client, raw []byte) error {
    var envelope struct {
        Type string `json:"type"`
    }
    if err := json.Unmarshal(raw, &envelope); err != nil {
        return err
    }
    if handler, ok := r.handlers[envelope.Type]; ok {
        return handler(client, raw)
    }
    return fmt.Errorf("unknown message type: %s", envelope.Type)
}

// 初始化路由
func initRouter() *Router {
    r := NewRouter()
    r.Handle("chat", handleChat)
    r.Handle("join", handleJoinRoom)
    r.Handle("leave", handleLeaveRoom)
    r.Handle("typing", handleTyping)
    return r
}
```

---

## 3. 分布式 WebSocket 架构

### 3.1 架构总览

单机 WebSocket 无法支撑大规模连接，分布式架构将连接分散到多个节点：

```
                    ┌────────────────────────┐
                    │     负载均衡器/LB       │
                    │  (LVS / Nginx / HAProxy)│
                    │  Layer-4 TCP 代理       │
                    └────────┬───────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
        ┌─────▼────┐  ┌─────▼────┐  ┌─────▼────┐
        │ WS Node1 │  │ WS Node2 │  │ WS Node3 │
        │ Gateway  │  │ Gateway  │  │ Gateway  │
        └────┬─────┘  └────┬─────┘  └────┬─────┘
             │             │             │
             └─────────────┼─────────────┘
                           │
                    ┌──────▼──────┐
                    │   消息总线   │
                    │ Redis Pub/Sub│
                    │  / Kafka    │
                    └─────────────┘
                           │
                    ┌──────▼──────┐
                    │  业务服务    │
                    │ (HTTP/RPC)  │
                    └─────────────┘
```

### 3.2 网关层统一接入

**Nginx 反向代理配置（四层 TCP 代理 + 可选七层）：**

```nginx
# 四层 TCP 代理 — 性能最优，适合 WebSocket
stream {
    upstream ws_backend {
        hash $remote_addr consistent;  # 一致性哈希保持会话
        server 10.0.1.1:9501 weight=5;
        server 10.0.1.2:9501 weight=5;
        server 10.0.1.3:9501 weight=5;
    }

    server {
        listen 8080;
        proxy_pass ws_backend;
        proxy_connect_timeout 5s;
        proxy_timeout 3600s;       # WebSocket 长连接超时
    }
}

# 七层 HTTP 代理（支持协议切换，可用于 URL 路由）
http {
    map $http_upgrade $connection_upgrade {
        default upgrade;
        '' close;
    }

    upstream ws_http_backend {
        server 10.0.1.1:9501;
        server 10.0.1.2:9501;
    }

    server {
        listen 443 ssl;
        server_name ws.example.com;

        ssl_certificate /etc/ssl/certs/example.crt;
        ssl_certificate_key /etc/ssl/private/example.key;

        location /ws/ {
            proxy_pass http://ws_http_backend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
        }
    }
}
```

**Go 网关层实现（消息桥接 + 连接管理）：**

```go
package main

import (
    "context"
    "encoding/json"
    "log"
    "net/http"
    "sync"
    "time"
    "github.com/go-redis/redis/v8"
    "github.com/gorilla/websocket"
)

type Gateway struct {
    nodeID       string
    redisClient  *redis.Client
    upgrader     websocket.Upgrader
    connections  sync.Map // fd -> *Client
    userConns    sync.Map // uid -> set of fd
}

func NewGateway(nodeID string, redisAddr string) *Gateway {
    return &Gateway{
        nodeID: nodeID,
        redisClient: redis.NewClient(&redis.Options{
            Addr: redisAddr,
        }),
        upgrader: websocket.Upgrader{
            ReadBufferSize:  4096,
            WriteBufferSize: 4096,
            CheckOrigin:     func(r *http.Request) bool { return true },
        },
    }
}

func (g *Gateway) Start(ctx context.Context) {
    // 订阅 Redis 频道，接收跨节点消息
    pubsub := g.redisClient.Subscribe(ctx, "ws:messages")
    go g.listenRedis(ctx, pubsub)

    http.HandleFunc("/ws", g.wsHandler)
    go http.ListenAndServe(":8080", nil)
}

func (g *Gateway) listenRedis(ctx context.Context, pubsub *redis.PubSub) {
    ch := pubsub.Channel()
    for msg := range ch {
        var envelope struct {
            Type   string          `json:"type"`
            ToUID  []int64         `json:"to_uids"`
            Payload json.RawMessage `json:"payload"`
        }
        json.Unmarshal([]byte(msg.Payload), &envelope)

        // 查找本节点上的目标连接并投递
        for _, uid := range envelope.ToUID {
            if fds, ok := g.userConns.Load(uid); ok {
                // 遍历该用户的所有连接（多设备）
                // ...
            }
        }
    }
}

func (g *Gateway) PublishToUser(ctx context.Context, uid int64, msg []byte) {
    data, _ := json.Marshal(map[string]interface{}{
        "type": "direct",
        "to_uids": []int64{uid},
        "payload": msg,
    })
    g.redisClient.Publish(ctx, "ws:messages", string(data))
}
```

---

### 3.3 连接路由与迁移

**连接迁移流程：当用户断线重连到不同节点时：**

```
1. 用户连接到 Node B（与原 Node A 不同）
2. Node B 查询 Redis Session，发现该用户之前由 Node A 服务
3. Node B 发送 Redis消息「连接迁移通知」给 Node A
4. Node A 清理本地连接状态，转发未投递消息
5. Node B 绑定 Session 到本节点
6. 通知业务层连接节点已变更
```

**Go 连接迁移核心逻辑：**

```go
func (g *Gateway) handleReconnect(ctx context.Context, uid int64, newConn *websocket.Conn) error {
    sessionKey := fmt.Sprintf("ws:session:%d", uid)
    oldNode, err := g.redisClient.Get(ctx, sessionKey).Result()
    if err == redis.Nil {
        // 全新连接
        g.redisClient.Set(ctx, sessionKey, g.nodeID, 24*time.Hour)
        return nil
    }

    if oldNode != g.nodeID {
        // 跨节点迁移 — 通知旧节点清理
        migrationMsg, _ := json.Marshal(map[string]interface{}{
            "type": "session_migrate",
            "uid":  uid,
            "new_node": g.nodeID,
        })
        g.redisClient.Publish(ctx, "ws:messages", string(migrationMsg))

        // 更新会话记录
        g.redisClient.Set(ctx, sessionKey, g.nodeID, 24*time.Hour)
    }

    return nil
}

// 旧节点监听迁移通知并清理
func (g *Gateway) handleMigration(ctx context.Context, msg map[string]interface{}) {
    uid := int64(msg["uid"].(float64))
    g.userConns.Delete(uid)

    // 清理本地连接
    g.connections.Range(func(key, value interface{}) bool {
        client := value.(*Client)
        if client.UID == uid {
            g.connections.Delete(key)
        }
        return true
    })

    // 转发待处理消息
    pendingKey := fmt.Sprintf("ws:pending:%d", uid)
    pendingMsgs, _ := g.redisClient.LRange(ctx, pendingKey, 0, -1).Result()
    for _, msg := range pendingMsgs {
        g.redisClient.Publish(ctx, "ws:messages", msg)
    }
    g.redisClient.Del(ctx, pendingKey)
}
```

---

### 3.4 消息广播 Pub/Sub + Redis/Kafka

#### Redis Pub/Sub 方案

```go
// Go — Redis Pub/Sub 广播
type MessageBroker struct {
    redis *redis.Client
    pub   string // 发布频道
}

func NewMessageBroker(addr string) *MessageBroker {
    return &MessageBroker{
        redis: redis.NewClient(&redis.Options{Addr: addr}),
        pub:   "ws:pubsub",
    }
}

func (b *MessageBroker) Publish(ctx context.Context, msg interface{}) error {
    data, err := json.Marshal(msg)
    if err != nil {
        return err
    }
    return b.redis.Publish(ctx, b.pub, string(data)).Err()
}

func (b *MessageBroker) Subscribe(ctx context.Context) *redis.PubSub {
    return b.redis.Subscribe(ctx, b.pub)
}
```

#### Kafka 方案（更强持久化、回溯能力）

```go
// Go — Kafka 广播（使用 sarama）
import "github.com/IBM/sarama"

type KafkaBroker struct {
    producer sarama.SyncProducer
    topic    string
}

func NewKafkaBroker(brokers []string, topic string) *KafkaBroker {
    config := sarama.NewConfig()
    config.Producer.RequiredAcks = sarama.WaitForLocal  // 至少等待 leader ack
    config.Producer.Return.Successes = true
    config.Producer.Partitioner = sarama.NewHashPartitioner // uid hash 分区

    producer, _ := sarama.NewSyncProducer(brokers, config)
    return &KafkaBroker{
        producer: producer,
        topic:    topic,
    }
}

func (b *KafkaBroker) Publish(ctx context.Context, key string, msg []byte) error {
    _, _, err := b.producer.SendMessage(&sarama.ProducerMessage{
        Topic: b.topic,
        Key:   sarama.StringEncoder(key),
        Value: sarama.ByteEncoder(msg),
    })
    return err
}

// 消费者 — 每个 WS 节点一批消费者
func (b *KafkaBroker) Consume(ctx context.Context, groupID string, handler func([]byte) error) {
    config := sarama.NewConfig()
    config.Consumer.Group.Rebalance.Strategy = sarama.BalanceStrategyRange
    config.Consumer.Offsets.Initial = sarama.OffsetNewest

    consumer := sarama.NewConsumerGroupFromClient(groupID, config)
    for {
        consumer.Consume(ctx, []string{b.topic}, &msgHandler{handler: handler})
        if ctx.Err() != nil {
            break
        }
    }
}
```

**PHP Swoole + Redis Pub/Sub：**

```php
<?php
use Swoole\WebSocket\Server;
use Swoole\Coroutine\Redis;

$server = new Server("0.0.0.0", 9501);

$server->on("start", function (Server $server) {
    // 启动一个协程订阅 Redis 频道
    go(function () use ($server) {
        $redis = new Redis();
        $redis->connect('127.0.0.1', 6379);
        $redis->subscribe(['ws:messages'], function ($redis, $channel, $message) use ($server) {
            $data = json_decode($message, true);
            if (isset($data['to_fd'])) {
                // 直接投递到目标连接
                if ($server->exists($data['to_fd'])) {
                    $server->push($data['to_fd'], $data['payload']);
                }
            } elseif (isset($data['to_room'])) {
                // 广播到房间
                foreach ($server->connections as $fd) {
                    if ($server->getClientInfo($fd)['room_id'] ?? 0 === $data['to_room']) {
                        $server->push($fd, $data['payload']);
                    }
                }
            }
        });
    });
});

// 向其他节点发送消息
function broadcastToAllNodes(Server $server, array $message, array $targetFds) {
    $redis = new Redis();
    $redis->connect('127.0.0.1', 6379);
    $redis->publish('ws:messages', json_encode([
        'to_fds' => $targetFds,
        'payload' => json_encode($message),
    ]));
    $redis->close();
}
```

**高频面试题：**

| 问题 | 要点 |
|------|------|
| Redis Pub/Sub vs Kafka 做消息分发？ | Redis Pub/Sub: 简单、低延迟，但消息无持久化、消费端离线丢失；Kafka：高吞吐、可回溯、持久化，运维成本高 |
| 连接迁移的时机？ | 用户断线重连到不同节点时，通过 session key 定位旧节点并触发清理 + 消息转发 |
| 用户多设备登录如何处理？ | 支持一个 uid 对应多个 fd（多设备），消息按设备推送 |
| sticky session 和一致性哈希的取舍？ | Sticky Session：LB 层面保持，简单但扩缩容导致大量迁移；一致性哈希：分布均匀、迁移量少，需客户端支持 hash 路由 |

---

### 3.5 跨节点消息投递

**跨节点投递方案对比：**

| 方案 | 延迟 | 吞吐 | 一致性 | 运维 |
|------|------|------|--------|------|
| Redis Pub/Sub | 1-3ms | 10K/s | 最终 | 低 |
| Kafka | 5-20ms | 100K+/s | 分区有序 | 中 |
| gRPC Stream | 0.5-2ms | 50K/s | 强 | 中 |
| RabbitMQ | 2-10ms | 20K/s | 可选 | 中 |

**gRPC 点对点直投（Peer-to-Peer）：**

```protobuf
// proto/wsrelay.proto
service WsRelay {
    rpc RelayMessage(RelayRequest) returns (RelayResponse);
    rpc BatchRelay(stream RelayRequest) returns (RelayResponse);
    rpc ConnectionMigrate(MigrateRequest) returns (MigrateResponse);
}

message RelayRequest {
    string from_node = 1;
    int64 to_uid = 2;
    bytes payload = 3;
    bool require_ack = 4;
    map<string, string> metadata = 5;
}

message RelayResponse {
    bool delivered = 1;
    string error = 2;
}
```

```go
// Go gRPC 客户端 — 节点间直投
func (n *Node) sendToPeerNode(peerNode string, msg *RelayRequest) error {
    conn, err := grpc.Dial(peerNode,
        grpc.WithInsecure(),
        grpc.WithDefaultCallOptions(grpc.MaxCallRecvMsgSize(1024*1024)),
    )
    if err != nil {
        return err
    }
    defer conn.Close()

    client := pb.NewWsRelayClient(conn)
    ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
    defer cancel()

    resp, err := client.RelayMessage(ctx, msg)
    if err != nil {
        return err
    }
    if !resp.Delivered {
        return fmt.Errorf("not delivered: %s", resp.Error)
    }
    return nil
}

// 节点注册 — 通过服务发现获取所有 WS 节点列表
type NodeRegistry struct {
    etcd  *clientv3.Client
    self  string
}

func NewNodeRegistry(endpoints []string, selfAddr string) *NodeRegistry {
    cli, _ := clientv3.New(clientv3.Config{Endpoints: endpoints})
    return &NodeRegistry{
        etcd:  cli,
        self:  selfAddr,
    }
}

func (r *NodeRegistry) Register() error {
    lease := r.etcd.NewLease()
    grant, _ := lease.Grant(context.TODO(), 10)
    _, err := r.etcd.Put(context.TODO(), fmt.Sprintf("/ws/nodes/%s", r.self),
        r.self, clientv3.WithLease(grant.ID))
    return err
}

func (r *NodeRegistry) Watch() <-chan []string {
    ch := make(chan []string)
    go func() {
        // 使用 Watch 或定时拉取节点列表
        ticker := time.NewTicker(5 * time.Second)
        for range ticker.C {
            resp, _ := r.etcd.Get(context.TODO(), "/ws/nodes/", clientv3.WithPrefix())
            var nodes []string
            for _, kv := range resp.Kvs {
                nodes = append(nodes, string(kv.Value))
            }
            ch <- nodes
        }
    }()
    return ch
}
```

---

### 3.6 会话保持

**Sticky Session（LB 层保持）：**

```nginx
# Nginx — ip_hash 保持相同 IP 到同一节点
upstream ws_backend {
    ip_hash;
    server 10.0.1.1:9501;
    server 10.0.1.2:9501;
    server 10.0.1.3:9501;
}

# HAProxy — cookie 保持
backend ws_back
    balance roundrobin
    cookie SERVERID insert indirect nocache
    server node1 10.0.1.1:9501 cookie node1 check
    server node2 10.0.1.2:9501 cookie node2 check
```

**一致性哈希（客户端路由）：**

```go
// Go — 一致性哈希节点路由
import "github.com/serialx/hashring"

type WSDispatcher struct {
    ring *hashring.HashRing
}

func NewWSDispatcher(nodes []string) *WSDispatcher {
    return &WSDispatcher{
        ring: hashring.New(nodes),
    }
}

// 根据用户 ID 确定目标节点
func (d *WSDispatcher) GetNode(uid string) (string, bool) {
    return d.ring.GetNode(uid)
}

// 节点弹性扩缩 — 只影响 1/N 的连接
func (d *WSDispatcher) AddNode(node string) {
    d.ring = d.ring.AddNode(node)
}

func (d *WSDispatcher) RemoveNode(node string) {
    d.ring = d.ring.RemoveNode(node)
}
```

---

## 4. 可靠性保障

### 4.1 心跳机制设计

**多层心跳架构：**

```
应用层心跳（Ping/Pong）
    ↑
中间件心跳（Swoole 内置 / LB 健康检查）
    ↑
传输层心跳（TCP Keep-Alive — 系统级）
```

**生产级心跳配置：**

```go
// Go — 应用层 + TCP Keep-Alive 双层心跳
func configureConn(conn *websocket.Conn) {
    // TCP Keep-Alive（系统级，默认2h，这里缩短到60s）
    tcpConn := conn.NetConn()
    if tcpConn != nil {
        rawConn := tcpConn.(*net.TCPConn)
        rawConn.SetKeepAlive(true)
        rawConn.SetKeepAlivePeriod(60 * time.Second)
    }

    // 应用层 Ping
    conn.SetPongHandler(func(appData string) error {
        conn.SetReadDeadline(time.Now().Add(90 * time.Second))
        return nil
    })

    go func() {
        ticker := time.NewTicker(30 * time.Second)
        defer ticker.Stop()
        for range ticker.C {
            conn.SetWriteDeadline(time.Now().Add(5 * time.Second))
            if err := conn.WriteMessage(websocket.PingMessage, nil); err != nil {
                return
            }
        }
    }()
}
```

```php
// PHP Swoole — Timer 自定义心跳
$server->tick(30000, function () use ($server, $redis) {
    $threshold = time() - 120; // 120秒无响应视为离线
    $checkConns = $redis->sMembers("ws:online_users");

    foreach ($checkConns as $uid) {
        $lastHb = $redis->hGet("ws:heartbeat:$uid", "time");
        if ($lastHb && $lastHb < $threshold) {
            // 标记用户离线
            $redis->sRem("ws:online_users", $uid);
            $redis->publish("ws:events", json_encode([
                'type' => 'offline',
                'uid' => $uid,
                'time' => time(),
            ]));
            // 如果该用户有连接，关闭它
            $fd = $redis->hGet("ws:fd_map", $uid);
            if ($fd && $server->exists($fd)) {
                $server->disconnect($fd, 1001, "heartbeat timeout");
            }
        }
    }
});
```

---

### 4.2 断线重连 — 指数退避

**客户端重连策略（JS 示例）：**

```javascript
class ReliableWebSocket {
    constructor(url, options = {}) {
        this.url = url;
        this.reconnect = true;
        this.baseDelay = options.baseDelay || 1000;   // 初始 1s
        this.maxDelay = options.maxDelay || 30000;    // 最大 30s
        this.maxRetries = options.maxRetries || 10;
        this.jitter = options.jitter || 0.3;           // ±30% 随机抖动
        this.retries = 0;

        this.connect();
    }

    connect() {
        this.ws = new WebSocket(this.url);
        this.ws.onopen = () => {
            this.retries = 0;
            this.onopen?.();
        };

        this.ws.onclose = (event) => {
            if (this.reconnect && this.retries < this.maxRetries) {
                const delay = this.calculateDelay();
                setTimeout(() => this.connect(), delay);
            }
        };

        this.ws.onerror = () => {
            // onclose 会随后触发
        };

        this.ws.onmessage = (event) => {
            this.onmessage?.(event);
        };
    }

    calculateDelay() {
        const delay = Math.min(
            this.baseDelay * Math.pow(2, this.retries),
            this.maxDelay
        );
        // 增加随机抖动，避免 thundering herd
        const jitter = delay * this.jitter * (Math.random() * 2 - 1);
        this.retries++;
        return delay + jitter;
    }

    close() {
        this.reconnect = false;
        this.ws.close();
    }
}

// 使用
const ws = new ReliableWebSocket('wss://chat.example.com/ws', {
    baseDelay: 1000,
    maxDelay: 30000,
    maxRetries: 15,
});
```

**服务端支持（续传消息）：**

```php
// PHP — 断线后的消息缓存与重传
$server->on("message", function (Server $server, $frame) use ($redis) {
    $data = json_decode($frame->data, true);

    if ($data['type'] === 'ack') {
        // 客户端确认收到的消息
        $redis->lRem("ws:pending:{$frame->fd}", $data['msg_id'], 1);
        return;
    }

    // 普通消息 — 缓存并等待 ACK
    $msgId = uniqid("msg_", true);
    $redis->rPush("ws:pending:{$frame->fd}", $msgId);

    // 发送消息并附带 msg_id
    $server->push($frame->fd, json_encode([
        'type' => 'message',
        'msg_id' => $msgId,
        'data' => $data['data'],
    ]));
});

// 定时重传未 ACK 消息
$server->tick(10000, function () use ($server, $redis) {
    foreach ($server->connections as $fd) {
        $pending = $redis->lRange("ws:pending:{$fd}", 0, -1);
        foreach ($pending as $msgId) {
            $msgData = $redis->get("ws:msg:{$msgId}");
            if ($msgData) {
                $server->push($fd, $msgData);
            }
        }
    }
});
```

---

### 4.3 消息 ACK 确认与重传

**ACK 确认模型：**

```
Client                  Server
  |                       |
  |---- [msg_id:1] ----->|
  |                       | 处理消息
  |<--- [ack:msg_id:1] --|
  |                       | (清除重传缓存)
  |                       |
  |--- [msg_id:2] ------>|
  |--- [msg_id:2] ------>| (超时未收到 ack，重传)
  |<--- [ack:msg_id:2] --|
```

**Go 实现 ACK 机制：**

```go
type MessageAck struct {
    mu              sync.Mutex
    pending         map[string]*PendingMessage // msgID -> 待确认消息
    maxRetries      int
    retryInterval   time.Duration
    ackChan         chan string // 收到 ack 的 msgID
}

type PendingMessage struct {
    Data     []byte
    Fd       int
    Retries  int
    Created  time.Time
    Stop     chan struct{}
}

func NewMessageAck(maxRetries int, interval time.Duration) *MessageAck {
    return &MessageAck{
        pending:       make(map[string]*PendingMessage),
        maxRetries:    maxRetries,
        retryInterval: interval,
        ackChan:       make(chan string, 1000),
    }
}

func (ma *MessageAck) Add(msgID string, pm *PendingMessage) {
    ma.mu.Lock()
    ma.pending[msgID] = pm
    ma.mu.Unlock()

    go ma.retryLoop(msgID, pm)
}

func (ma *MessageAck) retryLoop(msgID string, pm *PendingMessage) {
    ticker := time.NewTicker(ma.retryInterval)
    defer ticker.Stop()

    for {
        select {
        case <-ticker.C:
            if pm.Retries >= ma.maxRetries {
                ma.mu.Lock()
                delete(ma.pending, msgID)
                ma.mu.Unlock()
                log.Printf("消息 %s 达到最大重试次数，丢弃", msgID)
                return
            }
            pm.Retries++
            // 从连接管理器获取 conn 并重发
            log.Printf("重传消息 %s, 第 %d 次", msgID, pm.Retries)
            // conn.WriteMessage(websocket.TextMessage, pm.Data)

        case <-pm.Stop:
            return
        }
    }
}

func (ma *MessageAck) Ack(msgID string) {
    ma.mu.Lock()
    pm, ok := ma.pending[msgID]
    if ok {
        close(pm.Stop)
        delete(ma.pending, msgID)
    }
    ma.mu.Unlock()
}
```

**高频面试题：**

| 问题 | 要点 |
|------|------|
| 如何保证消息不丢失？ | ACK 确认 + 重传 + 离线消息持久化 + at-least-once 语义 |
| 如何处理消息重复？ | 客户端去重（msg_id 幂等）、服务端幂等校验 |
| 指数退避的 jitter 作用？ | 防止大量客户端同时重连导致的惊群效应（Thundering Herd） |
| 未确认消息的存储？ | Redis List/PendingQueue，Kafka 消费者 offset |

---

### 4.4 Session 持久化与迁移

**Session 数据结构：**

```go
type WSSession struct {
    SessionID    string                 `json:"session_id"`
    UserID       int64                  `json:"user_id"`
    NodeID       string                 `json:"node_id"`
    Fd           int                    `json:"fd"`
    ConnectedAt  int64                  `json:"connected_at"`
    LastActive   int64                  `json:"last_active"`
    Metadata     map[string]interface{} `json:"metadata"`
    DeviceInfo   string                 `json:"device_info"`
    ClientIP     string                 `json:"client_ip"`
    SubProtocols []string               `json:"sub_protocols,omitempty"`
}
```

**Redis Session 存储：**

```go
const (
    SessionKeyPrefix = "ws:session:"
    SessionTTL       = 48 * time.Hour
)

type SessionStore struct {
    redis *redis.Client
}

func (s *SessionStore) SaveSession(ctx context.Context, sess *WSSession) error {
    key := SessionKeyPrefix + strconv.FormatInt(sess.UserID, 10)
    data, _ := json.Marshal(sess)
    return s.redis.Set(ctx, key, string(data), SessionTTL).Err()
}

func (s *SessionStore) GetSession(ctx context.Context, userID int64) (*WSSession, error) {
    key := SessionKeyPrefix + strconv.FormatInt(userID, 10)
    data, err := s.redis.Get(ctx, key).Result()
    if err != nil {
        return nil, err
    }
    var sess WSSession
    json.Unmarshal([]byte(data), &sess)
    return &sess, nil
}

func (s *SessionStore) MigrateSession(ctx context.Context, userID int64, newNodeID string, newFd int) error {
    sess, err := s.GetSession(ctx, userID)
    if err != nil {
        return err
    }
    sess.NodeID = newNodeID
    sess.Fd = newFd
    sess.LastActive = time.Now().Unix()
    return s.SaveSession(ctx, sess)
}
```

**PHP Swoole + Redis Session 持久化：**

```php
<?php
class SessionManager
{
    private static string $prefix = 'ws:session:';
    private static int $ttl = 86400; // 24h

    public static function save(int $fd, array $data): void
    {
        $redis = new Redis();
        $redis->connect('127.0.0.1', 6379);
        $key = self::$prefix . $data['uid'];
        $data['fd'] = $fd;
        $data['node_id'] = gethostname();
        $data['updated_at'] = time();
        $redis->setEx($key, self::$ttl, json_encode($data));
        $redis->close();
    }

    public static function get(int $uid): ?array
    {
        $redis = new Redis();
        $redis->connect('127.0.0.1', 6379);
        $key = self::$prefix . $uid;
        $data = $redis->get($key);
        $redis->close();
        return $data ? json_decode($data, true) : null;
    }

    public static function delete(int $uid): void
    {
        $redis = new Redis();
        $redis->connect('127.0.0.1', 6379);
        $redis->del(self::$prefix . $uid);
        $redis->close();
    }
}

// Swoole 中使用
$server->on("open", function (Server $server, Request $request) {
    SessionManager::save($request->fd, [
        'uid' => $request->get['uid'],
        'room_id' => $request->get['room_id'] ?? 0,
        'connected_at' => time(),
    ]);
});

$server->on("close", function (Server $server, $fd) {
    $info = $server->getClientInfo($fd);
    $uid = $info['uid'] ?? null;
    if ($uid) {
        // 用户可能在其他节点还有连接，不做删除，只更新离线时间
        SessionManager::save($fd, ['uid' => $uid, 'offline_at' => time()]);
    }
});
```

---

## 5. 安全防护

### 5.1 WSS/TLS 加密

**配置：**

```nginx
# Nginx 终结 TLS
server {
    listen 443 ssl http2;
    server_name ws.example.com;

    ssl_certificate /etc/ssl/certs/fullchain.pem;
    ssl_certificate_key /etc/ssl/private/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;

    location /ws {
        proxy_pass http://ws_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```go
// Go 原生 TLS WebSocket
func main() {
    certFile := "/etc/ssl/certs/server.crt"
    keyFile := "/etc/ssl/private/server.key"

    http.HandleFunc("/ws", wsHandler)

    server := &http.Server{
        Addr:    ":443",
        Handler: nil,
        TLSConfig: &tls.Config{
            MinVersion: tls.VersionTLS12,
            CipherSuites: []uint16{
                tls.TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256,
                tls.TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256,
            },
        },
    }

    log.Fatal(server.ListenAndServeTLS(certFile, keyFile))
}
```

```php
// PHP Swoole SSL 配置
$server = new Swoole\WebSocket\Server("0.0.0.0", 9501, SWOOLE_PROCESS, SWOOLE_SOCK_TCP | SWOOLE_SSL);
$server->set([
    'ssl_cert_file' => '/etc/ssl/certs/server.crt',
    'ssl_key_file' => '/etc/ssl/private/server.key',
    'ssl_protocols' => SWOOLE_SSL_TLSV1_2 | SWOOLE_SSL_TLSV1_3,
    'ssl_ciphers' => 'ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384',
]);
```

---

### 5.2 Token 鉴权（JWT 握手验证）

**方案一：URL Query 传递 Token（握手阶段验证）：**

```go
func jwtAuthMiddleware(next http.HandlerFunc) http.HandlerFunc {
    return func(w http.ResponseWriter, r *http.Request) {
        token := r.URL.Query().Get("token")
        if token == "" {
            http.Error(w, "missing token", 401)
            return
        }

        claims, err := validateJWT(token)
        if err != nil {
            http.Error(w, "invalid token", 401)
            return
        }

        // 将用户信息注入 context
        ctx := context.WithValue(r.Context(), "uid", claims.UID)
        ctx = context.WithValue(ctx, "username", claims.Username)
        next(w, r.WithContext(ctx))
    }
}

func wsHandler(w http.ResponseWriter, r *http.Request) {
    uid := r.Context().Value("uid").(int64)
    // 后续升级操作使用 uid
}
```

**方案二：握手阶段 HTTP Header 传递：**

```javascript
// 客户端
const token = await getAuthToken();
const ws = new WebSocket(`wss://chat.example.com/ws`, {
    headers: { 'Authorization': `Bearer ${token}` }
});
// 注意：浏览器 WebSocket API 不支持自定义 headers，
// 需通过 URL query 或子协议携带
```

**方案三：Sec-WebSocket-Protocol 子协议携带：**

```javascript
const ws = new WebSocket('wss://chat.example.com/ws', ['chat', 'auth_v2_' + token]);

// 服务端提取子协议中的 token
```

**PHP Swoole JWT 鉴权：**

```php
<?php
use Firebase\JWT\JWT;
use Firebase\JWT\Key;

$server->on("handshake", function (Request $request, Response $response): bool {
    $token = $request->get['token'] ?? $request->header['authorization'] ?? '';

    if (empty($token)) {
        $response->status(401);
        $response->end(json_encode(['error' => 'missing token']));
        return false;
    }

    try {
        $decoded = JWT::decode($token, new Key('your-secret', 'HS256'));
        // 将用户信息存入请求属性
        $request->uid = $decoded->sub;
        $request->username = $decoded->name;
        return true;
    } catch (\Exception $e) {
        $response->status(401);
        $response->end(json_encode(['error' => 'invalid token']));
        return false;
    }
});
```

---

### 5.3 消息加密

**端到端加密（E2EE）vs 传输加密：**

```
传输加密（TLS）：节点到节点加密，服务端能看到明文
端到端加密（E2EE）：客户端加密，服务端仅做转发
```

**E2EE 实现：**

```javascript
// 客户端—使用 Web Crypto API
async function encryptMessage(plaintext, sharedSecret) {
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const encoded = new TextEncoder().encode(plaintext);
    const key = await crypto.subtle.importKey(
        'raw', sharedSecret,
        { name: 'AES-GCM', length: 256 },
        false, ['encrypt']
    );
    const ciphertext = await crypto.subtle.encrypt(
        { name: 'AES-GCM', iv },
        key, encoded
    );
    // 合并 iv + ciphertext
    const combined = new Uint8Array(iv.length + ciphertext.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(ciphertext), iv.length);
    return combined;
}
```

**Go 服务端 AES-GCM 加密：**

```go
package main

import (
    "crypto/aes"
    "crypto/cipher"
    "crypto/rand"
    "encoding/base64"
    "io"
)

// 服务端存储加密（消息落盘前）
func encryptPayload(plaintext []byte, key []byte) (string, error) {
    block, err := aes.NewCipher(key)
    if err != nil {
        return "", err
    }

    aead, err := cipher.NewGCM(block)
    if err != nil {
        return "", err
    }

    nonce := make([]byte, aead.NonceSize())
    if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
        return "", err
    }

    ciphertext := aead.Seal(nonce, nonce, plaintext, nil)
    return base64.StdEncoding.EncodeToString(ciphertext), nil
}

func decryptPayload(cipherB64 string, key []byte) ([]byte, error) {
    ciphertext, _ := base64.StdEncoding.DecodeString(cipherB64)
    block, _ := aes.NewCipher(key)
    aead, _ := cipher.NewGCM(block)

    nonceSize := aead.NonceSize()
    nonce, ciphertext := ciphertext[:nonceSize], ciphertext[nonceSize:]
    return aead.Open(nil, nonce, ciphertext, nil)
}
```

---

### 5.4 频率限制与 DDoS 防护

**Go 限流中间件（令牌桶 + 连接级限流）：**

```go
package main

import (
    "net/http"
    "sync"
    "time"
    "golang.org/x/time/rate"
)

type RateLimiter struct {
    mu       sync.Mutex
    clients  map[string]*rate.Limiter
    rate     rate.Limit
    burst    int
    cleanupInterval time.Duration
}

func NewRateLimiter(r rate.Limit, burst int) *RateLimiter {
    rl := &RateLimiter{
        clients: make(map[string]*rate.Limiter),
        rate:    r,
        burst:   burst,
    }

    // 定时清理过期客户端（防止内存泄漏）
    go func() {
        for {
            time.Sleep(10 * time.Minute)
            rl.mu.Lock()
            for ip, limiter := range rl.clients {
                // 如果超过 30 分钟未使用，清理
                if limiter != nil {
                    delete(rl.clients, ip)
                }
            }
            rl.mu.Unlock()
        }
    }()

    return rl
}

func (rl *RateLimiter) GetLimiter(ip string) *rate.Limiter {
    rl.mu.Lock()
    defer rl.mu.Unlock()

    limiter, exists := rl.clients[ip]
    if !exists {
        limiter = rate.NewLimiter(rl.rate, rl.burst)
        rl.clients[ip] = limiter
    }
    return limiter
}

// WebSocket 消息限流中间件
func (rl *RateLimiter) WSInterceptor(next func(clientID string, msg []byte) error) func(string, []byte) error {
    return func(clientID string, msg []byte) error {
        if !rl.GetLimiter(clientID).Allow() {
            return fmt.Errorf("rate limit exceeded")
        }
        return next(clientID, msg)
    }
}
```

**PHP Swoole 限流：**

```php
<?php
use Swoole\Table;

$rateTable = new Table(65536);
$rateTable->column('count', Table::TYPE_INT, 4);
$rateTable->column('reset_time', Table::TYPE_INT, 4);
$rateTable->create();

function checkRateLimit(int $fd, int $maxPerWindow = 60, int $windowSeconds = 60): bool {
    global $rateTable;
    $now = time();

    if (!$rateTable->exists($fd)) {
        $rateTable->set($fd, ['count' => 1, 'reset_time' => $now + $windowSeconds]);
        return true;
    }

    $data = $rateTable->get($fd);
    if ($now > $data['reset_time']) {
        $rateTable->set($fd, ['count' => 1, 'reset_time' => $now + $windowSeconds]);
        return true;
    }

    if ($data['count'] >= $maxPerWindow) {
        return false; // 限流
    }

    $rateTable->incr($fd, 'count', 1);
    return true;
}

$server->on("message", function (Server $server, $frame) {
    $ip = $server->getClientInfo($frame->fd)['remote_ip'] ?? '';

    if (!checkRateLimit($frame->fd, 60, 60)) {
        $server->push($frame->fd, json_encode(['error' => 'rate limit']));
        return;
    }

    // 业务处理...
});
```

**DDoS 防护策略：**

| 层级 | 措施 |
|------|------|
| 网络层 | Cloudflare / AWS Shield / 高防 IP |
| 传输层 | Nginx limit_conn / limit_req、Syn Cookie |
| 应用层 | 连接数限制（per IP）、消息限流、验证码 |
| 业务层 | 用户鉴权前不分配资源、token 验证后才建立连接 |

---

## 6. 性能优化

### 6.1 连接数优化（C10K / C100K / C1000K）

**C10K 问题：单机 1 万并发连接**  
- 使用 epoll（Linux）/ kqueue（macOS）/ IOCP（Windows）
- Go runtime 与 Swoole 的 Reactor 模型天然支持

**C100K 到 C1000K 的关键：**

| 瓶颈 | 解决方案 |
|------|----------|
| fd 限制 | 调整 `ulimit -n`（100万连接需 `fs.file-max` 和 `RLIMIT_NOFILE`）|
| 内存 | 每个连接 10-20KB 控制块（100万 ≈ 20GB）|
| 内核参数 | 调整 `net.ipv4.tcp_mem`、`net.core.rmem_max`、`net.core.wmem_max` |
| TIME_WAIT | 开启 `net.ipv4.tcp_tw_reuse`、`net.ipv4.tcp_tw_recycle`（注意 NAT 问题）|

**Go 百万连接优化：**

```go
package main

import (
    "net"
    "os"
    "syscall"
)

func tuneOS() {
    // Go runtime 层面—配置 goroutine 数量
    // 每个连接一个 goroutine，避免频繁调度
    // 使用 goroutine pool 复用

    // 调整系统参数（需 root 或 CAP_NET_ADMIN）
    // sysctl -w net.core.somaxconn=65535
    // sysctl -w net.ipv4.tcp_max_syn_backlog=65535
    // sysctl -w fs.file-max=1048576
    _ = os.Getenv("")
    _ = syscall.SOMAXCONN
}

// 自定义 Listener — 设置更优的 TCP 参数
func optimizedListener() (net.Listener, error) {
    lc := net.ListenConfig{
        Control: func(network, address string, c syscall.RawConn) error {
            return c.Control(func(fd uintptr) {
                // 设置 SO_REUSEPORT（仅 Linux 3.9+）
                syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, 0x0F, 1)
                // 设置 TCP_DEFER_ACCEPT
                syscall.SetsockoptInt(int(fd), syscall.IPPROTO_TCP, 9, 1)
                // 设置 TCP_QUICKACK
                syscall.SetsockoptInt(int(fd), syscall.IPPROTO_TCP, 12, 1)
            })
        },
    }
    return lc.Listen(context.Background(), "tcp", ":8080")
}
```

**PHP Swoole Reactor 模型：**

```php
// Swoole 使用 Reactor + Worker 多进程架构
$server = new Swoole\WebSocket\Server("0.0.0.0", 9501, SWOOLE_PROCESS);

$server->set([
    'reactor_num' => 8,          // Reactor 线程数（负责网络事件）
    'worker_num' => 16,          // Worker 进程数（业务逻辑）
    'backlog' => 65536,          // 连接队列大小
    'max_conn' => 100000,        // 最大连接数
    'socket_buffer_size' => 2 * 1024 * 1024, // 2MB socket 缓冲区
    'buffer_output_size' => 2 * 1024 * 1024,
    'dispatch_mode' => 2,        // 固定分配（连接绑定到固定 worker）
]);
```

---

### 6.2 内存优化

**零拷贝（Zero Copy）技术：**

```go
// Go — 避免 []byte 到 string 的额外分配
// 使用 unsafe 零拷贝转换（仅限消息处理周期内安全）
func bytesToString(b []byte) string {
    return *(*string)(unsafe.Pointer(&b))
}

// 预分配 buffer 池
var bufferPool = sync.Pool{
    New: func() interface{} {
        return make([]byte, 4096)
    },
}

// 从池中获取 buffer
buf := bufferPool.Get().([]byte)
defer bufferPool.Put(buf)
```

```php
// PHP Swoole — 使用内存池和零拷贝
// 使用 Swoole Table 替代数组
$table = new Swoole\Table(1024 * 1024);
$table->column('data', Table::TYPE_STRING, 1024);
$table->create();

// 使用 Swoole Buffer
$buffer = new Swoole\Buffer(1024);
$buffer->append($data);

// 使用内存共享（Swoole\Atomic）
$atomic = new Swoole\Atomic(0);
```

**对象复用（避免 GC 压力）：**

```go
// Go — 使用 sync.Pool 复用消息对象
type Message struct {
    Type string      `json:"type"`
    Data interface{} `json:"data"`
    ID   string      `json:"id"`
    Time int64       `json:"time"`
}

var msgPool = sync.Pool{
    New: func() interface{} {
        return &Message{}
    },
}

// 分配
msg := msgPool.Get().(*Message)

// 使用后重置并归还
msg.Type = ""
msg.Data = nil
msg.ID = ""
msg.Time = 0
msgPool.Put(msg)
```

**PHP Swoole — 协程上下文复用：**

```php
<?php
use Swoole\Coroutine;

// 使用协程上下文避免全局变量
$server->on("message", function (Server $server, $frame) {
    Coroutine::getContext()['msg_count'] = 0;

    go(function () use ($server, $frame) {
        // 处理消息...
    });
});

// 使用 Swoole 的 Channel 替代 slice/map
$channel = new Swoole\Coroutine\Channel(1024);
```

---

### 6.3 GC 优化

**Go GC 优化经验：**

```go
// 1. 控制 GOGC 参数（降低 GC 频率）
// GOGC=200 （200% 堆增长才触发 GC，默认 100）
// 或运行时设置
debug.SetGCPercent(200)

// 2. 减少对象分配
// - 预分配 slice（make([]byte, 0, expectedSize)）
// - 使用 sync.Pool
// - 避免在热点路径使用 fmt.Sprintf，使用 bytes.Buffer

// 3. 分担 GC 压力 — 分离热数据与冷数据
type ConnectionPool struct {
    // 每个连接一个 buffer
    readBuf  sync.Pool // 频繁分配的小对象
    sessions sync.Map  // 长生命周期的 session 对象
}
```

**PHP Swoole — 内存常驻：**

```php
// PHP 在 Swoole 下是常驻进程，需注意内存泄漏

// 1. 循环引用 — 使用 weak reference
$server->on("message", function (Server $server, $frame) {
    // 避免在闭包中捕获 $server 导致循环引用
    // 可用 Coroutine::defer 清理
});

// 2. 定时检查内存
$server->tick(60000, function () use ($server) {
    $usage = memory_get_usage(true);
    $peak = memory_get_peak_usage(true);
    if ($usage > 500 * 1024 * 1024) { // 超过 500MB
        // 记录日志并考虑重启 worker
        $server->reload();
    }
});
```

---

### 6.4 协议压缩

**permessage-deflate 扩展：**

WebSocket 内置的压缩扩展，对消息载荷进行 DEFLATE 压缩。

```go
// Go gorilla/websocket — 启用 permessage-deflate
import "github.com/gorilla/websocket"

var upgrader = websocket.Upgrader{
    EnableCompression: true,
    ReadBufferSize:    4096,
    WriteBufferSize:   4096,
}

// 客户端需在握手时声明：
// Sec-WebSocket-Extensions: permessage-deflate; client_max_window_bits
```

```nginx
# Nginx 反向代理 — 启用压缩
map $http_sec_websocket_extensions $sec_ws_ext {
    default "";
    "~*permessage-deflate" "permessage-deflate";
}

server {
    location /ws {
        proxy_pass http://backend;
        proxy_set_header Sec-WebSocket-Extensions $sec_ws_ext;
    }
}
```

**高频面试题：**

| 问题 | 要点 |
|------|------|
| permessage-deflate 的代价？ | 增加 CPU 开销（压缩/解压缩），小消息可能反而膨胀 |
| 何时使用压缩？ | JSON 文本消息（通常 50-70% 压缩率）；二进制/已压缩数据（图片）不适用 |
| 内存窗口大小优化？ | `client_max_window_bits` 和 `server_max_window_bits` 控制内存使用 |

---

### 6.5 Protobuf 二进制替代 JSON

**Protobuf 定义：**

```protobuf
// chat.proto
syntax = "proto3";
package chat;

message WsMessage {
    string msg_id = 1;
    int32 type = 2;
    int64 from_uid = 3;
    int64 to_uid = 4;
    int64 room_id = 5;
    string content = 6;
    int64 timestamp = 7;
    map<string, string> metadata = 8;
    oneof attachment {
        ImageData image = 10;
        AudioData audio = 11;
        FileData file = 12;
    }
}

message ImageData {
    string url = 1;
    int32 width = 2;
    int32 height = 3;
    string format = 4;
}

message FileData {
    string name = 1;
    int64 size = 2;
    string url = 3;
}
```

**Go 使用 Protobuf：**

```go
package main

import (
    "github.com/golang/protobuf/proto"
    pb "path/to/chat/proto"
)

func createMessage() []byte {
    msg := &pb.WsMessage{
        MsgId:     uuid.New().String(),
        Type:      1,
        FromUid:   1001,
        ToUid:     1002,
        Content:   "Hello",
        Timestamp: time.Now().Unix(),
    }
    data, _ := proto.Marshal(msg)
    return data
}

// 端到端性能对比：
// JSON:  "{\"msg_id\":\"xxx\",\"type\":1,\"from_uid\":1001,\"content\":\"Hello\"}" = 72 bytes
// Proto: 0x0a0365787810011802... = 28 bytes（61% 缩减）
```

**PHP Swoole 使用 Protobuf：**

```php
<?php
// 需要安装 protobuf 扩展
use Chat\WsMessage;
use Chat\ImageData;

$msg = new WsMessage();
$msg->setMsgId(uniqid());
$msg->setType(1);
$msg->setFromUid(1001);
$msg->setToUid(1002);
$msg->setContent("Hello from PHP");
$msg->setTimestamp(time());

$binaryData = $msg->serializeToString();

// 发送二进制帧
$server->push($fd, $binaryData, SWOOLE_WEBSOCKET_OPCODE_BINARY);
```

**性能对比数据（基准测试）：**

| 指标 | JSON | Protobuf | 提升 |
|------|------|----------|------|
| 消息大小 | 128 bytes | 42 bytes | 67% |
| 序列化 | 1.2 us | 0.3 us | 75% |
| 反序列化 | 1.8 us | 0.4 us | 78% |
| 带宽消耗 | 高 | 低 | 显著 |

---

## 7. 场景实战

### 7.1 IM 即时通讯

**架构要点：**

- 连接管理：注册中心 + 多设备支持
- 消息模型：`{msg_id, type, from, to, content, timestamp, seq}`
- 消息存储：写扩散（收件箱）+ 读扩散（群聊）
- 在线状态上报：Redis bitmap / Bloom Filter
- 离线消息：消息持久化 + 上线拉取（同步点播 / 推拉结合）

**消息流时序：**

```
A -> WS Server1 -> 消息路由 -> 判断接收方在线
├── 在线: Redis Pub/Sub -> WS Server2 -> B
└── 离线: 写入消息存储（MySQL/时序DB）
     B上线 -> 登录 -> 拉取离线消息（同步）
     B上线 -> WS Server 通知（等 B 来拉）
```

**PHP Swoole IM 消息结构：**

```php
<?php
class IMMessage {
    public string $msgId;
    public int    $fromUid;
    public int    $toUid;
    public int    $msgType;    // 1:text, 2:image, 3:file, 4:system
    public string $content;
    public int    $timestamp;
    public int    $seq;        // 消息序号（递增，用于去重和排序）
    public int    $status;     // 0:发送中, 1:已送达, 2:已读
    public ?int   $groupId;   // 群聊 ID（0 表示私聊）
}
```

---

### 7.2 实时推送 / 通知

**架构要点：**

- 用户 tags/segments 系统：按标签找目标用户
- 推送通道：WebSocket > APNs/FCM（移动端退路）
- 全量 vs 精准推送

**Go 推送管理：**

```go
type PushService struct {
    hub        *Hub          // WS 连接管理
    apnsClient *apns.Client  // iOS 推送
    fcmClient  *fcm.Client   // Android 推送
}

func (s *PushService) PushToUser(ctx context.Context, uid int64, notification *Notification) {
    // 1. 尝试 WebSocket 推送
    sent := s.hub.SendToUser(uid, notification.ToBytes())
    if sent {
        return
    }

    // 2. WS 不在线，走移动端推送
    deviceTokens := s.getDeviceTokens(ctx, uid)
    for _, token := range deviceTokens {
        if token.Platform == "ios" {
            s.apnsClient.Push(token.Value, notification.ToAPNSPayload())
        } else {
            s.fcmClient.Push(token.Value, notification.ToFCMPayload())
        }
    }
}
```

---

### 7.3 协同编辑（OT / CRDT）

**WebSocket 在协同编辑中的角色：**

- 操作传输通道（WebSocket 提供低延迟双工通信）
- 操作合并由 OT（Operational Transformation）或 CRDT 算法完成

**架构方案：**

```
用户A ---WS---> Server ---WS---> 用户B
               │
               ├── 操作转换（OT Server）
               ├── 操作日志（Redis/Kafka）
               └── 文档快照（持久化存储）
```

**消息格式：**

```javascript
// OT 操作
{
    "type": "operation",
    "doc_id": "doc_123",
    "revision": 42,
    "ops": [
        { "action": "insert", "pos": 10, "chars": "hello" },
        { "action": "retain", "len": 5 },
        { "action": "delete", "pos": 20, "len": 3 }
    ]
}

// ACK
{
    "type": "ack",
    "revision": 43
}
```

---

### 7.4 实时数据大屏

**架构要点：**

- 数据流：后端 ETL -> 消息队列 -> WS Server -> 大屏
- 推送频率控制：根据前端渲染能力动态调整（throttle）
- 断线重连：大屏应支持自动重连 + 全量数据刷新

**Go 大屏推送优化：**

```go
// 节流推送 — 聚合 1 秒内的数据变更
type DashboardAggregator struct {
    mu     sync.Mutex
    buffer map[string]interface{}
    ticker *time.Ticker
    conn   *websocket.Conn
}

func (d *DashboardAggregator) Push(event string, data interface{}) {
    d.mu.Lock()
    d.buffer[event] = data
    d.mu.Unlock()
}

func (d *DashboardAggregator) Start() {
    for range d.ticker.C {
        d.mu.Lock()
        payload := d.buffer
        d.buffer = make(map[string]interface{})
        d.mu.Unlock()

        if len(payload) > 0 {
            d.conn.WriteJSON(map[string]interface{}{
                "type": "dashboard_update",
                "data": payload,
                "ts":  time.Now().UnixMilli(),
            })
        }
    }
}
```

---

### 7.5 游戏状态同步

**三种同步模型：**

| 模型 | 延迟要求 | 带宽 | 适用场景 |
|------|----------|------|----------|
| 状态同步（State Sync） | <50ms | 高 | MMO 大型多人在线 |
| 帧同步（Lockstep） | <100ms | 低 | RTS/格斗游戏 |
| 操作同步（Input Sync） | <30ms | 中 | FPS |

**Go 帧同步架构：**

```go
type GameRoom struct {
    RoomID    string
    Players   map[string]*Player
    FrameChan chan *GameFrame
    TickRate  int      // 20 tick/s
    CurrentFrame int64
}

type GameFrame struct {
    FrameID int64
    Inputs  map[string]*PlayerInput // playerID -> input
}

type PlayerInput struct {
    Up    bool `json:"up"`
    Down  bool `json:"down"`
    Left  bool `json:"left"`
    Right bool `json:"right"`
    Attack bool `json:"attack"`
}

func (r *GameRoom) GameLoop() {
    ticker := time.NewTicker(time.Second / time.Duration(r.TickRate))
    defer ticker.Stop()

    for range ticker.C {
        r.CurrentFrame++

        // 收集所有玩家本帧的输入
        frame := &GameFrame{
            FrameID: r.CurrentFrame,
            Inputs:  make(map[string]*PlayerInput),
        }

        select {
        case frame.Inputs = <-r.FrameChan:
        default:
        }

        // 广播帧给所有玩家
        r.BroadcastFrame(frame)
    }
}
```

---

### 7.6 直播弹幕

**架构要点：**

- 与视频流无关，独立 WebSocket 通道
- 消息签名防伪造（用户 ID + 时间戳 + 签名）
- 弹幕审核（敏感词过滤 + 频率限制）
- 弹幕缓存（CDN 边缘节点缓存弹幕流）

**Go 弹幕广播优化：**

```go
// 广播树 — 避免 O(n) 循环
type BroadcastTree struct {
    root    *RoomNode
    fanout  int // 扇出系数
}

type RoomNode struct {
    subRooms []*RoomNode
    clients  []*websocket.Conn
}

func (t *BroadcastTree) Broadcast(msg []byte) {
    var wg sync.WaitGroup
    t.broadcastNode(t.root, msg, &wg)
    wg.Wait()
}

func (t *BroadcastTree) broadcastNode(node *RoomNode, msg []byte, wg *sync.WaitGroup) {
    // 向本节点的客户端发送
    for _, c := range node.clients {
        wg.Add(1)
        go func(conn *websocket.Conn) {
            defer wg.Done()
            conn.WriteMessage(websocket.TextMessage, msg)
        }(c)
    }
    // 递归子节点
    for _, sub := range node.subRooms {
        t.broadcastNode(sub, msg, wg)
    }
}
```

**PHP Swoole 弹幕示例：**

```php
<?php
use Swoole\WebSocket\Server;

$server = new Server("0.0.0.0", 9501);

$server->set([
    'worker_num' => 4,
    'max_conn' => 50000,
]);

// 房间连接管理
$roomClients = new Swoole\Table(1024);
$roomClients->column('count', Table::TYPE_INT, 4);
$roomClients->create();

$server->on("message", function (Server $server, $frame) {
    $data = json_decode($frame->data, true);
    $roomId = $data['room_id'] ?? 0;

    switch ($data['type']) {
        case 'danmaku':
            $content = strip_tags($data['text']);
            // 敏感词过滤
            if (checkSensitive($content)) {
                $server->push($frame->fd, json_encode(['error' => 'content blocked']));
                return;
            }
            // 广播给房间所有客户端
            $msg = json_encode([
                'type' => 'danmaku',
                'uid' => $data['uid'],
                'text' => $content,
                'color' => $data['color'] ?? '#fff',
                'time' => time(),
            ]);
            foreach ($server->connections as $fd) {
                // 优化：使用 connect_info 缓存 room_id 避免每次查询
                $server->push($fd, $msg);
            }
            break;
    }
});

$server->start();
```

---

### 7.7 物联网 IoT

**架构要点：**

- 设备端资源受限使用 MQTT，服务端到服务端使用 WebSocket
- 协议翻译：MQTT Broker <-> WS Gateway
- 设备状态：Registr 上报（RESTful）+ 变更推送（WebSocket）
- 指令下推：反向通道推送控制指令

**常见拓扑：**

```
传感器 -> MQTT Broker -> 规则引擎 -> WS Server -> Web 仪表盘
                                          |
                                    App 推送 / 告警

Web 控制台 -> WS Server -> MQTT Broker -> 设备
```

---

## 8. 替代方案对比

### 8.1 SSE（Server-Sent Events）

| 特性 | WebSocket | SSE |
|------|-----------|-----|
| 通信方向 | 全双工 | 服务端→单向 |
| 协议 | WS（独立协议） | HTTP |
| 自动重连 | 需手动实现 | EventSource 内置 |
| 二进制 | 支持 | 不支持（Text） |
| 最大并发连接 | 不限 | 浏览器限制 6 个/域名 |
| 跨域 | 直接支持 | CORS 配置 |
| 复杂度 | 中高 | 低 |
| 适用场景 | IM/游戏/协同编辑 | 实时通知/股价/进度推送 |

**SSE 示例（客户端简单性突出）：**

```javascript
// 客户端 — 3 行代码
const source = new EventSource('/api/stream');
source.addEventListener('message', (e) => {
    document.getElementById('data').innerText = e.data;
});
source.addEventListener('custom', (e) => {
    // 自定义事件
});
```

**Go 服务端 SSE：**

```go
func sseHandler(w http.ResponseWriter, r *http.Request) {
    flusher, ok := w.(http.Flusher)
    if !ok {
        http.Error(w, "not supported", 500)
        return
    }

    w.Header().Set("Content-Type", "text/event-stream")
    w.Header().Set("Cache-Control", "no-cache")
    w.Header().Set("Connection", "keep-alive")
    w.Header().Set("Access-Control-Allow-Origin", "*")

    ch := make(chan string)
    // 注册事件源
    eventBus.Subscribe(r.URL.Query().Get("channel"), ch)
    defer eventBus.Unsubscribe(ch)

    for {
        select {
        case data := <-ch:
            fmt.Fprintf(w, "data: %s\n\n", data)
            flusher.Flush()
        case <-r.Context().Done():
            return
        }
    }
}
```

---

### 8.2 gRPC Stream

| 特性 | WebSocket | gRPC Stream |
|------|-----------|-------------|
| 传输层 | TCP | HTTP/2 |
| 序列化 | JSON/自定义 | Protobuf（强制）|
| 双向流 | 原生支持 | 支持（Server/Client/Bidirectional）|
| 生态 | 浏览器原生 | 需 gRPC-Web/Envoy 代理 |
| 服务发现 | 无 | 内置（基于 DNS/LB）|
| 流控 | 应用层实现 | HTTP/2 流控 |
| 适用场景 | 客户端多样性高 | 微服务间通信 |

```go
// gRPC 双向流 — 与 WebSocket 类似
func (s *chatServer) Chat(stream pb.Chat_ChatServer) error {
    for {
        msg, err := stream.Recv()
        if err == io.EOF {
            return nil
        }
        if err != nil {
            return err
        }

        // 处理消息
        response := &pb.ChatMessage{
            MsgId:     uuid.New().String(),
            Content:   "received: " + msg.Content,
            Timestamp: time.Now().Unix(),
        }

        if err := stream.Send(response); err != nil {
            return err
        }
    }
}
```

---

### 8.3 MQTT

| 特性 | WebSocket | MQTT |
|------|-----------|------|
| 协议 | TCP | TCP/TLS |
| 发布/订阅 | 需自建 | 原生支持（QoS 0/1/2）|
| 消息 QoS | 应用层实现 | 协议层支持 |
| 保留消息 | 无 | 支持 |
| 最小包开销 | 2 字节（帧头） | 2 字节 |
| 客户端体积 | 较大（浏览器内置） | 极小（适合嵌入式）|
| 适用场景 | Web 应用 | IoT/M2M/嵌入式 |

---

### 8.4 WebTransport

| 特性 | WebSocket | WebTransport |
|------|-----------|--------------|
| 传输层 | TCP | QUIC (UDP) |
| 多路复用 | 单流 | 多流（无头阻塞）|
| 不可靠传输 | 不支持 | 支持（Unreliable Stream）|
| 延迟 | TCP 握手 | 0-RTT |
| 浏览器支持 | 全平台 | Chrome-only（2024+逐步普及）|
| 连接迁移 | 需自建 | QUIC 原生支持（连接迁移）|

**WebTransport 示例：**

```javascript
// 客户端 — WebTransport（新 API）
async function connect() {
    const transport = new WebTransport('https://example.com:443/webtransport');
    await transport.ready;

    // 不可靠数据报（类似 UDP）
    const writer = transport.datagrams.writable.getWriter();
    writer.write(new TextEncoder().encode('hello'));

    // 可靠单向流
    const stream = await transport.createBidirectionalStream();
    const reader = stream.readable.getReader();
    const writer = stream.writable.getWriter();
}
```

---

### 8.5 技术选型决策树

```
是否需要全双工通信？
├── 否 ──→ SSE（简单推送/通知/进度）
└── 是 ──→ 是否追求极低延迟 + 浏览器兼容？
    ├── 是 ──→ WebSocket（全栈首选）
    └── 否 ──→ 客户端环境？
        ├── 微服务间 ──→ gRPC Stream
        ├── 嵌入式/IoT ──→ MQTT
        └── 现代浏览器（仅 Chrome）──→ WebTransport
```

---

## 附录

### A. 高频面试题速查

| 主题 | 题目 | 难易度 |
|------|------|--------|
| 协议 | 简述 WebSocket 握手过程及 Sec-WebSocket-Key 的验证 | ⭐⭐ |
| 协议 | 为什么客户端需要掩码而服务端不需要？ | ⭐⭐⭐ |
| 协议 | 解释 WebSocket 帧结构中的 FIN、Opcode、MASK 字段 | ⭐⭐ |
| 协议 | TCP 和 WebSocket 的 Ping/Pong 有什么区别？ | ⭐⭐ |
| 服务端 | WebSocket 连接管理中的注册中心模式如何设计？ | ⭐⭐⭐ |
| 性能 | 如何在一台服务器上支撑 100 万 WebSocket 连接？ | ⭐⭐⭐⭐ |
| 性能 | permessage-deflate 压缩的优缺点是什么？ | ⭐⭐⭐ |
| 分布式 | 分布式中 WebSocket 用户连接跨节点时如何投递消息？ | ⭐⭐⭐⭐ |
| 分布式 | 一致性哈希在 WS 网关层的作用？ | ⭐⭐⭐ |
| 可靠性 | 如何保证 WebSocket 消息不丢失？ | ⭐⭐⭐⭐ |
| 可靠性 | 断线重连为什么使用指数退避 + jitter？ | ⭐⭐ |
| 安全 | WebSocket 有哪些常见安全攻击及防御手段？ | ⭐⭐⭐ |
| 对比 | WebSocket 相比 SSE，各自适用什么场景？ | ⭐⭐ |
| 对比 | WebTransport 能否取代 WebSocket？ | ⭐⭐⭐ |

### B. 推荐的 Open Source 项目

| 项目 | 语言 | 说明 |
|------|------|------|
| [Centrifugo](https://github.com/centrifugal/centrifugo) | Go | 可扩展的实时消息服务器，WebSocket + SSE + GRPC |
| [Mercure](https://github.com/dunglas/mercure) | Go | 基于 SSE 的实时推送 Hub |
| [Swoole](https://github.com/swoole/swoole-src) | C/PHP | PHP 协程 + WebSocket Server |
| [gorilla/websocket](https://github.com/gorilla/websocket) | Go | 经典 WS 库（已归档）|
| [nhooyr.io/websocket](https://github.com/nhooyr/websocket) | Go | 现代 WS 库（活跃维护）|
| [Socket.IO](https://github.com/socketio/socket.io) | JS | 全功能实时框架 |

### C. 检查清单（Go-live 前逐项确认）

- [ ] WSS/TLS 已配置，HTTP -> HTTPS 自动跳转
- [ ] JWT 鉴权在握手阶段完成，拒绝未授权连接
- [ ] 连接频率限制（每 IP 每秒连接数 + 消息数）
- [ ] 消息大小限制（帧载荷上限）
- [ ] 心跳机制已启用（应用层 Ping/Pong + TCP Keep-Alive）
- [ ] 超时断连逻辑（idle timeout）
- [ ] 跨域策略（`CheckOrigin` 配置生产环境域名白名单）
- [ ] 日志与监控（连接数、消息吞吐、错误率）
- [ ] 优雅关闭（信号量捕获，等待连接处理完后再退出）
- [ ] Session 持久化到 Redis（支持断线迁移）
- [ ] 负载均衡（LB 一致性哈希或 Sticky Session）
- [ ] 离线消息存储与重投机制
- [ ] 资源限制（最大连接数、最大消息大小、goroutine/协程数）

---

> 本文档持续更新，覆盖高级 WebSocket 面试的核心知识点。每个模块兼顾深度（原理分析）与广度（多语言实践、架构设计），适合作为高级后端开发 / 架构师的技术面试准备材料。
