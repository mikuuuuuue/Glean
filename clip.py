#!/usr/bin/env python3
"""剪藏 Skill 统一入口 - astrbot Skill 主脚本

支持：
  1. 普通网页 → Markdown + 图片 + 长截图
  2. B站视频 → 视频信息 + 字幕 → Markdown
  3. 图片 → 原图存档（识图由 clawbot agent 自身能力完成）
  4. PDF/Word → 原文件 + 正文抽取 → Markdown
  5. 多链接/多文件批处理 + 汇总回执
  6. 按领域自动分类存储、去重提醒、失败占位、跨领域移动

用法：
  python clip.py <url>
  python clip.py <url1> <url2> ...            # 多链接批处理
  python clip.py --image <path> [--image ...]   # 图片剪藏
  python clip.py --doc <path> [--doc ...]      # PDF/Word 剪藏
  python clip.py <url> --force                 # 已剪过→覆盖重剪
  python clip.py --search <keyword>
  python clip.py --stats
"""

import asyncio
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

from clipper.categorizer import Categorizer
from clipper.folder import safe_folder_name, unique_folder
from clipper.image import clip_image, file_content_hash
from clipper.indexer import Indexer
from clipper.logging import get_logger
from clipper.video import clip_bilibili, is_bilibili_url
from clipper.web import check_dedup_before_clip, clip_webpage, clip_webpage_firecrawl

_log = get_logger("clip")

# ── 路径和配置 ──────────────────────────────────────────
SKILL_DIR = Path(__file__).parent.absolute()
CONFIG_PATH = SKILL_DIR / "config.yaml"

with open(CONFIG_PATH, encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

STORAGE_CONFIG = CONFIG.get("storage", {})
BASE_DIR = SKILL_DIR / STORAGE_CONFIG.get("base_dir", "./clipped_pages")
INDEX_FILE = STORAGE_CONFIG.get("index_file", "_index.json")
FEATURES = CONFIG.get("features", {})

# 初始化
categorizer = Categorizer(str(CONFIG_PATH))
indexer = Indexer(str(BASE_DIR), INDEX_FILE)


# ── URL 检测(规范实现位于 clipper.video,此处导入以保持向后兼容) ─────
# is_bilibili_url 自 clipper.video 导入,供 clip_url 等流程使用;
# 更结构化的类型识别见 clipper.url_detector.detect_url_type。

# ── 文件安全命名(使用 clipper.folder 统一实现) ──────────────


# ── 整页长截图（Playwright 主 + Firecrawl 回退）─────────────
def _screenshot_engine():
    """读 config 返回截图引擎: auto / playwright / firecrawl / off。"""
    return (CONFIG.get("screenshot", {}) or {}).get("engine", "auto")


def _screenshot_disabled():
    sc = CONFIG.get("screenshot", {}) or {}
    return sc.get("enabled", True) is False or sc.get("engine", "auto") == "off"


async def _capture_screenshot(url: str, folder_path: Path):
    """对 url 做整页长截图，落到 folder_path/screenshot.png。

    策略：
      engine=playwright   → 仅本地 Playwright（失败也认）
      engine=firecrawl    → 仅 Firecrawl screenshot@fullPage
      engine=auto(默认)   → Playwright 优先；失败/未装回退 Firecrawl
      engine=off / 关     → 不截图
    返回 dict: {ok, screenshot_file, method, error}
    """
    if _screenshot_disabled():
        return {"ok": False, "screenshot_file": None, "method": "off", "error": "截图已关闭"}

    engine = _screenshot_engine()
    ss_path = folder_path / "screenshot.png"

    # ── Playwright 主路径 ──
    async def _try_playwright():
        from clipper.screenshot import take_fullpage_screenshot

        r = await take_fullpage_screenshot(url, folder_path)
        if r.get("success"):
            return {
                "ok": True,
                "screenshot_file": r.get("screenshot_file"),
                "method": "playwright",
                "error": None,
            }
        return {
            "ok": False,
            "screenshot_file": None,
            "method": "playwright",
            "error": r.get("error"),
        }

    # ── Firecrawl 回退/单路径：调 clip_webpage_firecrawl 取其 fullPage 截图 ──
    async def _try_firecrawl():
        if os.environ.get("CLIP_FIRECRAWL_DISABLE", "").strip():
            return {
                "ok": False,
                "screenshot_file": None,
                "method": "firecrawl",
                "error": "Firecrawl 被测试开关禁用",
            }
        fc = (CONFIG.get("scraping", {}) or {}).get("firecrawl", {}) or {}
        if not fc.get("api_key"):
            return {
                "ok": False,
                "screenshot_file": None,
                "method": "firecrawl",
                "error": "无 Firecrawl API Key",
            }
        tmp = folder_path.parent / ("_ss_tmp_" + folder_path.name)
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            r = await clip_webpage_firecrawl(url, tmp, category="其他收藏")
        except Exception as e:
            return {
                "ok": False,
                "screenshot_file": None,
                "method": "firecrawl",
                "error": f"Firecrawl 截图异常: {e}",
            }
        ss = r.get("screenshot_file")
        if ss and Path(ss).exists():
            folder_path.mkdir(parents=True, exist_ok=True)
            shutil.move(str(ss), str(ss_path))
            shutil.rmtree(tmp, ignore_errors=True)
            return {
                "ok": True,
                "screenshot_file": str(ss_path),
                "method": "firecrawl",
                "error": None,
            }
        shutil.rmtree(tmp, ignore_errors=True)
        return {
            "ok": False,
            "screenshot_file": None,
            "method": "firecrawl",
            "error": r.get("error", "Firecrawl 未返回截图"),
        }

    if engine == "playwright":
        return await _try_playwright()
    if engine == "firecrawl":
        return await _try_firecrawl()
    # auto
    r = await _try_playwright()
    if r["ok"]:
        return r
    return await _try_firecrawl()


def _inject_screenshot_ref(md_path: Path):
    """后处理：若 md 同目录有 screenshot.png 且 md 内未引用它，在第一个 --- 后
    插入「整页长截图」引用块（需求 §5.1）。md 已引用则跳过。"""
    if not md_path or not md_path.exists():
        return
    ss = md_path.parent / "screenshot.png"
    if not ss.exists():
        return
    txt = md_path.read_text(encoding="utf-8")
    if "screenshot.png" in txt:
        return
    ref_block = ["", "## 🖼️ 整页长截图", "", "![长截图](screenshot.png)", ""]
    # 在第一个独立 --- 行后插入
    parts = txt.split("---", 2)
    if len(parts) < 3:
        # 没有 frontmatter 分隔，直接在文件头插
        new_txt = "\n".join(ref_block) + "\n" + txt
    else:
        new_txt = parts[0] + "---" + parts[1] + "---" + "\n" + "\n".join(ref_block) + parts[2]
    md_path.write_text(new_txt, encoding="utf-8")


# ── 单次剪藏 ────────────────────────────────────────────


def _check_dedup(url: str, force: bool) -> dict | None:
    """去重检查,返回 duplicate dict 或 None(可继续剪藏)。"""
    if force:
        return None
    dedup = check_dedup_before_clip(indexer, url)
    if dedup["status"] != "new" and dedup["existing"]:
        existing = dedup["existing"][0]
        _log.info(
            "dedup_detected",
            url=url,
            status=dedup["status"],
            existing_title=existing.get("title", ""),
        )
        return {
            "url": url,
            "title": existing.get("title", ""),
            "category": existing.get("category", ""),
            "folder": str(
                Path(categorizer.base_dir)
                / existing.get("category", "")
                / existing.get("folder", "")
            ),
            "duplicate": True,
            "duplicate_entry": existing,
            "success_items": [],
            "warnings": [],
            "errors": [],
            "overall": "duplicate",
            "needs_suggestion": False,
        }
    return None


async def _clip_bilibili(
    url: str, timestamp: str, do_video: bool
) -> tuple[list, list, list, str, str, str, Path]:
    """B站视频剪藏子流程。返回 (success, warnings, errors, category, folder_name, title, folder_path)。"""
    all_success = []
    all_warnings = []
    all_errors = []
    temp_folder = Path(categorizer.base_dir) / "_temp" / f"{timestamp}_{{title}}"
    temp_folder.mkdir(parents=True, exist_ok=True)

    if do_video:
        video_result = await clip_bilibili(
            url,
            temp_folder,
            category_fn=lambda t, d: categorizer.classify(t or "B站视频", d),
        )
    else:
        video_result = {"success": False, "title": None, "error": "视频处理已跳过"}

    real_title = video_result.get("title") if video_result.get("title") else "B站视频"
    description = video_result.get("description", "")
    category = video_result.get("category") or categorizer.classify(real_title, description)
    safe_title = safe_folder_name(real_title)
    folder_name = f"{timestamp}_{safe_title}"
    folder_path = unique_folder(Path(categorizer.base_dir) / category / folder_name)
    folder_name = folder_path.name
    folder_path.mkdir(parents=True, exist_ok=True)

    if video_result.get("success") and video_result.get("md_file"):
        src = Path(video_result["md_file"])
        if src.exists():
            for f in temp_folder.glob("*"):
                dst = folder_path / f.name
                shutil.move(str(f), str(dst))
            video_result["md_file"] = str(folder_path / src.name)
            all_success.append(
                {
                    "type": "video_md",
                    "path": video_result.get("md_file"),
                    "title": real_title,
                    "has_subtitle": video_result.get("has_subtitle", False),
                    "subtitle_source": video_result.get("subtitle_source"),
                }
            )
        else:
            all_errors.append({"type": "video", "detail": "视频文件未生成"})
    elif video_result.get("success"):
        all_success.append(
            {
                "type": "video_md",
                "path": video_result.get("md_file"),
                "title": real_title,
                "has_subtitle": video_result.get("has_subtitle", False),
                "subtitle_source": video_result.get("subtitle_source"),
            }
        )
    else:
        if video_result.get("md_file"):
            src = Path(video_result["md_file"])
            if src.exists():
                for f in temp_folder.glob("*"):
                    dst = folder_path / f.name
                    shutil.move(str(f), str(dst))
                video_result["md_file"] = str(folder_path / src.name)
                all_success.append(
                    {
                        "type": "video_md",
                        "path": video_result.get("md_file"),
                        "title": real_title,
                        "has_subtitle": False,
                        "subtitle_source": None,
                    }
                )
        all_errors.append(
            {
                "type": "video",
                "detail": video_result.get("error", "视频处理失败"),
            }
        )

    for w in video_result.get("warnings", []):
        all_warnings.append({"type": "video", "detail": w})

    shutil.rmtree(temp_folder, ignore_errors=True)
    return all_success, all_warnings, all_errors, category, folder_name, real_title, folder_path


async def _clip_web_firecrawl(
    url: str, timestamp: str, do_images: bool, title: str, description: str
) -> tuple[list, list, list, str, str, str, Path, str]:
    """Firecrawl 网页剪藏子流程。返回 (success, warnings, errors, category, folder_name, title, folder_path, fetch_backend)。"""
    all_success = []
    all_warnings = []
    all_errors = []
    fetch_backend = "firecrawl"

    temp_category = categorizer.classify(title, description)
    safe_temp = safe_folder_name(title)
    temp_folder_name = f"{timestamp}_{safe_temp}"
    folder_path = Path(categorizer.base_dir) / temp_category / temp_folder_name

    try:
        fc_result = await clip_webpage_firecrawl(
            url,
            folder_path,
            category=temp_category,
            category_fn=lambda t, d: categorizer.classify(t, d),
        )
    except Exception as fc_err:
        fc_result = {
            "success": False,
            "title": title,
            "md_file": None,
            "screenshot_file": None,
            "error": f"Firecrawl 调用异常: {fc_err}",
            "warnings": [],
            "category": temp_category,
        }

    if fc_result.get("success"):
        real_title = fc_result.get("title", title)
        real_category = fc_result.get("category") or categorizer.classify(real_title, description)
        real_safe = safe_folder_name(real_title)
        real_folder_name = f"{timestamp}_{real_safe}"
        real_folder_path = Path(categorizer.base_dir) / real_category / real_folder_name

        if str(real_folder_path) != str(folder_path):
            real_folder_path.mkdir(parents=True, exist_ok=True)
            for f in folder_path.glob("*"):
                shutil.move(str(f), str(real_folder_path / f.name))
            shutil.rmtree(folder_path, ignore_errors=True)
            folder_path = real_folder_path
            folder_name = folder_path.name
            category = real_category
            title = real_title
        else:
            category = real_category
            folder_name = folder_path.name

        all_success.append(
            {
                "type": "article_md",
                "path": fc_result.get("md_file"),
                "title": real_title,
            }
        )
        if fc_result.get("screenshot_file"):
            all_success.append(
                {
                    "type": "screenshot",
                    "path": fc_result.get("screenshot_file"),
                }
            )
    else:
        # Firecrawl 失败:auto 模式回退到本地 httpx
        fb_used = False
        backend = CONFIG.get("scraping", {}).get("backend", "auto")
        if backend == "auto":
            fb_category = categorizer.classify(title, description)
            fb_safe = safe_folder_name(title)
            fb_folder_name = f"{timestamp}_{fb_safe}"
            fb_folder_path = Path(categorizer.base_dir) / fb_category / fb_folder_name

            fb_result = await clip_webpage(
                url,
                fb_folder_path,
                download_images=do_images,
                category=fb_category,
                category_fn=lambda t, d: categorizer.classify(t, d),
            )
            if fb_result.get("success"):
                fb_category = fb_result.get("category") or fb_category
                category = fb_category
                folder_path = fb_folder_path
                folder_name = fb_folder_name
                all_success.append(
                    {
                        "type": "article_md",
                        "path": fb_result.get("md_file"),
                        "title": fb_result.get("title", title),
                        "images": fb_result.get("images_downloaded", 0),
                    }
                )
                all_warnings.append(
                    {
                        "type": "web",
                        "detail": f"Firecrawl 失败已回退本地抓取：{fc_result.get('error', '')}",
                    }
                )
                for w in fb_result.get("warnings", []):
                    all_warnings.append({"type": "web", "detail": w})
                fb_used = True
                fetch_backend = "httpx"

        if not fb_used:
            if fc_result.get("md_file"):
                src = Path(fc_result["md_file"])
                real_title = fc_result.get("title", title) or "网页"
                real_safe = safe_folder_name(real_title)
                real_category = fc_result.get("category") or temp_category
                real_folder_name = f"{timestamp}_{real_safe}"
                real_folder_path = Path(categorizer.base_dir) / real_category / real_folder_name
                if str(real_folder_path) != str(folder_path):
                    real_folder_path.mkdir(parents=True, exist_ok=True)
                    for f in folder_path.glob("*"):
                        shutil.move(str(f), str(real_folder_path / f.name))
                    shutil.rmtree(folder_path, ignore_errors=True)
                    folder_path = real_folder_path
                    category = real_category
                folder_name = folder_path.name
                all_success.append(
                    {
                        "type": "article_md",
                        "path": str(folder_path / src.name),
                        "title": real_title,
                    }
                )
            else:
                folder_name = temp_folder_name
            if fc_result.get("screenshot_file"):
                all_success.append(
                    {
                        "type": "screenshot",
                        "path": fc_result.get("screenshot_file"),
                    }
                )
            all_errors.append(
                {
                    "type": "web",
                    "detail": fc_result.get("error", "Firecrawl 失败，本地回退不可用"),
                }
            )
            category = fc_result.get("category") or temp_category
    for w in fc_result.get("warnings", []):
        all_warnings.append({"type": "web", "detail": w})

    return (
        all_success,
        all_warnings,
        all_errors,
        category,
        folder_name,
        title,
        folder_path,
        fetch_backend,
    )


async def _clip_web_local(
    url: str, timestamp: str, do_images: bool, title: str, description: str
) -> tuple[list, list, list, str, str, str, Path]:
    """本地 httpx 网页剪藏子流程。返回 (success, warnings, errors, category, folder_name, title, folder_path)。"""
    all_success = []
    all_warnings = []
    all_errors = []

    category = categorizer.classify(title, description)
    safe_title = safe_folder_name(title)
    folder_name = f"{timestamp}_{safe_title}"
    folder_path = unique_folder(Path(categorizer.base_dir) / category / folder_name)
    folder_name = folder_path.name
    folder_path.mkdir(parents=True, exist_ok=True)

    res = await clip_webpage(
        url,
        folder_path,
        download_images=do_images,
        category=category,
        category_fn=lambda t, d: categorizer.classify(t, d),
    )
    real_cat = res.get("category") or category
    if real_cat != category:
        category = real_cat

    if res.get("success"):
        all_success.append(
            {
                "type": "article_md",
                "path": res.get("md_file"),
                "title": res.get("title", title),
                "images": res.get("images_downloaded", 0),
            }
        )
    else:
        if res.get("md_file"):
            all_success.append(
                {
                    "type": "article_md",
                    "path": res.get("md_file"),
                    "title": res.get("title", title),
                }
            )
        all_errors.append(
            {
                "type": "web",
                "detail": res.get("error", "网页处理失败"),
            }
        )
    for w in res.get("warnings", []):
        all_warnings.append({"type": "web", "detail": w})
    if res.get("images_failed", 0) > 0:
        all_warnings.append(
            {
                "type": "web",
                "detail": f"图片下载: {res.get('images_downloaded', 0)}/{res.get('images_downloaded', 0) + res.get('images_failed', 0)} 成功, {res.get('images_failed', 0)} 失败",
            }
        )

    # 按真实领域移动文件夹
    md_file = res.get("md_file")
    if real_cat and md_file:
        src_dir = Path(md_file).parent
        new_dir = Path(categorizer.base_dir) / real_cat / src_dir.name
        if str(new_dir) != str(src_dir):
            new_dir.mkdir(parents=True, exist_ok=True)
            for f in src_dir.iterdir():
                shutil.move(str(f), str(new_dir / f.name))
            shutil.rmtree(src_dir, ignore_errors=True)
            folder_path = new_dir
            for s in all_success:
                if s.get("type") == "article_md" and s.get("path") == md_file:
                    s["path"] = str(new_dir / Path(md_file).name)

    # 按真实标题重命名文件夹
    real_title = ""
    for s in all_success:
        if s.get("type") == "article_md" and s.get("title"):
            real_title = s["title"]
            break
    if real_title:
        real_safe = safe_folder_name(real_title)
        expected_name = f"{timestamp}_{real_safe}"
        if expected_name != folder_name:
            new_title_dir = folder_path.parent / expected_name
            if str(new_title_dir) != str(folder_path):
                new_title_dir.mkdir(parents=True, exist_ok=True)
                for f in folder_path.glob("*"):
                    shutil.move(str(f), str(new_title_dir / f.name))
                shutil.rmtree(folder_path, ignore_errors=True)
                folder_path = new_title_dir
                folder_name = expected_name
                for s in all_success:
                    if s.get("path"):
                        s["path"] = str(new_title_dir / Path(s["path"]).name)

    # 整页长截图
    try:
        ss_r = await _capture_screenshot(url, folder_path)
        if ss_r.get("ok"):
            all_success.append(
                {
                    "type": "screenshot",
                    "path": ss_r["screenshot_file"],
                    "title": title,
                }
            )
            for s in all_success:
                if s.get("type") == "article_md" and s.get("path"):
                    _inject_screenshot_ref(Path(s["path"]))
                    break
        else:
            all_warnings.append(
                {
                    "type": "screenshot",
                    "detail": f"长截图失败，已跳过：{ss_r.get('error', '')}",
                }
            )
    except Exception as ss_err:
        all_warnings.append(
            {
                "type": "screenshot",
                "detail": f"长截图异常，已跳过：{ss_err}",
            }
        )

    return all_success, all_warnings, all_errors, category, folder_name, title, folder_path


async def _fetch_title_and_desc(url: str) -> tuple[str, str]:
    """本地 httpx 预获取标题和描述用于分类。"""
    title = "网页"
    description = ""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10, follow_redirects=True, trust_env=False) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            title_match = re.search(r"<title[^>]*>([^<]+)</title>", resp.text, re.IGNORECASE)
            if title_match:
                title = title_match.group(1).strip()
                import html as html_mod

                title = html_mod.unescape(title)
            desc_match = re.search(
                r'<meta\s+name="description"\s+content="([^"]*)"',
                resp.text,
                re.IGNORECASE,
            )
            if desc_match:
                description = desc_match.group(1)
    except Exception:
        pass
    return title, description


async def _resolve_web_backend(url: str) -> tuple[bool, str, str]:
    """决定网页抓取后端。返回 (use_firecrawl, title, description)。"""
    scraping_config = CONFIG.get("scraping", {})
    backend = scraping_config.get("backend", "auto")
    fc_api_key = scraping_config.get("firecrawl", {}).get("api_key", "")

    is_weixin_article = "mp.weixin.qq.com" in urlparse(url).netloc
    if backend == "auto":
        use_firecrawl = bool(fc_api_key) and not is_weixin_article
    else:
        use_firecrawl = backend == "firecrawl" and bool(fc_api_key)
    if os.environ.get("CLIP_FORCE_LOCAL", "").strip():
        use_firecrawl = False

    if use_firecrawl:
        return True, "网页", ""

    title, description = await _fetch_title_and_desc(url)
    return False, title, description


async def clip_url(
    url: str,
    *,
    do_images: bool = True,
    do_video: bool = True,
    force: bool = False,
) -> dict:
    """剪藏一个 URL。force=True 时跳过去重,覆盖原条目。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _log.info("clip_start", url=url, force=force)
    fetch_backend = "httpx"

    # 去重检查
    dedup_result = _check_dedup(url, force)
    if dedup_result:
        return dedup_result

    if is_bilibili_url(url):
        fetch_backend = "bili-cli"
        (
            all_success,
            all_warnings,
            all_errors,
            category,
            folder_name,
            title,
            folder_path,
        ) = await _clip_bilibili(url, timestamp, do_video)
    else:
        use_firecrawl, title, description = await _resolve_web_backend(url)
        if use_firecrawl:
            (
                all_success,
                all_warnings,
                all_errors,
                category,
                folder_name,
                title,
                folder_path,
                fetch_backend,
            ) = await _clip_web_firecrawl(url, timestamp, do_images, title, description)
        else:
            (
                all_success,
                all_warnings,
                all_errors,
                category,
                folder_name,
                title,
                folder_path,
            ) = await _clip_web_local(url, timestamp, do_images, title, description)

    # 更新索引
    final_title = ""
    final_category = category
    item_type = "video" if is_bilibili_url(url) else "web"

    for s in all_success:
        if s.get("title"):
            final_title = s["title"]
            break
    if not final_title:
        final_title = title if title else "未知标题"

    files_list = [s.get("path", "") for s in all_success]

    if all_success and not all_errors:
        capture_status = "ok"
    elif all_success and all_errors:
        capture_status = "partial"
    else:
        capture_status = "failed"

    indexer.add_entry(
        url=url,
        title=final_title,
        category=final_category,
        folder=folder_name,
        files=files_list,
        warnings=[w.get("detail", "") for w in all_warnings],
        errors=[e.get("detail", "") for e in all_errors],
        status=capture_status,
        item_type=item_type,
        source=url,
        fetch_backend=fetch_backend,
    )

    _log.info(
        "clip_complete",
        url=url,
        title=final_title,
        status=capture_status,
        category=final_category,
        fetch_backend=fetch_backend,
    )

    return {
        "url": url,
        "title": final_title,
        "category": final_category,
        "folder": str(folder_path),
        "success_items": all_success,
        "warnings": all_warnings,
        "errors": all_errors,
        "overall": capture_status,
        "needs_suggestion": final_category == "其他收藏"
        and categorizer.needs_suggestion(final_title, ""),
    }


# ── 文件类剪藏（图片 / PDF / Word）─────────────────────────
async def clip_file(
    file_path: str,
    *,
    source_url: str = None,
    force: bool = False,
) -> dict:
    """剪藏本地文件（图片/PDF/Word），按内容哈希查重。"""
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return {
            "url": file_path,
            "title": p.name,
            "category": "",
            "folder": "",
            "success_items": [],
            "warnings": [],
            "errors": [{"type": "file", "detail": "文件不存在"}],
            "overall": "error",
            "needs_suggestion": False,
        }

    suffix = p.suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"):
        item_type = "image"
    elif suffix in (".pdf", ".docx"):
        item_type = "doc"
    else:
        return {
            "url": file_path,
            "title": p.name,
            "category": "",
            "folder": "",
            "success_items": [],
            "warnings": [],
            "errors": [{"type": "file", "detail": f"暂不支持的文件类型: {suffix}"}],
            "overall": "error",
            "needs_suggestion": False,
        }

    # T058: 文件大小前置校验(FR-013b)
    from clipper.validators import validate_file_size

    size_ok, size_err = validate_file_size(p)
    all_warnings = [] if size_ok else [{"type": "file", "detail": size_err}]
    if not size_ok:
        _log.warning("file_size_exceeded", path=str(p))

    # 内容哈希查重（需求 6.3）
    content_hash = file_content_hash(p)
    if not force:
        existing = indexer.find_by_hash(content_hash)
        if existing:
            return {
                "url": file_path,
                "title": existing.get("title", p.name),
                "category": existing.get("category", ""),
                "folder": str(
                    Path(categorizer.base_dir)
                    / existing.get("category", "")
                    / existing.get("folder", "")
                ),
                "duplicate": True,
                "duplicate_entry": existing,
                "success_items": [],
                "warnings": [],
                "errors": [],
                "overall": "duplicate",
                "needs_suggestion": False,
            }
    elif force:
        # 覆盖: 先删同名哈希的旧条目
        old = indexer.find_by_hash(content_hash)
        if old:
            old_dir = Path(categorizer.base_dir) / old.get("category", "") / old.get("folder", "")
            if old_dir.exists():
                shutil.rmtree(old_dir, ignore_errors=True)
            indexer.delete_entry(old.get("url", content_hash))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = safe_folder_name(p.stem) or f"file_{timestamp}"
    # 文件类暂用文件名做分类依据（无正文）
    fallback_category = categorizer.classify(safe_title, "") if item_type == "doc" else "其他收藏"
    folder_name = f"{timestamp}_{safe_title}"
    folder_path = Path(categorizer.base_dir) / fallback_category / folder_name

    if item_type == "image":
        res = clip_image(
            [str(p)],
            folder_path,
            category=fallback_category,
            source_url=source_url,
            category_fn=lambda t, d: categorizer.classify(t, d),
        )
    else:  # doc
        from clipper.doc import clip_doc

        res = clip_doc(
            str(p),
            folder_path,
            category=fallback_category,
            category_fn=lambda t, d: categorizer.classify(t, d),
        )

    folder_name = Path(res.get("md_file", "")).parent.name or folder_name
    folder_path = Path(res.get("md_file", str(folder_path))).parent
    final_category = res.get("category") or fallback_category
    # 若领域变了，移动目录
    real_dir = Path(categorizer.base_dir) / final_category / folder_path.name
    if str(real_dir) != str(folder_path):
        real_dir.mkdir(parents=True, exist_ok=True)
        for f in folder_path.glob("*"):
            shutil.move(str(f), str(real_dir / f.name))
        shutil.rmtree(folder_path, ignore_errors=True)
        folder_path = real_dir
        res["md_file"] = str(folder_path / Path(res["md_file"]).name)
        if res.get("files"):
            res["files"] = [str(folder_path / Path(f).name) for f in res["files"]]

    all_success = []
    all_errors = []
    file_warnings = [{"type": item_type, "detail": w} for w in res.get("warnings", [])]
    all_warnings = all_warnings + file_warnings
    if res.get("success"):
        all_success.append(
            {
                "type": f"{item_type}_md",
                "path": res.get("md_file"),
                "title": res.get("title", p.name),
                "images": len(res.get("files", [])) if item_type == "image" else 0,
            }
        )
        capture_status = "ok"
    else:
        capture_status = "failed"
        all_errors.append({"type": item_type, "detail": res.get("error", "处理失败")})
        if res.get("md_file"):
            all_success.append(
                {
                    "type": f"{item_type}_md",
                    "path": res.get("md_file"),
                    "title": res.get("title", p.name),
                }
            )

    indexer.add_entry(
        url=str(p),
        title=res.get("title", p.name),
        category=final_category,
        folder=folder_path.name,
        files=res.get("files", [res.get("md_file")]) if res.get("files") else [res.get("md_file")],
        warnings=[w.get("detail", "") for w in all_warnings],
        errors=[e.get("detail", "") for e in all_errors],
        status=capture_status,
        item_type=item_type,
        source=p.name if source_url is None else source_url,
        content_hash=content_hash,
        fetch_backend="local",
    )

    return {
        "url": str(p),
        "title": res.get("title", p.name),
        "category": final_category,
        "folder": str(folder_path),
        "success_items": all_success,
        "warnings": all_warnings,
        "errors": all_errors,
        "overall": capture_status,
        "content_hash": content_hash,
        "needs_suggestion": final_category == "其他收藏"
        and categorizer.needs_suggestion(res.get("title", ""), ""),
    }


# ── 格式化输出 ───────────────────────────────────────────
def format_result(result: dict) -> str:
    """将剪藏结果格式化为可读文本"""
    # 已剪藏提醒（需求 6.3）
    if result.get("duplicate"):
        e = result.get("duplicate_entry", {})
        lines = [
            f"## ♻️ 已剪藏过: {e.get('title', result['title'])}",
            "",
            f"- 📅 之前剪藏时间：{e.get('saved_at', '未知')}",
            f"- 📁 当时分类：**{e.get('category', '')}**",
            f"- 📂 路径：`{result.get('folder', '')}`",
            f"- 🔗 原始链接：{result.get('url', '')}",
            "",
            "如需**重新覆盖**，请确认后重试并带 `--force`：",
            "```",
            f'python clip.py "{result.get("url", "")}" --force',
            "```",
        ]
        return "\n".join(lines)

    lines = [f"## 📎 剪藏结果: {result['title']}", ""]

    if result["success_items"]:
        lines.append("### ✅ 成功")
        for item in result["success_items"]:
            t = item.get("type", "")
            if t == "article_md":
                lines.append(f"- 📄 文章已保存 ({item.get('images', 0)} 张图片)")
            elif t == "screenshot":
                lines.append("- 🖼️ 长截图已保存")
            elif t == "video_md":
                src = item.get("subtitle_source")
                if src == "official":
                    tag = " (官方字幕)"
                elif src and src.startswith("asr:"):
                    tag = f" ({src.split(':', 1)[1]}转写)"
                elif item.get("has_subtitle"):
                    tag = " (含字幕)"
                else:
                    tag = ""
                lines.append(f"- 📺 视频信息已保存{tag}")
            elif t == "image_md":
                lines.append(f"- 🖼️ 图片已保存 ({item.get('images', 0)} 张原图)")
            elif t == "doc_md":
                lines.append("- 📑 文档已保存")
        lines.append("")

    if result["warnings"]:
        lines.append("### ⚠️ 警告")
        for w in result["warnings"]:
            lines.append(f"- {w.get('detail', str(w))}")
        lines.append("")

    if result["errors"]:
        lines.append("### ❌ 错误")
        for e in result["errors"]:
            lines.append(f"- {e.get('detail', str(e))}")
        lines.append("")

    lines.extend(
        [
            f"📁 分类: **{result['category']}**",
            f"📂 路径: `{result['folder']}`",
            f"🔗 原始链接: {result['url']}",
        ]
    )

    # 分类建议
    if result.get("needs_suggestion") and result["category"] == "其他收藏":
        active = categorizer.get_active_categories()
        lines.append("")
        lines.append("### 💡 分类建议")
        lines.append("当前内容与现有分类关键词不匹配，已归入 **其他收藏**。")
        lines.append(f"现有分类 ({len(active)}/6): {', '.join(active)}")
        lines.append(f"可根据标题「{result.get('title', '')[:30]}」新增分类：")
        lines.append("```")
        lines.append('python clip.py --add-category "分类名" --keywords "关键词1,关键词2"')
        lines.append(f'python clip.py --reclassify "{Path(result["folder"]).name}" --to "分类名"')
        lines.append("```")

    return "\n".join(lines)


def build_summary(results: list) -> str:
    """批处理汇总回执（需求 5.5 / 验收 §9, T057: 含 retried 字段）"""
    lines = ["## 📦 批处理汇总", "", f"共 {len(results)} 条：", ""]
    lines.append("| 类型 | 标题 | 领域 | 状态 | 重试 | 链接/文件 |")
    for r in results:
        e = r.get("duplicate_entry")
        item_type = (e or r).get("type")
        if not item_type:
            u = r.get("url", "")
            item_type = (
                "video"
                if is_bilibili_url(u)
                else (
                    "image"
                    if u.lower().endswith(
                        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")
                    )
                    else ("doc" if u.lower().endswith((".pdf", ".docx")) else "web")
                )
            )
        title = (e or r).get("title", "")
        category = (e or r).get("category", "")
        source = (e or r).get("source", r.get("url", ""))
        overall = r.get("overall", "")
        icon = {"ok": "✅", "partial": "⚠️", "failed": "❌", "error": "❌", "duplicate": "♻️"}.get(
            overall, "?"
        )
        retried = "🔄" if r.get("retried") else ""
        lines.append(f"| {item_type} | {title[:30]} | {category} | {icon} | {retried} | {source} |")
    lines.append("")
    return "\n".join(lines)


# ── 命令行入口 ───────────────────────────────────────────
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="剪藏 Skill - 保存网页/视频到本地",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url", nargs="*", help="要剪藏的 URL（支持多个，批处理）")
    parser.add_argument("--no-images", action="store_true", help="不下载网页图片")
    parser.add_argument("--no-video", action="store_true", help="不处理视频")
    parser.add_argument("--force", action="store_true", help="跳过查重，覆盖原条目后重剪")
    parser.add_argument("--image", action="append", metavar="PATH", help="剪藏图片文件（可多次）")
    parser.add_argument(
        "--doc", action="append", metavar="PATH", help="剪藏 PDF/Word 文件（可多次）"
    )
    parser.add_argument("--search", metavar="KEYWORD", help="搜索已保存的内容")
    parser.add_argument("--stats", action="store_true", help="显示统计信息")
    parser.add_argument(
        "--list", metavar="CATEGORY", nargs="?", const="all", help="列出内容 (可选分类)"
    )
    parser.add_argument("--reclassify", metavar="FOLDER", help="移动文件夹到新分类")
    parser.add_argument("--to", metavar="CATEGORY", help="目标分类名（配合 --reclassify）")
    parser.add_argument("--replace", metavar="OLD_CAT", help="替换已有分类（配合 --to）")
    parser.add_argument(
        "--add-category", metavar="NAME", help="新增分类（可选 --keywords 逗号分隔）"
    )
    parser.add_argument("--keywords", metavar="KW1,KW2", help="新分类的关键词，逗号分隔")

    args = parser.parse_args()

    # 非剪藏操作
    if args.search:
        results = indexer.search(args.search)
        if results:
            print(f"🔍 搜索 '{args.search}' 的结果 ({len(results)} 条):\n")
            for entry in results:
                print(f"  📌 {entry['title']}")
                print(f"     🔗 {entry['url']}")
                print(f"     📁 {entry['category']} | 🕐 {entry['saved_at']}")
                print()
        else:
            print(f"🔍 未找到与 '{args.search}' 相关的内容")
        return

    if args.stats:
        stats = indexer.get_stats()
        print("📊 剪藏统计")
        print(f"   总计: {stats['total']} 条")
        print(f"   最后更新: {stats['last_updated']}")
        print("   分类分布:")
        for cat, count in stats.get("by_category", {}).items():
            print(f"     - {cat}: {count}")
        return

    if args.list is not None:
        entries = indexer.get_all() if args.list == "all" else indexer.get_by_category(args.list)
        if entries:
            print(f"📋 {'全部' if args.list == 'all' else args.list} 内容 ({len(entries)} 条):\n")
            for entry in entries:
                print(f"  📌 {entry['title']}")
                print(f"     🔗 {entry['url']}")
                print(f"     📁 {entry['category']} | 🕐 {entry['saved_at']}")
                print()
        else:
            print("📋 暂无内容")
        return

    # ── 新增分类 ──
    if args.add_category:
        name = args.add_category.strip()
        keywords = [k.strip() for k in (args.keywords or "").split(",") if k.strip()]
        active = categorizer.get_active_categories()
        if len(active) >= 6:
            print(f"❌ 分类已达上限（6个），现有: {', '.join(active)}")
            print("   请先 --replace 替换一个旧分类再新增")
            return
        if categorizer.add_category(name, keywords):
            print(f"✅ 新增分类: {name}")
            print(f"   关键词: {', '.join(keywords) if keywords else '(待补充)'}")
            print(f"   当前分类: {', '.join(categorizer.get_active_categories())}")
        else:
            print("❌ 新增失败: 分类已存在或名称为空")
        return

    # ── 替换分类 ──
    if args.replace and args.to:
        old = args.replace.strip()
        new = args.to.strip()
        if old not in categorizer.categories or old == "其他收藏":
            print(f"❌ 待替换分类不存在或不可替换: {old}")
            return
        keywords = [k.strip() for k in (args.keywords or "").split(",") if k.strip()]
        # 移动文件
        old_dir = Path(categorizer.base_dir) / old
        new_dir = Path(categorizer.base_dir) / new
        if categorizer.replace_category(old, new, keywords):
            if old_dir.exists():
                for item in old_dir.iterdir():
                    shutil.move(str(item), str(new_dir / item.name))
                old_dir.rmdir()
            # 更新索引中该分类的记录（持久化）
            indexer.update_entry(
                lambda e: e.get("category") == old,
                lambda e: {**e, "category": new},
            )
            print(f"✅ 已替换: {old} → {new}")
            if keywords:
                print(f"   关键词: {', '.join(keywords)}")
        else:
            print("❌ 替换失败")
        return

    # ── 重新分类（移动文件夹） ──
    if args.reclassify:
        folder_name = args.reclassify.strip()
        new_cat = (args.to or "").strip()
        if not new_cat:
            print("❌ 请用 --to 指定目标分类")
            print(f"   现有分类: {', '.join(categorizer.get_active_categories())}")
            return

        # 查找文件夹
        folder_path = None
        old_cat = None
        for cat in categorizer.categories:
            cat_dir = Path(categorizer.base_dir) / cat
            candidate = cat_dir / folder_name
            if candidate.exists() and candidate.is_dir():
                folder_path = candidate
                old_cat = cat
                break

        if not folder_path:
            print(f"❌ 未找到文件夹: {folder_name}")
            print("   请确认文件夹名正确（格式: 时间戳_标题）")
            return

        if old_cat == new_cat:
            print(f"⚠️ 已在分类 {new_cat} 中，无需移动")
            return

        # 确保目标分类存在
        if new_cat not in categorizer.categories:
            active = categorizer.get_active_categories()
            if len(active) >= 6 and new_cat not in categorizer.categories:
                print(f"❌ 分类已达上限（6个），现有: {', '.join(active)}")
                print("   请先 --replace 替换一个旧分类，再移动")
                return
            keywords = [k.strip() for k in (args.keywords or "").split(",") if k.strip()]
            if not categorizer.add_category(new_cat, keywords):
                print(f"❌ 无法创建分类: {new_cat}")
                return

        # 移动文件夹
        new_dir = Path(categorizer.base_dir) / new_cat / folder_name
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(folder_path), str(new_dir))

        # 清除空的旧分类目录
        old_cat_dir = Path(categorizer.base_dir) / old_cat
        if old_cat_dir.exists() and not any(old_cat_dir.iterdir()):
            old_cat_dir.rmdir()

        # 更新索引（持久化）
        indexer.update_entry(
            lambda e: e.get("folder") == folder_name and e.get("category") == old_cat,
            lambda e: {**e, "category": new_cat},
        )

        print(f"✅ 已移动: {folder_name}")
        print(f"   {old_cat} → {new_cat}")
        return

    # ── 文件类剪藏（图片 / 文档）批处理 + 汇总 ──
    file_inputs = []
    for p in args.image or []:
        file_inputs.append(("image", p))
    for p in args.doc or []:
        file_inputs.append(("doc", p))
    if file_inputs:
        print(f"📦 文件剪藏 {len(file_inputs)} 项\n")
        results = []
        for _, fp in file_inputs:
            try:
                r = asyncio.run(clip_file(fp, force=args.force))
            except Exception as e:
                r = {
                    "url": fp,
                    "title": fp,
                    "category": "",
                    "folder": "",
                    "success_items": [],
                    "warnings": [],
                    "errors": [{"type": "file", "detail": str(e)}],
                    "overall": "error",
                    "needs_suggestion": False,
                }
            results.append(r)
            print(format_result(r))
            print()

        # 批处理汇总回执
        print(build_summary(results))
        ok = sum(1 for r in results if r["overall"] == "ok")
        return 0 if ok else 1

    # 剪藏 URL
    if not args.url:
        parser.print_help()
        return

    urls = args.url
    print(f"🔗 正在剪藏 {len(urls)} 个链接\n")

    results = []
    for u in urls:
        # --force：覆盖前先删除旧条目与其文件夹
        if args.force:
            old = indexer.find_by_url(u)
            if old:
                old_dir = (
                    Path(categorizer.base_dir) / old.get("category", "") / old.get("folder", "")
                )
                if old_dir.exists():
                    shutil.rmtree(old_dir, ignore_errors=True)
                indexer.delete_entry(u)
                print(f"♻️ 已删除旧条目，准备重新剪藏: {u}\n")

        # T056: 单条失败自动重试 1 次(FR-011a)
        r = None
        retried = False
        try:
            r = asyncio.run(
                clip_url(
                    u,
                    do_images=not args.no_images,
                    do_video=not args.no_video,
                    force=args.force,
                )
            )
        except Exception as e:
            _log.warning("clip_failed_first", url=u, error=str(e)[:200])
            # 重试 1 次
            retried = True
            try:
                r = asyncio.run(
                    clip_url(
                        u,
                        do_images=not args.no_images,
                        do_video=not args.no_video,
                        force=args.force,
                    )
                )
                r["retried"] = True
                _log.info("clip_retry_success", url=u)
            except Exception as e2:
                _log.warning("clip_retry_failed", url=u, error=str(e2)[:200])
                r = {
                    "url": u,
                    "title": u,
                    "category": "",
                    "folder": "",
                    "success_items": [],
                    "warnings": [],
                    "errors": [{"type": "web", "detail": str(e2)}],
                    "overall": "error",
                    "needs_suggestion": False,
                    "retried": True,
                }
        if r is None:
            r = {
                "url": u,
                "title": u,
                "category": "",
                "folder": "",
                "success_items": [],
                "warnings": [],
                "errors": [{"type": "web", "detail": "unknown error"}],
                "overall": "error",
                "needs_suggestion": False,
            }
        # T059: structlog 记录每条结果
        _log.info("batch_item_done", url=u, overall=r.get("overall"), retried=retried)
        results.append(r)
        print(format_result(r))
        print()

    # 批处理汇总回执（多链接）
    if len(urls) > 1:
        print(build_summary(results))

    overall_any = (
        "ok"
        if any(r["overall"] == "ok" for r in results)
        else ("partial" if any(r["overall"] == "partial" for r in results) else "error")
    )
    return 0 if overall_any in ("ok", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
