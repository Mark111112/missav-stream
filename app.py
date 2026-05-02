"""
MissAV 视频流服务
独立的 Flask 服务，用于解析 MissAV.ai 视频流 URL
"""

import logging
import os
from urllib.parse import quote, urljoin, urlparse

import requests as http_requests
from flask import Flask, Response, jsonify, request, stream_with_context

from resolver import VideoResolver


def build_watch_url(movie_id: str) -> str:
    return f"{BASE_URL.rstrip('/')}/{movie_id}"


def build_request_headers(movie_id: str) -> dict[str, str]:
    watch_url = build_watch_url(movie_id)
    parsed = urlparse(watch_url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else BASE_URL.rstrip('/')
    return {
        'Referer': watch_url,
        'Origin': origin,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    }


def build_proxy_url(movie_id: str) -> str:
    proxy_path = f"/proxy/hls/{movie_id}.m3u8"
    return f"{request.host_url.rstrip('/')}{proxy_path}", proxy_path


def build_playback_payload(movie_id: str, stream_url: str):
    proxy_url, proxy_path = build_proxy_url(movie_id)
    return {
        'mode': 'proxy',
        'stream_url': stream_url,
        'direct_url': stream_url,
        'proxy_url': proxy_url,
        'proxy_path': proxy_path,
        'headers': {},
    }


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建 Flask 应用
app = Flask(__name__)

# 配置
PORT = int(os.getenv('PORT', 5000))
BASE_URL = os.getenv('BASE_URL', 'https://missav.ai')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
ALLOWED_PROXY_HOSTS = tuple(
    h.strip().lower() for h in os.getenv('ALLOWED_PROXY_HOSTS', 'surrit.com').split(',') if h.strip()
)

# 设置日志级别
if LOG_LEVEL == 'DEBUG':
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger('resolver').setLevel(logging.DEBUG)
elif LOG_LEVEL == 'WARNING':
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger('resolver').setLevel(logging.WARNING)

# 创建解析器实例
resolver = VideoResolver(base_url=BASE_URL, retry=3, delay=2, timeout=15)


def is_allowed_proxy_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return False
    host = parsed.hostname.lower() if parsed.hostname else ''
    return any(host == allowed or host.endswith(f'.{allowed}') for allowed in ALLOWED_PROXY_HOSTS)


def fetch_upstream(url: str, movie_id: str, *, stream: bool = False):
    headers = build_request_headers(movie_id)
    return http_requests.get(
        url,
        headers=headers,
        timeout=20,
        stream=stream,
        allow_redirects=True,
    )


M3U8_CONTENT_TYPES = (
    'application/vnd.apple.mpegurl',
    'application/x-mpegurl',
    'audio/mpegurl',
    'audio/x-mpegurl',
)


def is_m3u8_response(url: str, content_type: str, body: str) -> bool:
    lowered = (content_type or '').lower()
    return url.lower().endswith('.m3u8') or any(t in lowered for t in M3U8_CONTENT_TYPES) or body.lstrip().startswith('#EXTM3U')


def rewrite_m3u8(content: str, base_url: str, movie_id: str) -> str:
    lines = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            lines.append(raw_line)
            continue

        absolute = urljoin(base_url, line)
        proxied = f"/proxy/file?movie_id={quote(movie_id, safe='')}&url={quote(absolute, safe='')}"
        lines.append(proxied)

    return '\n'.join(lines) + ('\n' if content.endswith('\n') else '')


def proxy_upstream_url(movie_id: str, upstream_url: str):
    if not is_allowed_proxy_url(upstream_url):
        logger.warning('拒绝代理非允许域名: %s', upstream_url)
        return jsonify({'success': False, 'error': 'Upstream host not allowed'}), 400

    try:
        upstream = fetch_upstream(upstream_url, movie_id, stream=True)
    except Exception as e:
        logger.error('代理上游失败: %s, 错误: %s', upstream_url, e)
        return jsonify({'success': False, 'error': str(e)}), 502

    if upstream.status_code >= 400:
        logger.warning('上游返回异常: %s -> HTTP %s', upstream_url, upstream.status_code)
        return jsonify({'success': False, 'error': f'Upstream HTTP {upstream.status_code}'}), 502

    content_type = upstream.headers.get('Content-Type', '')
    if is_m3u8_response(upstream_url, content_type, ''):
        body = upstream.text
        rewritten = rewrite_m3u8(body, upstream_url, movie_id)
        return Response(rewritten, status=200, content_type='application/vnd.apple.mpegurl')

    passthrough_headers = {}
    for header in ('Content-Type', 'Content-Length', 'Accept-Ranges', 'Cache-Control', 'Content-Range'):
        value = upstream.headers.get(header)
        if value:
            passthrough_headers[header] = value

    return Response(
        stream_with_context(upstream.iter_content(chunk_size=64 * 1024)),
        status=upstream.status_code,
        headers=passthrough_headers,
        direct_passthrough=True,
    )


@app.route('/health', methods=['GET'])
def health_check():
    """健康检查端点"""
    return jsonify({
        'status': 'healthy',
        'service': 'missav-stream',
        'base_url': BASE_URL,
        'proxy_hosts': list(ALLOWED_PROXY_HOSTS),
    })


@app.route('/proxy/hls/<movie_id>.m3u8', methods=['GET'])
def proxy_hls(movie_id: str):
    quality = request.args.get('quality', '').strip() or None
    logger.info('代理入口请求: %s, 质量: %s', movie_id, quality or '默认')

    try:
        stream_url = resolver.resolve(movie_id, quality=quality)
        if not stream_url:
            return jsonify({'success': False, 'error': 'No stream URL found'}), 404
        return proxy_upstream_url(movie_id, stream_url)
    except Exception as e:
        logger.error('代理入口异常: %s, 错误: %s', movie_id, e)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/proxy/file', methods=['GET'])
def proxy_file():
    movie_id = request.args.get('movie_id', '').strip()
    upstream_url = request.args.get('url', '').strip()

    if not movie_id or not upstream_url:
        return jsonify({'success': False, 'error': 'movie_id and url are required'}), 400

    return proxy_upstream_url(movie_id, upstream_url)


@app.route('/api/resolve/<movie_id>', methods=['GET'])
def resolve_movie(movie_id: str):
    """
    解析影片 ID 获取视频流 URL

    Args:
        movie_id: 影片 ID（路径参数），如 SSIS-406

    Query Parameters:
        quality: 视频质量（可选），如 720p, 1080p
    """
    quality = request.args.get('quality', '').strip() or None

    logger.info(f"请求解析影片: {movie_id}, 质量: {quality or '默认'}")

    try:
        stream_url = resolver.resolve(movie_id, quality=quality)

        if stream_url:
            logger.info(f"解析成功: {movie_id}")
            playback = build_playback_payload(movie_id, stream_url)
            return jsonify({
                'success': True,
                'movie_id': movie_id,
                'stream_url': stream_url,
                'playback': playback,
            }), 200
        else:
            logger.warning(f"解析失败: {movie_id}")
            return jsonify({
                'success': False,
                'movie_id': movie_id,
                'stream_url': None,
                'playback': None,
                'error': 'No stream URL found'
            }), 404

    except Exception as e:
        logger.error(f"解析异常: {movie_id}, 错误: {e}")
        return jsonify({
            'success': False,
            'movie_id': movie_id,
            'stream_url': None,
            'playback': None,
            'error': str(e)
        }), 500


@app.route('/api/resolve', methods=['POST'])
def resolve_movie_post():
    """
    POST 方式解析影片（兼容旧接口）

    Request JSON:
        {
            "movie_id": "SSIS-406",
            "quality": "720p"  // 可选
        }
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({
                'success': False,
                'error': 'Invalid JSON'
            }), 400

        movie_id = data.get('movie_id', '').strip()
        quality = data.get('quality', '').strip() or None

        if not movie_id:
            return jsonify({
                'success': False,
                'error': 'movie_id is required'
            }), 400

        logger.info(f"POST 请求解析影片: {movie_id}, 质量: {quality or '默认'}")

        stream_url = resolver.resolve(movie_id, quality=quality)

        if stream_url:
            playback = build_playback_payload(movie_id, stream_url)
            return jsonify({
                'success': True,
                'movie_id': movie_id,
                'stream_url': stream_url,
                'playback': playback,
            }), 200
        else:
            return jsonify({
                'success': False,
                'movie_id': movie_id,
                'stream_url': None,
                'playback': None,
                'error': 'No stream URL found'
            }), 404

    except Exception as e:
        logger.error(f"POST 解析异常: {e}")
        return jsonify({
            'success': False,
            'playback': None,
            'error': str(e)
        }), 500


@app.errorhandler(404)
def not_found(error):
    """404 错误处理"""
    return jsonify({
        'success': False,
        'error': 'Not found'
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """500 错误处理"""
    logger.error(f"Internal error: {error}")
    return jsonify({
        'success': False,
        'error': 'Internal server error'
    }), 500


if __name__ == '__main__':
    logger.info(f"启动 MissAV 视频流服务...")
    logger.info(f"端口: {PORT}")
    logger.info(f"Base URL: {BASE_URL}")
    logger.info(f"日志级别: {LOG_LEVEL}")

    # 生产环境建议使用 gunicorn:
    # gunicorn -w 4 -b 0.0.0.0:5000 app:app
    app.run(host='0.0.0.0', port=PORT, debug=False)
