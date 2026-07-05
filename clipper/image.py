"""图片剪藏模块 - 原图存档 + 留识图描述占位

识图（OCR / 内容描述）由 clawbot agent 自身视觉能力完成，本模块只负责：
  1. 把原图存入条目目录；
  2. 生成 md，每张图位置写本地相对路径 + 描述占位；
  3. 写元信息头。
"""

import contextlib
import hashlib
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from clipper.logging import get_logger

_log = get_logger("clipper.image")


def file_content_hash(file_path: Path) -> str:
    """计算文件内容 SHA1 短哈希，用于查重"""
    h = hashlib.sha1()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()[:16]


def clip_image(
    image_paths: list[Any],
    output_dir: Path,
    category: str = "其他收藏",
    source_url: str | None = None,
    category_fn: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """
    把一组图片剪藏。

    image_paths: 本地图片路径列表
    category_fn: 可选 callable(title, description)->分类名（image 无文本，可简单回退）

    Returns:
        dict: {success, title, md_file, content_hash, files, warnings, error}
    """
    result: dict[str, Any] = {
        "success": False,
        "title": "图片剪藏",
        "md_file": None,
        "content_hash": None,
        "files": [],
        "warnings": [],
        "error": None,
        "fetch_backend": "local",  # FR-012
    }

    # 校验图片
    valid = [Path(p) for p in image_paths if Path(p).exists() and Path(p).is_file()]
    if not valid:
        result["error"] = "没有有效的图片文件"
        return result

    # FR-013b: 文件大小前置校验
    from clipper.validators import validate_file_size

    for img in valid:
        size_ok, size_err = validate_file_size(img)
        if not size_ok:
            result["warnings"].append(size_err)
            _log.warning("image_size_exceeded", src=str(img))

    # 以第一张图的内容哈希作为整组查重标识
    content_hash = file_content_hash(valid[0])
    result["content_hash"] = content_hash

    output_dir.mkdir(parents=True, exist_ok=True)

    # 保存原图（命名：序号-原名）
    saved_files = []
    for idx, src in enumerate(valid, 1):
        ext = src.suffix or ".png"
        dest_name = f"{idx:02d}-{src.name}" if src.name else f"{idx:02d}{ext}"
        dest = output_dir / dest_name
        try:
            shutil.copy2(str(src), str(dest))
            saved_files.append(dest_name)
        except Exception as e:
            result["warnings"].append(f"保存图片 {src.name} 失败: {e}")
            _log.warning("image_save_failed", src=str(src), error=str(e))

    # 标题：用第一张图名（去扩展名）
    title = valid[0].stem or "图片剪藏"
    result["title"] = title

    # 回算领域（可选；图片无文本描述）
    if category_fn is not None:
        with contextlib.suppress(Exception):
            category = category_fn(title, "") or category
    result["category"] = category

    # 构建 md
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md_lines = [
        f"# {title}",
        "",
        f"> 📅 剪藏时间：{now}",
        "> 🏷️ 来源类型：image",
        f"> 📁 领域：{category}",
        "> ✅ 抓取状态：成功",
        (f"> 🔗 来源：[{source_url}]({source_url})" if source_url else ""),
        "",
        "---",
        "",
        f"## 🖼️ 图片（共 {len(saved_files)} 张）",
        "",
    ]
    for idx, (name, orig) in enumerate(zip(saved_files, valid, strict=False), 1):
        md_lines += [
            f"### 图 {idx}：{orig.name}",
            "",
            f"![{orig.name}]({name})",
            "",
            "<!-- agent-describe: 请 clawbot 识图后在此填写 OCR 识别的文字与一句话描述 -->",
            "",
            f"- 本地路径：`{name}`",
            "",
        ]

    md_lines += [
        "---",
        "",
        "## 📋 元数据",
        "",
        "- **来源类型**：image",
        f"- **领域**：{category}",
        "- **抓取状态**：成功",
        f"- **图片数量**：{len(saved_files)}",
        f"- **内容哈希**：{content_hash}",
        f"- **剪藏时间**：{now}",
    ]
    if source_url:
        md_lines.append(f"- **来源链接**：{source_url}")
    md_lines += [f"- **原始文件名**：{', '.join(p.name for p in valid)}"]

    if result["warnings"]:
        md_lines += ["", "## ⚠️ 警告", ""]
        for w in result["warnings"]:
            md_lines.append(f"- {w}")

    md_path = output_dir / "image.md"
    md_path.write_text("\n".join(filter(None, md_lines)), encoding="utf-8")

    result["md_file"] = str(md_path)
    result["files"] = [str(output_dir / n) for n in saved_files]
    result["success"] = True
    return result
