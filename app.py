"""
MissAV 视频流服务
独立的 Flask 服务，用于解析 MissAV.ai 视频流 URL
"""

import os
import logging
from flask import Flask, request, jsonify
from resolver import VideoResolver

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

# 设置日志级别
if LOG_LEVEL == 'DEBUG':
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger('resolver').setLevel(logging.DEBUG)
elif LOG_LEVEL == 'WARNING':
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger('resolver').setLevel(logging.WARNING)

# 创建解析器实例
resolver = VideoResolver(base_url=BASE_URL, retry=3, delay=2, timeout=15)


@app.route('/health', methods=['GET'])
def health_check():
    """健康检查端点"""
    return jsonify({
        'status': 'healthy',
        'service': 'missav-stream',
        'base_url': BASE_URL
    })


@app.route('/api/resolve/<movie_id>', methods=['GET'])
def resolve_movie(movie_id: str):
    """
    解析影片 ID 获取视频流 URL

    Args:
        movie_id: 影片 ID（路径参数），如 SSIS-406

    Query Parameters:
        quality: 视频质量（可选），如 720p, 1080p

    Returns:
        JSON 响应:
        {
            "success": true/false,
            "movie_id": "影片ID",
            "stream_url": "m3u8流URL 或 null",
            "error": "错误信息（失败时）"
        }
    """
    quality = request.args.get('quality', '').strip() or None

    logger.info(f"请求解析影片: {movie_id}, 质量: {quality or '默认'}")

    try:
        stream_url = resolver.resolve(movie_id, quality=quality)

        if stream_url:
            logger.info(f"解析成功: {movie_id}")
            return jsonify({
                'success': True,
                'movie_id': movie_id,
                'stream_url': stream_url,
            }), 200
        else:
            logger.warning(f"解析失败: {movie_id}")
            return jsonify({
                'success': False,
                'movie_id': movie_id,
                'stream_url': None,
                'error': 'No stream URL found'
            }), 404

    except Exception as e:
        logger.error(f"解析异常: {movie_id}, 错误: {e}")
        return jsonify({
            'success': False,
            'movie_id': movie_id,
            'stream_url': None,
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
            return jsonify({
                'success': True,
                'movie_id': movie_id,
                'stream_url': stream_url,
            }), 200
        else:
            return jsonify({
                'success': False,
                'movie_id': movie_id,
                'stream_url': None,
                'error': 'No stream URL found'
            }), 404

    except Exception as e:
        logger.error(f"POST 解析异常: {e}")
        return jsonify({
            'success': False,
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
