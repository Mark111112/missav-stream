# MissAV Stream Service

独立的 MissAV 视频流解析服务，用于获取 MissAV.ai 网站视频的 m3u8 流 URL。

## 功能

- 从 MissAV.ai 获取影片视频流 URL
- 支持多质量选择（720p, 1080p 等）
- 自动绕过 Cloudflare 保护（使用 curl_cffi）
- RESTful API 接口

## API 接口

### 1. 健康检查

```
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

```
GET /api/resolve/<movie_id>?quality=1080p
```

**参数：**
- `movie_id`（路径参数）：影片 ID，如 `SSIS-406`
- `quality`（查询参数，可选）：视频质量，如 `720p`, `1080p`，默认最高质量

**响应示例（成功）：**
```json
{
  "success": true,
  "movie_id": "SSIS-406",
  "stream_url": "https://surrit.com/xxx/1080p/video.m3u8"
}
```

**响应示例（失败）：**
```json
{
  "success": false,
  "movie_id": "SSIS-406",
  "stream_url": null,
  "error": "No stream URL found"
}
```

### 3. 解析影片 URL (POST)

```
POST /api/resolve
Content-Type: application/json

{
  "movie_id": "SSIS-406",
  "quality": "720p"
}
```

**响应同 GET 接口。**

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

创建 `docker-compose.yml`：

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
docker-compose up -d
```

## Flutter 客户端配置

在 Flutter 应用中设置服务地址：

```dart
MissAVService(
  pythonServerUrl: 'http://your-server:5000',
);
```

## 注意事项

1. **curl_cffi**：强烈建议安装此库以更好地绕过 Cloudflare 保护
   ```bash
   pip install curl_cffi
   ```

2. **生产环境**：建议使用 gunicorn 而不是 Flask 内置服务器

3. **防火墙**：确保服务器可以访问 `missav.ai` 和 `surrit.com`

4. **速率限制**：服务没有内置速率限制，建议使用反向代理（如 Nginx）添加

5. **HTTPS**：生产环境建议使用 HTTPS，可使用 Nginx 反向代理

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
