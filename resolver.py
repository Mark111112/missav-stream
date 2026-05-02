"""
MissAV 视频流解析器
从 MissAV.ai 获取视频流 m3u8 URL
"""

import logging
import time
import re
from typing import Optional
from urllib.parse import urlparse

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 尝试导入 curl_cffi（推荐，更好地绕过 Cloudflare）
try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
    logger.info("curl_cffi 可用，将优先使用")
except ImportError:
    curl_requests = None
    CURL_CFFI_AVAILABLE = False
    logger.warning("curl_cffi 未安装，将使用标准 requests 库")

import requests

# 常量定义
VIDEO_M3U8_PREFIX = 'https://surrit.com/'
VIDEO_PLAYLIST_SUFFIX = '/playlist.m3u8'

# 匹配模式（按优先级顺序）
MATCH_PATTERNS = [
    r'm3u8\|([a-f0-9\|]+)\|com\|surrit\|https\|video',
    r'https://surrit\.com/([a-f0-9-]+)/playlist\.m3u8',
    r'''video[^>]*src=["']+(https://surrit\.com/[^"']+)["']+''',
    r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',
    r'https?://[^"\'<>\s]+\.m3u8',
]

RESOLUTION_PATTERN = r'RESOLUTION=(\d+)x(\d+)'

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Cache-Control': 'max-age=0',
    'Connection': 'keep-alive',
    'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'same-origin',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1',
    'DNT': '1',
}


class VideoResolver:
    """MissAV 视频流解析器"""

    def __init__(
        self,
        base_url: str = 'https://missav.ai',
        retry: int = 3,
        delay: int = 2,
        timeout: int = 15,
    ):
        """
        初始化解析器

        Args:
            base_url: MissAV 网站基础 URL
            retry: 重试次数
            delay: 重试延迟（秒）
            timeout: 请求超时（秒）
        """
        self.base_url = base_url.rstrip('/')
        self.retry = retry
        self.delay = delay
        self.timeout = timeout
        self.direct_url = None
        self._session = None

    @property
    def session(self):
        """懒加载 requests session"""
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update(DEFAULT_HEADERS.copy())
        return self._session

    def resolve(self, movie_id: str, quality: Optional[str] = None) -> Optional[str]:
        """
        解析影片 ID 获取视频流 URL

        Args:
            movie_id: 影片 ID（如 SSIS-406）
            quality: 视频质量（如 '720p', '1080p'），默认最高质量

        Returns:
            视频 m3u8 流 URL，失败返回 None
        """
        movie_url = f"{self.base_url}/{movie_id}"
        logger.info(f"解析影片: {movie_id}")

        # 1. 获取页面内容并提取元数据
        metadata = self._fetch_metadata(movie_url)
        if not metadata:
            logger.error(f"无法获取影片元数据: {movie_id}")
            return None

        # 2. 如果是直接 URL 标记，返回保存的直接 URL
        if metadata == "direct_url":
            if self.direct_url:
                logger.info(f"使用直接 m3u8 URL")
                return self.direct_url
            return None

        # 3. UUID 标准处理
        playlist_url = f"{VIDEO_M3U8_PREFIX}{metadata}{VIDEO_PLAYLIST_SUFFIX}"
        logger.info(f"播放列表 URL: {playlist_url}")

        # 4. 获取播放列表内容
        playlist_content = self._fetch_playlist(playlist_url)
        if not playlist_content:
            logger.warning("无法获取播放列表内容，返回主列表 URL")
            return playlist_url

        # 5. 解析播放列表获取指定质量的流 URL
        return self._parse_playlist(playlist_url, playlist_content, quality)

    def _fetch_with_curl_cffi(self, url: str, cookies: dict = None) -> Optional[str]:
        """使用 curl_cffi 获取页面内容（更好地绕过 Cloudflare）"""
        if not CURL_CFFI_AVAILABLE:
            return None

        # 尝试多个浏览器版本，按优先级排序
        impersonate_versions = [
            "chrome124",  # 最新 Chrome
            "chrome120",
            "chrome116",
            "chrome110",
            "edge119",   # 尝试 Edge
            "edge99",
        ]

        for version in impersonate_versions:
            try:
                logger.debug(f"尝试 curl_cffi 伪装: {version}")
                response = curl_requests.get(
                    url=url,
                    headers=DEFAULT_HEADERS,
                    cookies=cookies,
                    impersonate=version,
                    timeout=self.timeout,
                    verify=False,
                )
                if response.status_code == 200:
                    logger.info(f"curl_cffi 请求成功 (使用 {version})")
                    return response.text
                elif response.status_code == 403:
                    logger.warning(f"curl_cffi ({version}) 请求返回 403")
                    # 继续尝试下一个版本
                else:
                    logger.warning(f"curl_cffi ({version}) 请求返回 {response.status_code}")
                    # 非 403 错误，可能是其他问题，继续尝试
            except Exception as e:
                logger.debug(f"curl_cffi ({version}) 请求失败: {e}")
                # 继续尝试下一个版本

        return None

    def _fetch_with_requests(self, url: str, cookies: dict = None) -> Optional[str]:
        """使用标准 requests 获取页面内容"""
        try:
            for attempt in range(1, self.retry + 1):
                try:
                    response = self.session.get(
                        url,
                        cookies=cookies,
                        timeout=self.timeout,
                        allow_redirects=True,
                    )

                    if response.status_code == 200:
                        logger.debug(f"requests 请求成功 (尝试 {attempt}/{self.retry})")
                        return response.text

                    elif response.status_code == 403:
                        # 尝试添加随机头部绕过
                        import random
                        import string
                        rand_str = ''.join(random.choices(string.ascii_letters + string.digits, k=8))

                        headers = {"X-Requested-With": f"XMLHttpRequest-{rand_str}"}
                        self.session.headers.update(headers)

                        if cookies:
                            cookies["missav_session"] = rand_str
                        else:
                            cookies = {"missav_session": rand_str, "age_verify": "true"}

                        domain = urlparse(url).netloc
                        self.session.cookies.set("missav_session", rand_str, domain=domain)

                        logger.info(f"收到 403，尝试绕过 (尝试 {attempt}/{self.retry})")
                        time.sleep(self.delay)

                    else:
                        logger.warning(f"HTTP {response.status_code} (尝试 {attempt}/{self.retry})")
                        time.sleep(self.delay)

                except requests.exceptions.Timeout:
                    logger.error(f"请求超时 (尝试 {attempt}/{self.retry})")
                    if attempt < self.retry:
                        time.sleep(self.delay)
                except Exception as e:
                    logger.error(f"请求失败: {e} (尝试 {attempt}/{self.retry})")
                    if attempt < self.retry:
                        time.sleep(self.delay)

        except Exception as e:
            logger.error(f"_fetch_with_requests 异常: {e}")

        return None

    def _fetch_metadata(self, movie_url: str) -> Optional[str]:
        """获取影片元数据（UUID 或直接 m3u8 URL）"""
        domain = urlparse(movie_url).netloc
        cookies = {"age_verify": "true"}
        self.session.cookies.set("age_verify", "true", domain=domain)

        # 优先使用 curl_cffi
        html = self._fetch_with_curl_cffi(movie_url, cookies=cookies)

        # 回退到标准 requests
        if not html:
            logger.debug("curl_cffi 失败，使用标准 requests")
            html = self._fetch_with_requests(movie_url, cookies=cookies)

        if not html:
            return None

        # 尝试匹配模式
        return self._extract_metadata(html)

    def _extract_metadata(self, html: str) -> Optional[str]:
        """从 HTML 中提取视频元数据"""
        direct_m3u8_url = None

        for i, pattern in enumerate(MATCH_PATTERNS):
            match = re.search(pattern, html)
            if match:
                logger.info(f"匹配到模式 {i + 1}")

                if i == 0:  # 特殊 UUID 格式
                    result = match.group(1)
                    uuid = "-".join(result.split("|")[::-1])
                    if self._is_valid_uuid(uuid):
                        logger.info(f"UUID 有效: {uuid}")
                        return uuid

                elif i == 1:  # surrit.com URL 中的 UUID
                    uuid = match.group(1)
                    if self._is_valid_uuid(uuid):
                        logger.info(f"UUID 有效: {uuid}")
                        return uuid

                elif i == 2:  # video 标签 src
                    url_part = match.group(1)
                    if url_part.endswith('.m3u8'):
                        logger.info(f"找到直接 m3u8")
                        direct_m3u8_url = url_part
                    else:
                        uuid_match = re.search(r'/([a-f0-9-]+)/', url_part)
                        if uuid_match:
                            uuid = uuid_match.group(1)
                            if self._is_valid_uuid(uuid):
                                logger.info(f"UUID 有效: {uuid}")
                                return uuid

                elif i == 3:  # 标准 UUID
                    uuid = match.group(0)
                    if self._is_valid_uuid(uuid):
                        logger.info(f"UUID 有效: {uuid}")
                        return uuid

                elif i in (4, 5):  # 直接 m3u8 链接
                    direct_m3u8_url = match.group(1) if i == 5 else match.group(0)
                    logger.info(f"找到直接 m3u8")

        # 如果找到直接 m3u8 但没找到 UUID
        if direct_m3u8_url:
            logger.info(f"未找到 UUID，使用直接 m3u8")
            self.direct_url = direct_m3u8_url
            return "direct_url"

        logger.error("无法提取视频元数据")
        return None

    def _fetch_playlist(self, url: str) -> Optional[str]:
        """获取播放列表内容"""
        referer = self.base_url + '/'
        playlist_headers = {
            **DEFAULT_HEADERS,
            'Referer': referer,
            'Origin': self.base_url,
        }

        # 优先使用 curl_cffi
        if CURL_CFFI_AVAILABLE:
            try:
                response = curl_requests.get(
                    url,
                    headers=playlist_headers,
                    impersonate="chrome110",
                    timeout=self.timeout,
                )
                if response.status_code == 200:
                    return response.text
                logger.warning(f"获取播放列表失败 (curl_cffi): HTTP {response.status_code}")
            except Exception as e:
                logger.debug(f"获取播放列表失败 (curl_cffi): {e}")

        # 回退到标准 requests
        try:
            response = self.session.get(url, headers=playlist_headers, timeout=self.timeout)
            if response.status_code == 200:
                return response.text
            logger.warning(f"获取播放列表失败 (requests): HTTP {response.status_code}")
        except Exception as e:
            logger.error(f"获取播放列表失败 (requests): {e}")

        return None

    def _parse_playlist(self, playlist_url: str, content: str, quality: Optional[str] = None) -> Optional[str]:
        """解析播放列表获取指定质量的流 URL"""
        try:
            matches = re.findall(RESOLUTION_PATTERN, content)
            if not matches:
                logger.info("没有分辨率信息，返回主列表 URL")
                return playlist_url

            # 构建质量映射
            quality_map = {int(h): int(w) for w, h in matches}
            quality_list = sorted(quality_map.keys())

            # 选择质量
            if quality:
                quality_cleaned = quality.lower().replace('p', '')
                try:
                    target = int(quality_cleaned)
                except ValueError:
                    target = None
            else:
                target = None

            # 选择最接近的质量
            if target is None:
                selected = quality_list[-1]
                logger.info(f"选择最高质量: {selected}p")
            else:
                selected = min(quality_list, key=lambda x: abs(x - target))
                logger.info(f"选择质量: {selected}p (请求: {quality})")

            width = quality_map[selected]
            url_patterns = [
                f"{width}x{selected}/video.m3u8",
                f"{selected}p/video.m3u8",
            ]

            # 查找匹配的 URL
            for pattern in url_patterns:
                if pattern in content:
                    lines = content.splitlines()
                    for line in lines:
                        if pattern in line and not line.strip().startswith('#'):
                            logger.info(f"找到流 URL")
                            if line.startswith('http'):
                                return line.strip()
                            # 相对路径处理
                            base_url = '/'.join(playlist_url.split('/')[:-1])
                            return f"{base_url}/{line.strip()}"

            # 使用最后一个非注释行
            non_comment = [l.strip() for l in content.splitlines() if l.strip() and not l.strip().startswith('#')]
            if non_comment:
                result = non_comment[-1]
                if result.startswith('http'):
                    return result
                base_url = '/'.join(playlist_url.split('/')[:-1])
                return f"{base_url}/{result}"

            return playlist_url

        except Exception as e:
            logger.error(f"解析播放列表失败: {e}")
            return playlist_url

    @staticmethod
    def _is_valid_uuid(uuid: str) -> bool:
        """验证 UUID 格式"""
        return bool(re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', uuid))
