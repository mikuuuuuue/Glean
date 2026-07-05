"""前置校验 - 文件大小与视频时长(FR-013b)。

在剪藏前检查文件/视频是否超过限制:
  - 单文件 ≤20MB(可配置)
  - 视频时长 ≤15分钟(可配置)

超限返回明确拒绝原因,不产生半成品目录。
"""

from pathlib import Path
from typing import Any

# 默认限制(与 config.example.yaml 一致)
_DEFAULT_MAX_FILE_SIZE_MB = 20
_DEFAULT_MAX_VIDEO_DURATION_MIN = 15


def validate_file_size(
    path: Path,
    max_mb: int = _DEFAULT_MAX_FILE_SIZE_MB,
) -> dict[str, Any]:
    """校验文件大小是否在限制内。

    Args:
        path: 文件路径
        max_mb: 最大允许大小(MB),默认 20

    Returns:
        {"valid": bool, "reason": str}
        - valid=True 时 reason 为空字符串
        - valid=False 时 reason 包含限制值与单位
    """
    p = Path(path)
    if not p.exists():
        return {"valid": False, "reason": f"文件不存在: {path}"}
    size_bytes = p.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    if size_mb > max_mb:
        return {
            "valid": False,
            "reason": f"文件大小 {size_mb:.1f}MB 超过限制 {max_mb}MB",
        }
    return {"valid": True, "reason": ""}


def validate_video_duration(
    duration_sec: float,
    max_min: int = _DEFAULT_MAX_VIDEO_DURATION_MIN,
) -> dict[str, Any]:
    """校验视频时长是否在限制内。

    Args:
        duration_sec: 视频时长(秒)
        max_min: 最大允许时长(分钟),默认 15

    Returns:
        {"valid": bool, "reason": str}
        - valid=True 时 reason 为空字符串
        - valid=False 时 reason 包含限制值(分钟)与"分钟"字样
    """
    duration_min = duration_sec / 60.0
    if duration_min > max_min:
        return {
            "valid": False,
            "reason": f"视频时长 {duration_min:.1f}分钟 超过限制 {max_min}分钟",
        }
    return {"valid": True, "reason": ""}
