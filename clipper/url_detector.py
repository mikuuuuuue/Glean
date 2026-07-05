"""URL 类型检测模块(FR-001)。

提供结构化的 URL 类型识别,替代散落在各处的 ad-hoc 判断。

检测策略(优先级从高到低):
  1. ``bilibili_video``: B站视频链接(BV号、av号、b23.tv 短链、番剧播放页)
  2. ``web``: 可识别的网页链接(http/https 且有有效域名)
  3. ``unknown``: 无法识别——调用方 MUST 拒绝剪藏并向用户输出明确提示,
     不得进入抓取或解析流程(FR-001)。

设计说明:
  - 本模块为结构化检测的权威实现,保持自包含(不依赖 clipper.video 的配置加载),
    以便在剪藏入口前置校验时零副作用快速判定。
  - ``clip.is_bilibili_url``(自 ``clipper.video`` 导入)用于平台匹配,
    与本模块的 ``_is_bilibili`` 模式保持一致。

可观测性(宪法原则 V):
  - ``unknown`` 拒绝事件经 structlog 记录,便于追踪无效输入。
"""

import re
from typing import Literal

from clipper.logging import get_logger

_log = get_logger("clipper.url_detector")

# 检测结果类型
UrlType = Literal["bilibili_video", "web", "unknown"]

# B站视频 URL 模式: BV/av 视频页、b23.tv 短链、番剧播放页
_BILIBILI_PATTERNS = [
    r"bilibili\.com/video/(BV[\w]+|av\d+)",
    r"b23\.tv/[\w]+",
    r"bilibili\.com/bangumi/play/",
]

# 有效网页 URL: http(s) 且有至少一个点号的域名
_WEB_URL_PATTERN = r"^https?://[\w\-]+(\.[\w\-]+)+"


def detect_url_type(url: str) -> UrlType:
    """检测 URL 类型(FR-001)。

    Args:
        url: 待检测的 URL 字符串

    Returns:
        - ``"bilibili_video"``: B站视频链接
        - ``"web"``: 可识别的网页链接(http/https 且有有效域名)
        - ``"unknown"``: 无法识别,调用方应拒绝剪藏
    """
    # B站视频优先: BV号、av号、b23.tv短链、番剧
    if _is_bilibili(url):
        return "bilibili_video"
    # 网页: http(s) 且有有效域名
    if _is_valid_web_url(url):
        return "web"
    # 无法识别 → 调用方 MUST 拒绝剪藏(FR-001)
    _log.warning("url_type_unknown", url=url)
    return "unknown"


def _is_bilibili(url: str) -> bool:
    """判断 URL 是否为 B站视频链接(BV/av/b23.tv/番剧)。"""
    return any(re.search(p, url, re.IGNORECASE) for p in _BILIBILI_PATTERNS)


def _is_valid_web_url(url: str) -> bool:
    """判断 URL 是否为可识别的网页链接(http/https 且有有效域名)。"""
    return bool(re.match(_WEB_URL_PATTERN, url))


def should_reject(url: str) -> bool:
    """URL 是否应被拒绝剪藏(无法识别类型,FR-001)。

    Returns:
        True 表示该 URL 类型无法识别,调用方 MUST 拒绝剪藏并提示用户。
    """
    return detect_url_type(url) == "unknown"
