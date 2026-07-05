"""结构化日志配置 - structlog,与 result["warnings"] 职责分离。

职责划分(宪法原则 V):
  - structlog: 机器可读的运行日志(抓取后端、耗时、降级事件、错误)
  - result["warnings"]: 面向用户的剪藏结果摘要(图片下载失败等)

使用方式:
    from clipper.logging import get_logger
    log = get_logger(__name__)
    log.info("clip_start", url=url, backend="httpx")
"""

import logging
import sys

import structlog


def configure_logging() -> None:
    """配置 structlog(进程级,仅首次调用生效)。

    使用 ConsoleRenderer 输出人类可读的彩色日志,
    同时保留 structlog 的结构化字段以便后续扩展为 JSON 输出。
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


# 模块导入时自动配置
configure_logging()


def get_logger(name: str = "clipper") -> structlog.stdlib.BoundLogger:
    """获取 structlog logger。

    Args:
        name: logger 名称,通常传 __name__

    Returns:
        structlog BoundLogger 实例
    """
    return structlog.get_logger(name)  # type: ignore[no-any-return]
