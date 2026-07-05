"""多平台适配器抽象基类(FR-004 扩展接入点)。

v1 视频剪藏以 B站为主,架构为其他平台(YouTube 等)预留可扩展的接入点。
每个平台实现一个 ``PlatformAdapter`` 子类,封装该平台的抓取逻辑,
调用方通过 ``matches(url)`` 选择适配器,再统一调用 ``clip(url, output_dir, ...)``。

职责划分(宪法原则 V):
  - structlog: 适配器选择、抓取后端切换等运行日志
  - result["warnings"]: 面向用户的剪藏结果摘要
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class PlatformAdapter(ABC):
    """多平台适配器抽象基类(FR-004 扩展接入点)。

    子类 MUST 实现以下三个抽象成员:
      - ``platform_name``: 平台标识(如 "bilibili"、"youtube")
      - ``matches(url)``: 判断 URL 是否属于此平台
      - ``clip(url, output_dir, ...)``: 执行剪藏,返回标准结果 dict

    返回结果 dict 约定(与 ``clip_bilibili`` 等现有函数一致):
      ``{success, title, md_file, ...}``
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """平台名称(小写标识,如 "bilibili")。"""
        ...

    @abstractmethod
    def matches(self, url: str) -> bool:
        """检查 URL 是否属于此平台。

        Args:
            url: 待检测的 URL

        Returns:
            True 表示此适配器可处理该 URL
        """
        ...

    @abstractmethod
    async def clip(self, url: str, output_dir: Path, **kwargs: Any) -> dict[str, Any]:
        """剪藏指定平台 URL。

        Args:
            url: 平台视频/内容链接
            output_dir: 归档输出目录
            **kwargs: 平台特定参数(如 category、category_fn)

        Returns:
            dict: ``{success, title, md_file, ...}``
        """
        ...
