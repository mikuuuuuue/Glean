"""目录命名工具 - 冲突时追加数字后缀(FR-009a)。

提供:
  - safe_folder_name(): 清洗标题为合法文件夹名
  - unique_folder(): 检查目标目录存在性,冲突时追加 -1/-2/... 后缀
"""

import re
from pathlib import Path

# Windows 非法字符: < > : " / \\ | ? *
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*]')

# 文件夹名最大长度(含时间戳前缀)
_MAX_FOLDER_NAME_LENGTH = 50


def safe_folder_name(title: str, max_length: int = _MAX_FOLDER_NAME_LENGTH) -> str:
    """生成安全的文件夹名。

    - 移除 Windows 非法字符 (< > : " / \\ | ? *)
    - 截断至 max_length 字符
    - 去除首尾空格和点(Windows 不允许以点结尾)

    Args:
        title: 原始标题
        max_length: 最大长度

    Returns:
        清洗后的安全文件夹名
    """
    name = _INVALID_CHARS.sub("", title)
    name = name.strip(". ")
    if len(name) > max_length:
        name = name[:max_length].rstrip(". ")
    return name or "untitled"


def unique_folder(base: Path) -> Path:
    """检查目标目录是否存在,冲突时追加 -1/-2/... 后缀。

    不创建目录,仅返回不冲突的路径。

    Args:
        base: 期望的目录路径

    Returns:
        不冲突的路径(可能等于 base,也可能追加数字后缀)
    """
    if not base.exists():
        return base
    counter = 1
    while True:
        candidate = base.parent / f"{base.name}-{counter}"
        if not candidate.exists():
            return candidate
        counter += 1
