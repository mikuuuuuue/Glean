"""视频剪藏模块 - B站(bili-cli) + YouTube(yt-dlp)

B站使用 bili-cli（Agent-Reach 首选，专为对抗B站风控设计）
YouTube 使用 yt-dlp（预留）

按需求 A6 调整：字幕照存，但不做 AI 总结；分类按视频标题+简介判定。
"""

import asyncio
import contextlib
import json as json_mod
import re
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from clipper.config import ConfigProxy
from clipper.logging import get_logger

_CONFIG = ConfigProxy()
_log = get_logger("clipper.video")


def extract_bvid(url: str) -> str | None:
    """从B站链接提取 BV 号或 av 号"""
    m = re.search(r"BV([\w]{10})", url)
    if m:
        return "BV" + m.group(1)
    m = re.search(r"av(\d+)", url, re.IGNORECASE)
    if m:
        return "av" + m.group(1)
    return None


# B站 URL 匹配模式: BV/av 视频页、b23.tv 短链、番剧播放页
BILIBILI_PATTERNS = [
    r"bilibili\.com/video/(BV[\w]+|av\d+)",
    r"b23\.tv/[\w]+",
    r"bilibili\.com/bangumi/play/",
]


def is_bilibili_url(url: str) -> bool:
    """判断是否为 B站 视频链接。

    匹配范围:
      - ``bilibili.com/video/BVxxxxxxxxxx`` 或 ``av数字``
      - ``b23.tv/xxxx`` 短链
      - ``bilibili.com/bangumi/play/`` 番剧

    此为 clipper 包内的规范实现,``clip.py`` 通过导入复用以保持向后兼容。
    """
    return any(re.search(pattern, url, re.IGNORECASE) for pattern in BILIBILI_PATTERNS)


async def resolve_b23(url: str) -> str | None:
    """解析 b23.tv 短链接，返回真实 URL"""
    if "b23.tv" not in url:
        return url
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            location: str = resp.headers.get("Location", "")
            if location:
                return location
    except Exception:
        pass
    return url


async def resolve_av_to_bv(bvid: str) -> str:
    """将 av 号转为 BV 号（bili-cli 不支持 av 格式）。

    通过 B站 API: https://api.bilibili.com/x/web-interface/view?aid=XXX
    处理两种情况：
    1. 普通视频：data.bvid 存在
    2. 合集视频：data.episodes[0].bvid 存在（取第一集）
    """
    if not bvid or not bvid.lower().startswith("av"):
        return bvid
    aid = bvid[2:]  # 去掉 "av" 前缀
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            resp = await client.get(
                f"https://api.bilibili.com/x/web-interface/view?aid={aid}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data: Any = resp.json()
            if data.get("code") == 0:
                d = data.get("data", {})
                # 普通视频
                if d.get("bvid"):
                    return str(d["bvid"])
                # 合集视频：取第一集的 BV 号
                episodes = d.get("episodes") or []
                if episodes:
                    _log.info("av_resolved_to_season", aid=aid, episode_count=len(episodes))
                    return str(episodes[0].get("bvid", bvid))
    except Exception:
        pass
    return bvid  # 转换失败返回原值


# ═══════════════════════════════════════════════════════════
# B站：bili-cli（通过 subprocess 调用）
# ═══════════════════════════════════════════════════════════


async def clip_bilibili(
    url: str,
    output_dir: Path,
    category: str = "视频与影音",
    category_fn: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """
    用 bili-cli 提取 B站 视频信息与字幕，保存为 Markdown。

    category: 默认/兜底领域
    category_fn: 可选 callable(title, description)->分类名，拿到真实标题后会调用它
                 覆盖默认 category，使 md 头部写入真实领域。

    Returns:
        dict: {success, title, md_file, has_subtitle, description, cover_file, warnings, error}
    """
    result: dict[str, Any] = {
        "success": False,
        "title": "未知视频",
        "md_file": None,
        "has_subtitle": False,
        "subtitle_source": None,
        "transcript_file": None,
        "description": "",
        "cover_file": None,
        "warnings": [],
        "error": None,
        "fetch_backend": "bili-cli",  # FR-012
    }

    # 检查 bili-cli 是否可用
    if not _bili_cli_available():
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / "video.md"
        md_path.write_text(
            _build_video_placeholder(
                url,
                "bili-cli 未安装，请执行: pipx install bilibili-cli 或 uv tool install bilibili-cli\n安装后首次使用需登录: bili login (扫码)",
                partial_info=[],
                category=category,
                status="失败",
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
        if resolved and resolved != url:
            bvid = extract_bvid(resolved)
            if bvid:
                url = resolved

    # av 号转为 BV 号（bili-cli 不支持 av 格式）
    if bvid and bvid.lower().startswith("av"):
        bv = await resolve_av_to_bv(bvid)
        if bv != bvid:
            bvid = bv

    if not bvid:
        # 失败占位 md（需求 6.4）
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / "video.md"
        md_path.write_text(
            _build_video_placeholder(
                url,
                "无法从URL提取BV号，请确认链接格式正确",
                partial_info=[],
                category=category,
                status="失败",
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
                    url,
                    "bili-cli 执行失败，请确认已登录: bili login",
                    partial_info=[f"BV号：{bvid}"],
                    category=category,
                    status="失败",
                ),
                encoding="utf-8",
            )
            result["md_file"] = str(md_path)
            result["error"] = "bili-cli 执行失败，请确认已登录: bili login"
            _log.warning("bili_cli_failed", url=url, bvid=bvid)
            return result

        # bili-cli JSON 输出格式: {"ok": true, "data": {...}, "error": null}
        if not raw.get("ok"):
            err_msg = raw.get("error", "未知错误")
            output_dir.mkdir(parents=True, exist_ok=True)
            md_path = output_dir / "video.md"
            md_path.write_text(
                _build_video_placeholder(
                    url,
                    f"bili-cli 返回错误: {err_msg}",
                    partial_info=[f"BV号：{bvid}"],
                    category=category,
                    status="失败",
                ),
                encoding="utf-8",
            )
            result["md_file"] = str(md_path)
            result["error"] = f"bili-cli 返回错误: {err_msg}"
            return result

        data = raw.get("data", {})

        # ── 提取字段（兼容 bili-cli 新旧 schema） ──
        # v0.6.2: data.video.{title,description,owner,stats,duration_seconds}
        # 旧版:   data.{title,desc,owner,stat,duration}
        video_data = data.get("video", data) if isinstance(data.get("video"), dict) else data
        title = video_data.get("title", "未知视频")
        desc = video_data.get("description", "") or video_data.get("desc", "")
        pic = video_data.get("pic", "")
        owner = video_data.get("owner", {})
        uploader = owner.get("name", "未知UP主") if isinstance(owner, dict) else str(owner)
        stat = video_data.get("stats", video_data.get("stat", {}))
        duration = video_data.get("duration_seconds", video_data.get("duration", 0))
        if not isinstance(duration, int):
            duration = 0

        # FR-013b: 视频时长前置校验
        from clipper.validators import validate_video_duration

        dur_ok, dur_err = validate_video_duration(duration)
        if not dur_ok:
            _log.warning("video_duration_exceeded", bvid=bvid, duration=duration)
            result["warnings"].append(dur_err)
        view_count = stat.get("view", 0) if isinstance(stat, dict) else 0
        like_count = stat.get("like", 0) if isinstance(stat, dict) else 0
        pubdate = video_data.get("pubdate", 0)

        result["title"] = title
        result["description"] = desc[:500] if desc else ""

        # 拿到真实标题后，用 category_fn 回算真实领域（覆盖默认）
        if category_fn is not None:
            with contextlib.suppress(Exception):
                category = category_fn(title, desc) or category

        result["category"] = category

        # ── 字幕 ──
        subtitle_text = None
        subtitle_data = data.get("subtitle")
        if subtitle_data:
            # bili-cli v0.6.2: {"available": bool, "format": "plain", "text": "...", "items": [...]}
            if isinstance(subtitle_data, dict):
                if subtitle_data.get("available", False) is False:
                    # v0.6.2 明确标记无字幕
                    subtitle_text = None
                    # T076: 检查是否因未登录导致
                    raw_cli = data.get("_raw_stderr", "")
                    if (
                        "Credential" in raw_cli
                        or "sessdata" in raw_cli
                        or "login" in raw_cli.lower()
                    ):
                        result["warnings"].append(
                            "bili-cli 未登录，运行 `bili login` 扫码登录后可获取官方字幕"
                        )
                        _log.info("subtitle_login_required", bvid=bvid)
                    else:
                        result["warnings"].append("该视频无官方字幕，将尝试 ASR 转写")
                else:
                    # 优先用 text 字段（纯文本）
                    text = subtitle_data.get("text", "").strip()
                    if text:
                        subtitle_text = text
                    else:
                        # 回退到 items 结构化数据
                        items = subtitle_data.get("items", [])
                        if items:
                            lines: list[str] = []
                            for item in items:
                                if isinstance(item, dict):
                                    content = item.get("content", "").strip()
                                    if content and (not lines or lines[-1] != content):
                                        lines.append(content)
                            subtitle_text = "\n".join(lines) if lines else None
                        # 旧版可能嵌套在 body 里
                        if not subtitle_text:
                            body = subtitle_data.get("body", [])
                            if body:
                                lines = []
                                for item in body:
                                    content = (
                                        item.get("content", "").strip()
                                        if isinstance(item, dict)
                                        else ""
                                    )
                                    if content and (not lines or lines[-1] != content):
                                        lines.append(content)
                                subtitle_text = "\n".join(lines) if lines else None
            elif isinstance(subtitle_data, str):
                subtitle_text = subtitle_data.strip()
            elif isinstance(subtitle_data, list):
                # 旧版结构化: [{"from": 0.0, "to": 1.5, "content": "文字"}, ...]
                lines = []
                for item in subtitle_data:
                    if isinstance(item, dict):
                        content = item.get("content", "").strip()
                        if content and (not lines or lines[-1] != content):
                            lines.append(content)
                subtitle_text = "\n".join(lines) if lines else None

        subtitle_source = "official" if subtitle_text else None

        if subtitle_text:
            result["has_subtitle"] = True
        else:
            # ── 无官方字幕 → 分级 ASR 回退 ──
            asr_cfg = _CONFIG.get("asr", {}) or {}
            if asr_cfg.get("enabled", False):
                from clipper.asr import transcribe_with_fallback

                audio_dir = Path(asr_cfg.get("audio_dir") or "") or output_dir
                audio_path = await download_bilibili_audio(bvid, audio_dir)
                if audio_path:
                    asr_res = await transcribe_with_fallback(
                        audio_path,
                        output_dir,
                        language=asr_cfg.get("videocaptioner", {}).get("language", "auto"),
                    )
                    result["warnings"] += asr_res.get("warnings", [])
                    if asr_res.get("success"):
                        subtitle_text = asr_res["text"]
                        subtitle_source = f"asr:{asr_res['engine']}"
                        result["has_subtitle"] = True
                        result["fetch_backend"] = f"bili-cli+asr:{asr_res['engine']}"
                        result["warnings"].append(
                            f"无官方字幕，已用 {asr_res['engine']} ASR 转写（结果可能存在误差）"
                        )
                        if asr_res.get("transcript_file"):
                            result["transcript_file"] = asr_res["transcript_file"]
                    else:
                        result["warnings"].append(f"ASR 回退失败: {asr_res.get('error', '')}")
                        _log.warning("asr_all_failed", url=url, bvid=bvid)
                    # 音频清理
                    if not asr_cfg.get("keep_audio", False) and audio_path:
                        with contextlib.suppress(Exception):
                            audio_path.unlink(missing_ok=True)
                else:
                    result["warnings"].append(
                        "音频下载失败(bili audio)，跳过 ASR；"
                        "确认已装 audio 扩展: pipx install 'bilibili-cli[audio]'"
                    )
            else:
                result["warnings"].append("该视频无字幕或字幕为空（可能需要登录 bili login）")

        result["subtitle_source"] = subtitle_source

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
        capture_status = "成功" if subtitle_text else "部分失败"

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
            "> 📺 类型：B站视频",
            f"> 🆔 BV号：{bvid}",
            f"> 📁 领域：{category}",
            "> 🏷️ 来源类型：video",
            "> 🌐 平台：bilibili",
            f"> 📅 发布日期：{upload_date_fmt}",
            f"> ✅ 抓取状态：{capture_status}",
            "",
            "---",
            "",
            "## 📹 视频信息",
            "",
            "| 项目 | 内容 |",
            "|------|------|",
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
            md_lines.extend(["", "## 🎤 字幕内容", ""])
            if subtitle_source and subtitle_source.startswith("asr:"):
                md_lines.append(
                    f"> ℹ️ 本字幕由 ASR 自动转写（{subtitle_source.split(':', 1)[1]}），"
                    "未经人工校对，可能存在识别误差。\n"
                )
            md_lines.append(sub_text)
        else:
            md_lines.extend(
                ["", "## 🎤 字幕内容", "", "> 字幕不可用（官方无字幕且 ASR 回退失败），未生成总结"]
            )

        md_lines.extend(
            [
                "",
                "---",
                "",
                "## 📋 元数据",
                "",
                f"- **原始链接**：{url}",
                "- **类型**：video",
                "- **平台**：bilibili",
                f"- **BV号**：{bvid}",
                f"- **领域**：{category}",
                f"- **发布日期**：{upload_date_fmt}",
                f"- **抓取状态**：{capture_status}",
                f"- **剪藏时间**：{now}",
                f"- **UP主**：{uploader}",
            ]
        )

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
        _log.info(
            "video_clip_success", url=url, bvid=bvid, subtitle_source=result.get("subtitle_source")
        )

    except Exception as e:
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / "video.md"
        md_path.write_text(
            _build_video_placeholder(
                url,
                f"B站视频处理异常: {e}",
                partial_info=[f"BV号：{bvid}"],
                category=category,
                status="失败",
            ),
            encoding="utf-8",
        )
        result["md_file"] = str(md_path)
        result["error"] = f"B站视频处理异常: {e}"

    return result


async def _download_cover(pic_url: str, output_dir: Path) -> Path | None:
    """下载B站封面图到输出目录，返回本地路径"""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15, follow_redirects=True, trust_env=False) as client:
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


def _build_video_placeholder(
    url: str,
    reason: str,
    partial_info: list[str],
    category: str = "视频与影音",
    status: str = "失败",
) -> str:
    """构建视频失败占位 md（需求 6.4）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# B站视频（抓取失败）",
        "",
        f"> 📅 剪藏时间：{now}",
        f"> 🔗 来源：[{url}]({url})",
        "> 📺 类型：B站视频",
        f"> 📁 领域：{category}",
        "> 🏷️ 来源类型：video",
        "> 🌐 平台：bilibili",
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
        "- **类型**：video",
        "- **平台**：bilibili",
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
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _bili_audio_available() -> bool:
    """检查 bili-cli 是否已安装 audio 扩展（bili audio 子命令）"""
    try:
        result = subprocess.run(
            ["bili", "audio", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


async def download_bilibili_audio(bvid: str, out_dir: Path) -> Path | None:
    """用 bili-cli 下载完整音频(--no-split，m4a)。失败返回 None。

    需 audio 扩展: pipx install 'bilibili-cli[audio]'
    """
    if not _bili_audio_available():
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()

    def _run() -> subprocess.CompletedProcess[str] | None:
        try:
            proc = subprocess.run(
                ["bili", "audio", bvid, "--no-split", "-o", str(out_dir)],
                capture_output=True,
                text=True,
                timeout=900,
            )
            return proc
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None

    proc = await loop.run_in_executor(None, _run)
    if not proc or proc.returncode != 0:
        return None
    # bili-cli 输出文件名不确定，glob 兜底（优先 m4a，其次 mp3/wav）
    for ext in ("*.m4a", "*.mp3", "*.wav", "*.mp4"):
        files = sorted(out_dir.glob(ext))
        if files:
            return files[-1]
    return None


async def _run_bili_cli(bvid: str) -> dict[str, Any] | None:
    """执行 bili-cli 并返回 JSON 结果

    注意: bili-cli 在字幕获取失败(如未登录)时会返回 exit code 1，
    但 stdout 中的 JSON 仍可能 ok:true 且包含视频信息。
    因此优先解析 JSON，仅当 JSON 解析失败时才看 exit code。
    """
    loop = asyncio.get_event_loop()

    def _run() -> dict[str, Any]:
        try:
            proc = subprocess.run(
                ["bili", "video", bvid, "--subtitle", "--json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # 优先解析 JSON（bili-cli 字幕失败时 exit code=1 但 JSON 仍有效）
            if proc.stdout and proc.stdout.strip():
                try:
                    data: dict[str, Any] = json_mod.loads(proc.stdout)
                    if data.get("ok"):
                        # T076: 保留 stderr 供后续登录检测
                        stderr_str = (proc.stderr or "").strip()
                        if stderr_str:
                            data["_raw_stderr"] = stderr_str
                        return data
                except json_mod.JSONDecodeError:
                    pass  # JSON 解析失败，继续走 exit code 逻辑

            # JSON 无效或 ok:false，按 exit code 处理
            stderr = (proc.stderr or "").strip()
            if "not logged in" in stderr.lower() or "login" in stderr.lower():
                return {"ok": False, "error": "未登录，请执行 bili login 扫码登录"}
            return {"ok": False, "error": stderr or f"退出码 {proc.returncode}"}

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


async def clip_youtube(url: str, output_dir: Path) -> dict[str, Any]:
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
