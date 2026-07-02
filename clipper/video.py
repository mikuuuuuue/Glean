"""视频剪藏模块 - B站(bili-cli) + YouTube(yt-dlp)

B站使用 bili-cli（Agent-Reach 首选，专为对抗B站风控设计）
YouTube 使用 yt-dlp（预留）

按需求 A6 调整：字幕照存，但不做 AI 总结；分类按视频标题+简介判定。
"""

import asyncio
import json as json_mod
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


def _load_config():
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


_CONFIG = _load_config()


def extract_bvid(url: str) -> Optional[str]:
    """从B站链接提取 BV 号或 av 号"""
    m = re.search(r"BV([\w]{10})", url)
    if m:
        return "BV" + m.group(1)
    m = re.search(r"av(\d+)", url, re.IGNORECASE)
    if m:
        return "av" + m.group(1)
    return None


async def resolve_b23(url: str) -> Optional[str]:
    """解析 b23.tv 短链接，返回真实 URL"""
    if "b23.tv" not in url:
        return url
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            location = resp.headers.get("Location", "")
            if location:
                return location
    except Exception:
        pass
    return url


# ═══════════════════════════════════════════════════════════
# B站：bili-cli（通过 subprocess 调用）
# ═══════════════════════════════════════════════════════════

async def clip_bilibili(url: str, output_dir: Path,
                        category: str = "视频与影音",
                        category_fn=None) -> dict:
    """
    用 bili-cli 提取 B站 视频信息与字幕，保存为 Markdown。

    category: 默认/兜底领域
    category_fn: 可选 callable(title, description)->分类名，拿到真实标题后会调用它
                 覆盖默认 category，使 md 头部写入真实领域。

    Returns:
        dict: {success, title, md_file, has_subtitle, description, cover_file, warnings, error}
    """
    result = {
        "success": False,
        "title": "未知视频",
        "md_file": None,
        "has_subtitle": False,
        "description": "",
        "cover_file": None,
        "warnings": [],
        "error": None,
    }

    # 检查 bili-cli 是否可用
    if not _bili_cli_available():
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / "video.md"
        md_path.write_text(
            _build_video_placeholder(
                url,
                "bili-cli 未安装，请执行: pipx install bilibili-cli 或 uv tool install bilibili-cli\n安装后首次使用需登录: bili login (扫码)",
                partial_info=[], category=category, status="失败",
            ),
            encoding="utf-8",
        )
        result["md_file"] = str(md_path)
        result["error"] = (
            "bili-cli 未安装，请执行: pipx install bilibili-cli 或 uv tool install bilibili-cli\n"
            "安装后首次使用需登录: bili login (扫码)"
        )
        return result

    # 解析 BV 号
    bvid = extract_bvid(url)
    if not bvid and "b23.tv" in url:
        resolved = await resolve_b23(url)
        if resolved != url:
            bvid = extract_bvid(resolved)
            if bvid:
                url = resolved

    if not bvid:
        # 失败占位 md（需求 6.4）
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / "video.md"
        md_path.write_text(
            _build_video_placeholder(
                url, "无法从URL提取BV号，请确认链接格式正确",
                partial_info=[], category=category, status="失败",
            ),
            encoding="utf-8",
        )
        result["md_file"] = str(md_path)
        result["error"] = "无法从URL提取BV号，请确认链接格式正确"
        return result

    try:
        # ── 获取视频信息 + 字幕（一条命令） ──
        raw = await _run_bili_cli(bvid)

        if raw is None:
            output_dir.mkdir(parents=True, exist_ok=True)
            md_path = output_dir / "video.md"
            md_path.write_text(
                _build_video_placeholder(
                    url, "bili-cli 执行失败，请确认已登录: bili login",
                    partial_info=[f"BV号：{bvid}"], category=category, status="失败",
                ),
                encoding="utf-8",
            )
            result["md_file"] = str(md_path)
            result["error"] = "bili-cli 执行失败，请确认已登录: bili login"
            return result

        # bili-cli JSON 输出格式: {"ok": true, "data": {...}, "error": null}
        if not raw.get("ok"):
            err_msg = raw.get("error", "未知错误")
            output_dir.mkdir(parents=True, exist_ok=True)
            md_path = output_dir / "video.md"
            md_path.write_text(
                _build_video_placeholder(
                    url, f"bili-cli 返回错误: {err_msg}",
                    partial_info=[f"BV号：{bvid}"], category=category, status="失败",
                ),
                encoding="utf-8",
            )
            result["md_file"] = str(md_path)
            result["error"] = f"bili-cli 返回错误: {err_msg}"
            return result

        data = raw.get("data", {})

        # ── 提取字段 ──
        title = data.get("title", "未知视频")
        desc = data.get("desc", "")
        pic = data.get("pic", "")
        owner = data.get("owner", {})
        uploader = owner.get("name", "未知UP主") if isinstance(owner, dict) else str(owner)
        stat = data.get("stat", {})
        duration = data.get("duration", 0)
        view_count = stat.get("view", 0) if isinstance(stat, dict) else 0
        like_count = stat.get("like", 0) if isinstance(stat, dict) else 0
        pubdate = data.get("pubdate", 0)

        result["title"] = title
        result["description"] = desc[:500] if desc else ""

        # 拿到真实标题后，用 category_fn 回算真实领域（覆盖默认）
        if category_fn is not None:
            try:
                category = category_fn(title, desc) or category
            except Exception:
                pass

        result["category"] = category

        # ── 字幕 ──
        subtitle_text = None
        subtitle_data = data.get("subtitle")
        if subtitle_data:
            # bili-cli 把字幕以纯文本或结构化形式返回
            if isinstance(subtitle_data, str):
                subtitle_text = subtitle_data.strip()
            elif isinstance(subtitle_data, list):
                # 结构化: [{"from": 0.0, "to": 1.5, "content": "文字"}, ...]
                lines = []
                for item in subtitle_data:
                    if isinstance(item, dict):
                        content = item.get("content", "").strip()
                        if content and (not lines or lines[-1] != content):
                            lines.append(content)
                subtitle_text = "\n".join(lines) if lines else None
            elif isinstance(subtitle_data, dict):
                # 可能嵌套在 dict 里
                body = subtitle_data.get("body", [])
                if body:
                    lines = []
                    for item in body:
                        content = item.get("content", "").strip()
                        if content and (not lines or lines[-1] != content):
                            lines.append(content)
                    subtitle_text = "\n".join(lines) if lines else None

        if subtitle_text:
            result["has_subtitle"] = True
        else:
            result["warnings"].append("该视频无字幕或字幕为空（可能需要登录 bili login）")

        # ── 格式化 ──
        mins, secs = divmod(duration or 0, 60)
        hours, mins_div = divmod(mins, 60)
        duration_str = f"{hours}:{mins_div:02d}:{secs:02d}" if hours else f"{mins_div}:{secs:02d}"

        if pubdate:
            from datetime import datetime as dt
            upload_date_fmt = dt.fromtimestamp(pubdate).strftime("%Y-%m-%d")
        else:
            upload_date_fmt = "未知"

        # ── 抓取状态（无字幕记部分失败） ──
        if subtitle_text:
            capture_status = "成功"
        else:
            capture_status = "部分失败"

        # ── 下载封面（T4）──
        if pic:
            cover_path = await _download_cover(pic, output_dir)
            if cover_path:
                result["cover_file"] = str(cover_path)

        # ── 构建 Markdown ──
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        md_lines = [
            f"# {title}",
            "",
            f"> 📅 剪藏时间：{now}",
            f"> 🔗 来源：[{url}]({url})",
            f"> 📺 类型：B站视频",
            f"> 🆔 BV号：{bvid}",
            f"> 📁 领域：{category}",
            f"> 🏷️ 来源类型：video",
            f"> 🌐 平台：bilibili",
            f"> 📅 发布日期：{upload_date_fmt}",
            f"> ✅ 抓取状态：{capture_status}",
            "",
            "---",
            "",
            "## 📹 视频信息",
            "",
            f"| 项目 | 内容 |",
            f"|------|------|",
            f"| **UP主** | {uploader} |",
            f"| **发布时间** | {upload_date_fmt} |",
            f"| **时长** | {duration_str} |",
            f"| **播放量** | {view_count:,} |",
            f"| **点赞** | {like_count:,} |",
        ]

        if result.get("cover_file"):
            md_lines.append(f"| **封面** | ![](cover{Path(result['cover_file']).suffix}) |")

        if desc:
            desc_text = desc[:2000] if len(desc) > 2000 else desc
            md_lines.extend(["", "## 📝 视频简介", "", desc_text])

        if subtitle_text:
            sub_text = subtitle_text[:10000] if len(subtitle_text) > 10000 else subtitle_text
            if len(subtitle_text) > 10000:
                sub_text += "\n\n> ⚠️ 字幕内容过长，已截断前10000字"
            md_lines.extend(["", "## 🎤 字幕内容", "", sub_text])
        else:
            md_lines.extend(["", "## 🎤 字幕内容", "", "> 字幕不可用，未生成总结"])

        md_lines.extend([
            "", "---", "",
            "## 📋 元数据", "",
            f"- **原始链接**：{url}",
            f"- **类型**：video",
            f"- **平台**：bilibili",
            f"- **BV号**：{bvid}",
            f"- **领域**：{category}",
            f"- **发布日期**：{upload_date_fmt}",
            f"- **抓取状态**：{capture_status}",
            f"- **剪藏时间**：{now}",
            f"- **UP主**：{uploader}",
        ])

        if result["warnings"]:
            md_lines.append("\n## ⚠️ 警告\n")
            for w in result["warnings"]:
                md_lines.append(f"- {w}")

        md_content = "\n".join(md_lines)
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / "video.md"
        md_path.write_text(md_content, encoding="utf-8")

        result["md_file"] = str(md_path)
        result["success"] = True
        result["capture_status"] = capture_status

    except Exception as e:
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / "video.md"
        md_path.write_text(
            _build_video_placeholder(
                url, f"B站视频处理异常: {e}",
                partial_info=[f"BV号：{bvid}"], category=category, status="失败",
            ),
            encoding="utf-8",
        )
        result["md_file"] = str(md_path)
        result["error"] = f"B站视频处理异常: {e}"

    return result


async def _download_cover(pic_url: str, output_dir: Path) -> Optional[Path]:
    """下载B站封面图到输出目录，返回本地路径"""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(pic_url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "").lower()
            ext = ".jpg"
            for ct, e in [("jpeg", ".jpg"), ("png", ".png"), ("webp", ".webp"), ("gif", ".gif")]:
                if ct in content_type:
                    ext = e
                    break
            output_dir.mkdir(parents=True, exist_ok=True)
            cover_path = output_dir / f"cover{ext}"
            cover_path.write_bytes(resp.content)
            return cover_path
    except Exception:
        return None


def _build_video_placeholder(url: str, reason: str, partial_info: list,
                             category: str = "视频与影音", status: str = "失败") -> str:
    """构建视频失败占位 md（需求 6.4）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# B站视频（抓取失败）",
        "",
        f"> 📅 剪藏时间：{now}",
        f"> 🔗 来源：[{url}]({url})",
        f"> 📺 类型：B站视频",
        f"> 📁 领域：{category}",
        f"> 🏷️ 来源类型：video",
        f"> 🌐 平台：bilibili",
        f"> ❌ 抓取状态：{status}",
        "",
        "---",
        "",
        "## ❗ 失败原因",
        "",
        reason,
        "",
    ]
    if partial_info:
        lines += ["## 📌 已获取信息", ""]
        lines += [f"- {info}" for info in partial_info]
        lines.append("")
    lines += [
        "---",
        "",
        "## 📋 元数据",
        "",
        f"- **原始链接**：{url}",
        f"- **类型**：video",
        f"- **平台**：bilibili",
        f"- **领域**：{category}",
        f"- **抓取状态**：{status}",
        f"- **剪藏时间**：{now}",
    ]
    return "\n".join(lines)


def _bili_cli_available() -> bool:
    """检查 bili-cli 是否已安装"""
    try:
        result = subprocess.run(
            ["bili", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


async def _run_bili_cli(bvid: str) -> Optional[dict]:
    """执行 bili-cli 并返回 JSON 结果"""
    loop = asyncio.get_event_loop()

    def _run():
        try:
            proc = subprocess.run(
                ["bili", "video", bvid, "--subtitle", "--json"],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode != 0:
                stderr = proc.stderr.strip()
                # 常见错误提示
                if "not logged in" in stderr.lower() or "login" in stderr.lower():
                    return {"ok": False, "error": "未登录，请执行 bili login 扫码登录"}
                return {"ok": False, "error": stderr or f"退出码 {proc.returncode}"}

            # 解析 JSON
            return json_mod.loads(proc.stdout)

        except json_mod.JSONDecodeError as e:
            return {"ok": False, "error": f"JSON 解析失败: {e}"}
        except FileNotFoundError:
            return {"ok": False, "error": "bili-cli 未安装"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "bili-cli 执行超时"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return await loop.run_in_executor(None, _run)


# ═══════════════════════════════════════════════════════════
# YouTube：yt-dlp（预留）
# ═══════════════════════════════════════════════════════════

async def clip_youtube(url: str, output_dir: Path) -> dict:
    """YouTube 视频处理（预留）"""
    return {
        "success": False,
        "title": "YouTube",
        "md_file": None,
        "has_subtitle": False,
        "description": "",
        "warnings": [],
        "error": "YouTube 支持尚未实现",
    }