"""B站平台适配器(FR-004)。

封装现有 ``clipper.video.clip_bilibili``,实现 ``PlatformAdapter`` 接口,
为多平台扩展提供统一接入点。v1 仅 B站可用,其他平台(YouTube 等)预留。
"""

from pathlib import Path
from typing import Any

from clipper.logging import get_logger
from clipper.platform_base import PlatformAdapter
from clipper.video import clip_bilibili, is_bilibili_url

_log = get_logger("clipper.platform_bilibili")


class BilibiliAdapter(PlatformAdapter):
    """B站视频剪藏适配器。

    - ``matches``: 复用 ``is_bilibili_url`` 判断 BV/av/b23.tv/番剧链接
    - ``clip``: 委托给 ``clip_bilibili``,保持原有抓取与字幕/ASR 回退逻辑
    """

    @property
    def platform_name(self) -> str:
        return "bilibili"

    def matches(self, url: str) -> bool:
        matched = is_bilibili_url(url)
        _log.debug("platform_match", platform=self.platform_name, url=url, matched=matched)
        return matched

    async def clip(self, url: str, output_dir: Path, **kwargs: Any) -> dict[str, Any]:
        _log.info("platform_clip_start", platform=self.platform_name, url=url)
        result = await clip_bilibili(url, output_dir, **kwargs)
        _log.info(
            "platform_clip_complete",
            platform=self.platform_name,
            url=url,
            success=result.get("success"),
            subtitle_source=result.get("subtitle_source"),
        )
        return result
