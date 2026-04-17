# MissAV Stream Service

独立的 MissAV 视频流解析服务，用于获取 MissAV.ai 网站视频的可播放信息。

> 当前定位：**轻量解析服务**，适合部署在 Koyeb 等低配环境。  
> 它负责解析 `stream_url` 并返回播放所需请求头，**不负责代理整段视频流量**。

## 功能

- 从 MissAV.ai 获取影片视频流 URL
- 支持多质量选择（720p, 1080p 等）
- 自动绕过 Cloudflare 保护（优先使用 `curl_cffi`）
- 返回统一播放结构 `playback`
- 轻量模式：返回 `direct_url + headers`，不做重流量代理

## API 接口

### 1. 健康检查

```http
GET /health
```

**响应示例：**

```json
{
  "status": "healthy",
  "service": "missav-stream",
  "base_url": "https://missav.ai"
}
```

### 2. 解析影片 URL (GET)

```http
GET /api/resolve/<movie_id>?quality=1080p
```

**参数：**
- `movie_id`（路径参数）：影片 ID，如 `SSIS-406`
- `quality`（查询参数，可选）：视频质量，如 `720p`, `1080p`，默认最高质量

**成功响应示例：**

```json
{
  "success": true,
  "movie_id": "SSIS-406",
  "stream_url": "https://surrit.com/xxx/1080p/video.m3u8",
  "playback": {
    "mode": "headers",
    "stream_url": "https://surrit.com/xxx/1080p/video.m3u8",
    "direct_url": "https://surrit.com/xxx/1080p/video.m3u8",
    "proxy_url": null,
    "headers": {
      "Referer": "https://missav.ai/SSIS-406",
      "Origin": "https://missav.ai",
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    }
  }
}
```

**失败响应示例：**

```json
{
  "success": false,
  "movie_id": "SSIS-406",
  "stream_url": null,
  "playback": null,
  "error": "No stream URL found"
}
```

### 3. 解析影片 URL (POST)

```http
POST /api/resolve
Content-Type: application/json

{
  "movie_id": "SSIS-406",
  "quality": "720p"
}
```

**成功响应结构与 GET 相同。**

## 统一播放协议说明

本服务返回统一 `playback` 结构，便于客户端与其他服务（例如 busweb）对齐：

- `mode: "headers"`
  - 说明：客户端应使用 `direct_url`，并附带 `headers` 播放
  - 适合：Koyeb / Serverless / 低配容器
- `mode: "proxy"`
  - 说明：通常由本地高带宽服务返回 `proxy_url` / `proxy_path`
  - 本服务**默认不使用该模式**

### 为什么默认不做 proxy？

如果服务端代理整个 HLS 播放过程（m3u8 + 所有分片），会显著增加：

- 出站流量
- 长连接数量
- 并发分片请求数

对于 Koyeb 这类低配实例，这会导致：

- 带宽/流量快速上涨
- 连接压力明显增大
- 成本和稳定性恶化

因此本服务默认只做：

> **解析 + 返回 headers**

而不是：

> **全量视频代理**

## 维护文档

- [Resolver Maintenance Guide](./docs/RESOLVER_MAINTENANCE.md)

这份文档专门说明：

- 当前解析器到底在做什么
- 源站变化时如何分类定位
- 该优先修改哪一层
- 哪些情况属于轻量解析方案的边界

## Flutter 客户端接入建议

如果客户端支持给网络播放器附加请求头，建议优先使用：

- `playback.direct_url`
- `playback.headers`

伪代码示例：

```dart
final playback = response.data['playback'];
final url = playback['direct_url'];
final headers = Map<String, String>.from(playback['headers'] ?? {});

VideoPlayerController.networkUrl(
  Uri.parse(url),
  httpHeaders: headers,
);
```

如果客户端后续同时兼容 busweb 这样的重代理服务，可以统一处理：

1. `mode == proxy` → 优先使用 `proxy_url` / `proxy_path`
2. `mode == headers` → 使用 `direct_url + headers`

## 本地运行

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动服务

```bash
# 开发环境
python app.py

# 生产环境（使用 gunicorn）
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### 3. 配置环境变量（可选）

```bash
export PORT=5000
export BASE_URL=https://missav.ai
export LOG_LEVEL=INFO
```

## Docker 部署

### 1. 构建镜像

```bash
docker build -t missav-stream:latest .
```

### 2. 运行容器

```bash
docker run -d \
  --name missav-stream \
  -p 5000:5000 \
  -e BASE_URL=https://missav.ai \
  -e LOG_LEVEL=INFO \
  missav-stream:latest
```

### 3. Docker Compose（推荐）

```yaml
version: '3.8'

services:
  missav-stream:
    build: .
    container_name: missav-stream
    ports:
      - "5000:5000"
    environment:
      - BASE_URL=https://missav.ai
      - LOG_LEVEL=INFO
    restart: unless-stopped
```

运行：

```bash
docker compose up -d
```

## Koyeb 部署建议

适合部署到 Koyeb，但建议保持当前轻量模式：

- ✅ 推荐：解析 `stream_url` + 返回 `headers`
- ❌ 不推荐：服务端代理完整视频流

如果后续需要代理模式，建议放在：

- 家庭自建服务器
- NAS / 局域网 Docker 主机
- 有稳定带宽和较高流量上限的环境

## 注意事项

1. **curl_cffi**：强烈建议安装，以更好地绕过 Cloudflare 保护
   ```bash
   pip install curl_cffi
   ```

2. **生产环境**：建议使用 gunicorn 而不是 Flask 内置服务器

3. **防火墙**：确保服务器可以访问 `missav.ai` 和 `surrit.com`

4. **速率限制**：服务未内置速率限制，建议在反向代理层加限制

5. **HTTPS**：生产环境建议使用 HTTPS

6. **环境定位**：本服务设计目标是“轻量解析”，不是通用视频 CDN / 反向代理

## Nginx 配置示例

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location /api/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```
