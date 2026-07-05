"""网页剪藏模块 - HTML→Markdown + 图片下载

抓取策略：
  1. Firecrawl API（推荐，自动处理JS渲染+反爬，返回干净Markdown+截图）
  2. 本地 httpx 回退（离线或未配置 Firecrawl 时，仅纯文本）

失败时生成失败占位 md（需求 6.4）。图片防盗链分两级：黑名单域名保留远程
URL；其余按 origin/host Referer 重试，失败也保留远程 URL。
"""

import asyncio
import contextlib
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urljoin, urlparse

import html2text
import httpx

# ── 配置加载(使用统一单例 clipper.config) ──────────────────
from clipper.config import ConfigProxy
from clipper.logging import get_logger

_CONFIG = ConfigProxy()
_log = get_logger("clipper.web")
_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "sec-ch-ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


# ═══════════════════════════════════════════════════════════
# Firecrawl 后端（推荐）
# ═══════════════════════════════════════════════════════════


async def clip_webpage_firecrawl(
    url: str,
    output_dir: Path,
    category: str = "其他收藏",
    category_fn: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """
    使用 Firecrawl API 抓取网页，直接返回干净 Markdown + 截图。

    category: 默认/兜底领域
    category_fn: 可选 callable(title, description)->分类名；拿到真实标题后会调用它
                 覆盖默认 category，使 md 头部写入真实领域。

    Returns:
        dict: {success, title, md_file, screenshot_file, error, warnings}
    """
    result: dict[str, Any] = {
        "success": False,
        "title": "无标题",
        "md_file": None,
        "screenshot_file": None,
        "error": None,
        "warnings": [],
        "fetch_method": "firecrawl",
        "fetch_backend": "firecrawl",
    }

    scraping_config = _CONFIG.get("scraping", {})
    fc_config = scraping_config.get("firecrawl", {})
    api_key = fc_config.get("api_key", "")

    if not api_key:
        result["error"] = "Firecrawl API Key 未配置"
        return result

    try:
        from firecrawl import FirecrawlApp
    except ImportError:
        result["error"] = "firecrawl-py 未安装，请执行: pip install firecrawl-py"
        return result

    try:
        app = FirecrawlApp(api_key=api_key)

        # 不同版本 firecrawl-py 接口签名不同（camelCase/snake_case/scrapeOptions）。
        # 采用最小化调用并逐步加可选参数；任何参数错误都回退到最小调用。
        # 整页长截图（需求 §5.1）：新版 SDK 用 ScreenshotFormat(full_page=True)
        # 即 {"type":"screenshot","full_page":True}；旧版 SDK（pre-Pydantic）
        # 接受 "screenshot" 字符串，不支持 full_page，服务端 render 可能用
        # 首屏视口。先试整页，失败降级普通 screenshot。
        fullpage_screenshot = {"type": "screenshot", "full_page": True}

        def _call(minimal: bool = False) -> Any:
            try:
                return app.scrape_url(url, formats=["markdown", fullpage_screenshot])
            except Exception:
                # 旧 SDK 不认 ScreenshotFormat → 降级到普通 screenshot
                try:
                    return app.scrape_url(url, formats=["markdown", "screenshot"])
                except Exception:
                    # 最后回退：仅抓 markdown，放弃截图（需求 T13：逐步降级）
                    try:
                        return app.scrape_url(url, formats=["markdown"])
                    except Exception:
                        return None

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _call)

        if not data:
            result["error"] = "Firecrawl 返回空数据"
            return result

        # Firecrawl SDK 返回 Document 对象，转 dict
        if not isinstance(data, dict):
            data = (
                data.model_dump()
                if hasattr(data, "model_dump")
                else (data.dict() if hasattr(data, "dict") else vars(data))
            )

        # ── 提取 Markdown ──
        md_text = data.get("markdown", "")
        metadata = data.get("metadata", {})

        title = metadata.get("title") or _extract_title_from_md(md_text) or "无标题"
        result["title"] = title

        # 拿到真实标题后回算领域（覆盖默认），md 头部写入真实领域
        if category_fn is not None:
            with contextlib.suppress(Exception):
                category = category_fn(title, metadata.get("description", "")) or category
        result["category"] = category

        # ── 下载截图（即便正文空也优先保留长截图） ──
        screenshot_data = data.get("screenshot")
        if screenshot_data:
            ss_path_obj = output_dir / "screenshot.png"
            output_dir.mkdir(parents=True, exist_ok=True)
            try:
                if screenshot_data.startswith("http"):
                    # URL 形式:通过 httpx 下载
                    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                        resp = await client.get(screenshot_data)
                        resp.raise_for_status()
                        ss_path_obj.write_bytes(resp.content)
                else:
                    # base64 形式:直接解码保存
                    import base64

                    ss_path_obj.write_bytes(base64.b64decode(screenshot_data))
                result["screenshot_file"] = str(ss_path_obj)
            except Exception as e:
                result["warnings"].append(f"截图保存失败: {e}")

        # ── 正文为空 → 失败占位（若截图在则部分占位） ──
        if not md_text.strip():
            status = "部分失败" if result.get("screenshot_file") else "失败"
            output_dir.mkdir(parents=True, exist_ok=True)
            md_path = output_dir / "article.md"
            partial_info = [f"标题：{title}"]
            if metadata.get("description"):
                partial_info.append(f"描述：{metadata.get('description')}")
            md_path.write_text(
                _build_placeholder_md(
                    title,
                    url,
                    "Firecrawl 未返回正文内容（可能是付费墙或验证码页面）",
                    partial_info=partial_info,
                    fetch_method="firecrawl",
                    category=category,
                    status=status,
                    screenshot_path=result.get("screenshot_file"),
                ),
                encoding="utf-8",
            )
            result["md_file"] = str(md_path)
            result["error"] = "Firecrawl 未返回正文内容（可能是付费墙或验证码页面）"
            return result

        # ── 写入 MD ──
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        md_lines = [
            f"# {title}",
            "",
            f"> 📅 剪藏时间：{now}",
            f"> 🔗 来源：[{url}]({url})",
            "> 🔧 抓取方式：🌐 Firecrawl API",
            f"> 📁 领域：{category}",
            "> 🏷️ 来源类型：web",
            "> ✅ 抓取状态：成功",
            "",
            "---",
            "",
        ]
        # 截图引用块（需求 §5.1 整页长截图）
        if result.get("screenshot_file"):
            md_lines += [
                "## 🖼️ 整页长截图",
                "",
                f"![长截图]({Path(result['screenshot_file']).name})",
                "",
            ]
        md_lines += [
            md_text,
            "",
            "---",
            "",
            "## 📋 元数据",
            "",
            f"- **原始链接**：{url}",
            f"- **剪藏时间**：{now}",
            "- **来源类型**：web",
            f"- **领域**：{category}",
            "- **抓取状态**：成功",
            f"- **原始标题**：{metadata.get('title', title)}",
            f"- **描述**：{metadata.get('description', '')}",
            f"- **语言**：{metadata.get('language', '')}",
        ]

        output_dir.mkdir(parents=True, exist_ok=True)

        # ── 下载正文中的图片到本地（需求 T14：Firecrawl 图片本地化）──
        full_md = "\n".join(md_lines)
        img_urls = _extract_md_image_urls(full_md)
        if img_urls:
            limits = _CONFIG.get("limits", {})
            max_images = limits.get("max_images", 20)
            blacklist = _CONFIG.get("unsupported_image_domains", [])
            dl_urls = [u for u in img_urls[:max_images] if not _is_domain_blacklisted(u, blacklist)]
            remote_kept = len(img_urls[:max_images]) - len(dl_urls)
            if remote_kept:
                result["warnings"].append(f"图片防盗链保留远程链接({remote_kept}张)")
            if dl_urls:
                img_dir = output_dir / "images"
                downloaded, failed, failed_urls = await _download_images(
                    dl_urls,
                    img_dir,
                    referer=url,
                )
                if failed > 0:
                    result["warnings"].append(
                        f"图片下载: {downloaded}/{len(dl_urls)} 成功, {failed} 失败"
                    )
                full_md = _replace_md_image_refs(full_md, dl_urls, img_dir)

        md_path = output_dir / "article.md"
        md_path.write_text(full_md, encoding="utf-8")
        result["md_file"] = str(md_path)
        result["success"] = True
        _log.info("firecrawl_clip_success", url=url, title=title)

    except Exception as e:
        result["error"] = f"Firecrawl 请求失败: {e}"
        _log.warning("firecrawl_clip_failed", url=url, error=str(e))

    return result


def _extract_title_from_md(md_text: str) -> str:
    """从 Markdown 中提取第一个 # 标题"""
    for line in md_text.split("\n"):
        line = line.strip()
        if line.startswith("# ") and len(line) > 2:
            return line[2:].strip()
    return ""


def check_dedup_before_clip(
    indexer: Any, url: str, content_hash: str | None = None
) -> dict[str, Any]:
    """在剪藏前检查去重(FR-010)。

    封装 Indexer.check_dedup(),供 clip.py 调用。

    Args:
        indexer: Indexer 实例
        url: 待查重的 URL
        content_hash: 内容哈希(可选,网页类剪藏通常不传)

    Returns:
        {"status": "duplicate"|"updated"|"new", "existing": list}
        - duplicate: URL + content_hash 均相同 → 完全重复,跳过
        - updated: URL 相同但 content_hash 不同 → 内容已更新,提示覆盖
        - new: URL 无匹配 → 非重复,正常剪藏
    """
    return cast(dict[str, Any], indexer.check_dedup(url, content_hash))


# ═══════════════════════════════════════════════════════════
# 本地后端（纯 httpx，无 Playwright）
# ═══════════════════════════════════════════════════════════


async def clip_webpage(
    url: str,
    output_dir: Path,
    download_images: bool = True,
    category: str = "其他收藏",
    category_fn: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """
    本地 httpx 抓取网页并保存为 Markdown（纯文本，无法处理JS渲染页面）。
    推荐使用 Firecrawl 后端。

    category: 默认/兜底领域
    category_fn: 可选 callable(title, description)->分类名；拿到标题后调用它覆盖 category

    Returns:
        dict: {success, title, md_file, images_downloaded, images_failed, warnings, error}
    """
    result: dict[str, Any] = {
        "success": False,
        "title": "无标题",
        "md_file": None,
        "images_downloaded": 0,
        "images_failed": 0,
        "warnings": [],
        "error": None,
        "fetch_backend": "httpx",
    }

    limits = _CONFIG.get("limits", {})
    fetch_timeout = limits.get("page_fetch_timeout", 20)
    max_images = limits.get("max_images", 20)

    # httpx 抓取
    html = None
    page_cookies = {}
    try:
        async with httpx.AsyncClient(
            timeout=fetch_timeout, follow_redirects=True, trust_env=False
        ) as client:
            resp = await client.get(url, headers=_DEFAULT_HEADERS)
            resp.raise_for_status()
            html = resp.text
            # 提取 Cookie 供后续图片请求复用。
            # dict(resp.cookies) 同时兼容真实 httpx.Cookies 与夹具里的普通 dict；
            # 失败则置空（mp 图靠 referer 通常已够）。
            try:
                page_cookies = dict(resp.cookies)
            except Exception:
                page_cookies = {}
    except Exception as e:
        # 失败占位 md（需求 6.4）
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / "article.md"
        md_path.write_text(
            _build_placeholder_md(
                urlparse(url).netloc,
                url,
                f"httpx 抓取失败: {e}",
                partial_info=["标题：未知（未能抓取页面）"],
                fetch_method="httpx",
                category=category,
                status="失败",
            ),
            encoding="utf-8",
        )
        result["md_file"] = str(md_path)
        result["title"] = urlparse(url).netloc
        result["error"] = f"httpx 抓取失败: {e}（JS渲染页面请配置 Firecrawl）"
        _log.warning("httpx_fetch_failed", url=url, error=str(e))
        return result

    # 提取标题
    title = _extract_title(html) or urlparse(url).netloc
    result["title"] = title

    # 拿到真实标题后回算领域（覆盖默认）
    if category_fn is not None:
        with contextlib.suppress(Exception):
            category = category_fn(title, "") or category
    result["category"] = category

    # 归一化懒加载图（微信等 data-src）→ src，html2text 才能 render 图片
    html = normalize_lazy_imgs(html)
    html = _wrap_images_in_blocks(html)

    # HTML → Markdown
    try:
        md_body = _html_to_markdown(html, url)
    except Exception as e:
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / "article.md"
        md_path.write_text(
            _build_placeholder_md(
                title,
                url,
                f"HTML转Markdown失败: {e}",
                partial_info=[f"标题：{title}"],
                fetch_method="httpx",
                category=category,
                status="失败",
            ),
            encoding="utf-8",
        )
        result["md_file"] = str(md_path)
        result["error"] = f"HTML转Markdown失败: {e}"
        return result

    max_chars = limits.get("max_content_chars", 50000)
    if len(md_body) > max_chars:
        md_body = md_body[:max_chars] + "\n\n> ⚠️ 内容过长，已截断"

    # 提取并下载图片
    img_dir = output_dir / "images"
    img_warnings = []
    if download_images:
        blacklist = _CONFIG.get("unsupported_image_domains", [])
        all_img_urls = _extract_image_urls(html, url)[:max_images]
        # 页面 host（判定微信文章：referer 是 mp.weixin 时，图床 mmbiz/qpic
        # 带这 referer 即可下载，故对这种页面跳过黑名单放弃下载逻辑）
        page_host = urlparse(url).netloc.lower()
        is_weixin_article = "mp.weixin.qq.com" in page_host
        img_urls = []
        remote_kept = []
        for u in all_img_urls:
            if _is_domain_blacklisted(u, blacklist) and not is_weixin_article:
                remote_kept.append(u)
            else:
                img_urls.append(u)
        if remote_kept:
            img_warnings.append(
                f"图片防盗链保留远程链接({len(remote_kept)}张)："
                + ", ".join(remote_kept[:3])
                + ("..." if len(remote_kept) > 3 else "")
            )
        if img_urls:
            img_dir.mkdir(parents=True, exist_ok=True)
            downloaded, failed, failed_urls = await _download_images(
                img_urls, img_dir, referer=url, cookies=page_cookies
            )
            result["images_downloaded"] = downloaded
            result["images_failed"] = failed

            if failed > 0:
                img_warnings.append(f"图片下载: {downloaded}/{len(img_urls)} 成功, {failed} 失败")
                if failed_urls:
                    img_warnings.append(
                        f"失败图片: {', '.join(failed_urls[:5])}"
                        + ("..." if len(failed_urls) > 5 else "")
                    )
            md_body = _replace_image_refs(md_body, img_urls, img_dir)

    # 写入 MD
    md_path = output_dir / "article.md"
    md_content = _build_markdown(
        title, url, md_body, img_warnings, "httpx", category=category, status="成功"
    )

    try:
        md_path.write_text(md_content, encoding="utf-8")
        result["md_file"] = str(md_path)
        result["success"] = True
        result["warnings"].extend(img_warnings)
    except Exception as e:
        result["error"] = f"写入MD文件失败: {e}"

    return result


# ═══════════════════════════════════════════════════════════
# HTML 解析工具
# ═══════════════════════════════════════════════════════════


def _extract_title(html: str) -> str | None:
    """从 HTML 中提取标题。微信文章优先 og:title，其次 <title>"""
    is_weixin = "mp.weixin.qq.com" in html
    patterns = [
        r'<meta\s+property="og:title"\s+content="([^"]*)"',
        r'<meta\s+name="twitter:title"\s+content="([^"]*)"',
        r"<title[^>]*>([^<]+)</title>",
        r"<h1[^>]*>([^<]+)</h1>",
    ]
    for pattern in patterns:
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            title = m.group(1).strip()
            if title:
                import html as html_mod

                title = html_mod.unescape(title)
                # 微信 <title> 格式常为 「标题」，去掉首尾引号类字符
                if is_weixin and pattern.startswith("<title"):
                    title = title.strip("「」\"'")
                return title
    return None


def _html_to_markdown(html: str, base_url: str) -> str:
    """将 HTML 转为 Markdown，保留格式。微信文章只取 #js_content 正文"""
    is_weixin = "mp.weixin.qq.com" in html

    # 移除无关标签（script/style 含大量非正文文本，nav/footer 是导航）
    for tag in ["script", "style", "nav", "footer", "iframe", "noscript", "header"]:
        html = re.sub(
            rf"<{tag}[\s>][\s\S]*?</{tag}>",
            "",
            html,
            flags=re.IGNORECASE,
        )

    if is_weixin:
        # 微信文章：只取 #js_content 正文容器，丢弃页面框架噪音
        js_match = re.search(
            r'<div[^>]*\bid="js_content"[^>]*>([\s\S]*?)(?:</div>\s*(?:<script|<div[^>]*\bclass="rich_media_area_extra|$))',
            html,
            re.IGNORECASE,
        )
        if js_match:
            html = js_match.group(1)
        # 清洗微信正文内的噪音元素
        html = _clean_wechat_html(html)
    else:
        # 提取 <body> 内容
        body_match = re.search(
            r"<body[^>]*>([\s\S]*)</body>",
            html,
            re.IGNORECASE,
        )
        if body_match:
            html = body_match.group(1)

    h = html2text.HTML2Text()
    h.body_width = 0  # 不自动折行
    h.ignore_links = False  # 保留链接
    h.ignore_images = False  # 保留图片
    h.ignore_emphasis = False  # 保留加粗/斜体
    h.protect_links = False
    h.unicode_snob = True
    h.skip_internal_links = False
    h.default_image_alt = ""

    md = h.handle(html)
    # 压缩多余空行（但保留段落间距）
    md = re.sub(r"\n{4,}", "\n\n\n", md)
    md = re.sub(r"\n{3}", "\n\n", md)
    return md.strip()


def normalize_lazy_imgs(html: str) -> str:
    """把 <img data-src> 的懒加载图片 URL 复制到 src 属性。

    微信公众号等页面正文图普遍用 `data-src`（懒加载），html2text 只渲染
    `src` 属性——不归一化会导致 md 正文里一张微信图都看不到。
    已有 src（含空值）的标签，用 data-src 覆盖；否则补一个 src 属性。
    """

    def repl(m: re.Match[str]) -> str:
        tag = m.group(0)
        ds = re.search(r'data-src=["\']([^"\']+)["\']', tag, re.IGNORECASE)
        if not ds:
            return tag
        url = ds.group(1)
        # 用负向回看排除 data-src 里的 src（避免误判已存在 src）
        if re.search(r"(?<![A-Za-z\-])src=", tag):
            tag = re.sub(
                r'(?<![A-Za-z\-])src=["\'][^"\']*["\']',
                f'src="{url}"',
                tag,
                count=1,
            )
        else:
            # 在标签末尾的 / 或 > 前插入 src 属性
            tag = re.sub(r"(/?)>$", f' src="{url}"\\1>', tag, count=1)
        return tag

    return re.sub(r"<img[^>]*?>", repl, html, flags=re.IGNORECASE)


def _clean_wechat_html(html: str) -> str:
    """移除微信正文内常见的噪音元素（mp-common-* 组件、投票、赞赏等）。"""
    # 移除自定义标签 <mp-common-*> 及其内容
    html = re.sub(
        r"<mp-common-\w+[^>]*>[\s\S]*?</mp-common-\w+>",
        "",
        html,
        flags=re.IGNORECASE,
    )
    # 移除微信内嵌的 iframe（视频、广告等）
    html = re.sub(r"<iframe[^>]*>[\s\S]*?</iframe>", "", html, flags=re.IGNORECASE)
    # 移除 ooooo_message_link / product 等无关组件
    for cls in [
        "rich_media_area_extra",
        "reward_area",
        "original_area_primary",
        "rich_media_tool",
        "rich_media_meta_list",
        "profile_container",
    ]:
        html = re.sub(
            rf'<div[^>]*\bclass="[^"]*\b{cls}\b[^"]*"[^>]*>[\s\S]*?</div>',
            "",
            html,
            flags=re.IGNORECASE,
        )
    return html


def _wrap_images_in_blocks(html: str) -> str:
    """将不在块级元素内的独立 <img> 包裹进 <p>，使 html2text 渲染为独立行。

    微信正文中图片常与文字混在同一 <p> 内，html2text 产出形如
    「文字![](img)文字」的行内混排。将 <img> 提到独立段落可确保
    markdown 图片独占一行、前后各空一行，增强可读性。
    """

    def _wrap(m: re.Match[str]) -> str:
        tag = m.group(0)
        # 只处理不在块级容器内的 img（避免二次包裹）
        return f"<p>{tag}</p>"

    # 匹配不在 <p>, <figure>, <div>, <li>, <blockquote> 等块级标签内的 <img>
    return re.sub(
        r"(?<!<p>)(?<!<figure>)(?<!<div>)(?<!<li>)(?<!<blockquote>)"
        r"\s*<img[^>]*>\s*"
        r"(?!</p>)(?!</figure>)(?!</div>)(?!</li>)(?!</blockquote>)",
        _wrap,
        html,
        flags=re.IGNORECASE,
    )


def _extract_image_urls(html: str, base_url: str) -> list[str]:
    """提取 HTML 中的图片链接（优先 data-src 懒加载，其次 src），转绝对URL，去重"""
    urls: list[str] = []
    seen: set[str] = set()
    # 先抓 data-src（微信等懒加载页面），再抓 src；统一处理
    img_pattern = re.compile(
        r'<img[^>]*?(?:data-src|src)=["\']([^"\']+)["\']',
        re.IGNORECASE,
    )
    for m in img_pattern.finditer(html):
        src = m.group(1)
        if src.startswith("data:"):
            continue
        full_url = urljoin(base_url, src)
        if full_url not in seen:
            seen.add(full_url)
            urls.append(full_url)
    return urls


def _is_domain_blacklisted(url: str, blacklist: list[str]) -> bool:
    """判断图片 URL 的 host 是否命中已知的不可本地化域名黑名单"""
    host = urlparse(url).netloc.lower()
    return any(bad in host for bad in (blacklist or []))


# ═══════════════════════════════════════════════════════════
# 图片下载
# ═══════════════════════════════════════════════════════════


async def _download_images(
    img_urls: list[str],
    img_dir: Path,
    referer: str = "",
    cookies: dict[str, Any] | None = None,
) -> tuple[int, int, list[str]]:
    """异步下载图片，返回 (成功数, 失败数, 失败URL列表)

    防盗链策略：
    - 带上页面的 Referer 头（最关键），并尝试 origin 再尝试 host
    - 复用页面请求的 Cookie
    - 先尝试下载，不预先黑名单过滤（黑名单在调用方处理）
    - 宽松的 Content-Type 检查
    """
    imgs_path = Path(img_dir)
    imgs_path.mkdir(parents=True, exist_ok=True)

    limits = _CONFIG.get("limits", {})
    img_timeout = limits.get("image_timeout", 10)

    if cookies is None:
        cookies = {}

    # 页面 host（用于以站点自身为 Referer 的重试，绕过部分严格的防盗链）
    page_origin = ""
    if referer:
        p = urlparse(referer)
        page_origin = f"{p.scheme}://{p.netloc}"

    async def download_one(idx: int, img_url: str) -> str | None:
        # Referer 候选：原页面 URL → 页面 origin → 页面 host
        referer_candidates = []
        if referer:
            referer_candidates.append(referer)
        if page_origin:
            referer_candidates.append(page_origin)

        for ref in referer_candidates:
            try:
                # 构建请求头：UA + Referer（防盗链关键） + Cookie
                headers = dict(_DEFAULT_HEADERS)
                headers["Sec-Fetch-Site"] = (
                    "cross-site"
                    if urlparse(img_url).netloc != urlparse(ref).netloc
                    else "same-origin"
                )
                headers["Sec-Fetch-Mode"] = "no-cors"
                headers["Sec-Fetch-Dest"] = "image"
                headers["Accept"] = (
                    "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
                )
                headers["Referer"] = ref
                if cookies:
                    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
                    headers["Cookie"] = cookie_str

                async with httpx.AsyncClient(
                    timeout=img_timeout, follow_redirects=True, trust_env=False
                ) as client:
                    resp = await client.get(img_url, headers=headers)
                    resp.raise_for_status()

                    content_type = resp.headers.get("Content-Type", "").lower()
                    # 宽松检查：只要不是明确的 HTML/文本错误页就尝试保存
                    if "text/html" in content_type:
                        continue  # 被重定向到登录页/错误页，换 Referer 再试
                    if len(resp.content) == 0:
                        continue

                    ext = _guess_ext(img_url, content_type)
                    filename = f"img_{idx:02d}{ext}"
                    (imgs_path / filename).write_bytes(resp.content)
                    return filename
            except Exception:
                continue
        return None

    tasks = [download_one(i, url) for i, url in enumerate(img_urls, 1)]
    results = await asyncio.gather(*tasks)

    succeeded = sum(1 for r in results if r is not None)
    failed = len(results) - succeeded

    # 收集失败的 URL
    failed_urls = []
    for img_url, local_name in zip(img_urls, results, strict=False):
        if local_name is None:
            # 截短 URL 用于显示
            short = img_url[:80] + "..." if len(img_url) > 80 else img_url
            failed_urls.append(short)

    # 保存 URL→本地路径 映射
    mapping = {}
    for img_url, local_name in zip(img_urls, results, strict=False):
        if local_name:
            mapping[img_url] = f"images/{local_name}"

    import json as json_mod

    (img_dir / "_mapping.json").write_text(json_mod.dumps(mapping, ensure_ascii=False, indent=2))

    return succeeded, failed, failed_urls


def _guess_ext(url: str, content_type: str) -> str:
    """猜测图片扩展名"""
    ext_map = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "image/bmp": ".bmp",
    }
    for mime, ext in ext_map.items():
        if mime in content_type:
            return ext
    path = urlparse(url).path.lower()
    for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"]:
        if path.endswith(ext):
            return ext
    return ".jpg"


def _replace_image_refs(md_body: str, img_urls: list[str], img_dir: Path) -> str:
    """将 Markdown 中的远程图片链接替换为本地相对路径。

    按"URL path 前缀"匹配（去掉 query 后的净 path），而非字面全 URL 精确匹配。
    原因：html2text 转换后的 md 中，微信 mmbiz 图片 URL 常带额外 query
    （&from=appmsg 等）或被 markdown 特殊字符截断，与映射表的完整 URL 不完全
    一致；用 path 段前缀匹配可稳健地把同源图都归拢到本地。
    """
    import json as json_mod

    mapping_file = img_dir / "_mapping.json"
    if not mapping_file.exists():
        return md_body

    mapping: dict[str, str] = json_mod.loads(mapping_file.read_text(encoding="utf-8"))

    url_map: dict[str, str] = {}
    for remote_url, local_path in mapping.items():
        url_map[remote_url] = local_path
    return _replace_md_urls(md_body, url_map)


def _extract_md_image_urls(md_text: str) -> list[str]:
    """从 Markdown 文本中提取所有图片 URL（去重、保留顺序）。"""
    urls: list[str] = []
    seen: set[str] = set()
    # Markdown 图片: ![alt](url)
    for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", md_text):
        url = m.group(1)
        if url not in seen and not url.startswith("data:"):
            seen.add(url)
            urls.append(url)
    # HTML img 标签（Firecrawl 有时保留 HTML）: <img src="url" ...>
    for m in re.finditer(
        r'<img[^>]*?src=["\']([^"\']+)["\']',
        md_text,
        re.IGNORECASE,
    ):
        url = m.group(1)
        if url not in seen and not url.startswith("data:"):
            seen.add(url)
            urls.append(url)
    return urls


def _replace_md_image_refs(md_body: str, img_urls: list[str], img_dir: Path) -> str:
    """将 markdown 正文中的远程图片 URL 替换为本地相对路径。

    使用与 _replace_image_refs 相同的策略：先精确匹配，再前缀正则匹配。
    """
    import json as json_mod

    mapping_file = img_dir / "_mapping.json"
    if not mapping_file.exists():
        return md_body

    mapping: dict[str, str] = json_mod.loads(mapping_file.read_text(encoding="utf-8"))
    return _replace_md_urls(md_body, mapping)


def _replace_md_urls(md_body: str, url_map: dict[str, str]) -> str:
    """核心替换逻辑：按 URL→新路径映射替换 markdown 中的远程链接。

    先精确匹配，再前缀正则（处理带 query 参数的 URL 变体）。
    """

    def net_prefix(u: str) -> str:
        p = urlparse(u)
        return f"{p.scheme}://{p.netloc}{p.path}"

    for remote_url, local_path in url_map.items():
        np = net_prefix(remote_url)
        # 先试完整 URL 精确匹配（含 query string），避免 query 残留
        if remote_url in md_body:
            md_body = md_body.replace(remote_url, local_path)
            continue
        # 再用前缀正则：匹配 net_prefix 起始、后面跟任意非空白/括号尾巴的整段 URL
        pattern = re.escape(np) + r"[^)\s\"'\\]*"
        md_body = re.sub(pattern, local_path, md_body)
    return md_body


# ═══════════════════════════════════════════════════════════
# Markdown 文件构建
# ═══════════════════════════════════════════════════════════


def _build_markdown(
    title: str,
    url: str,
    body: str,
    warnings: list[str],
    fetch_method: str = "httpx",
    category: str = "其他收藏",
    status: str = "成功",
    screenshot_path: str | None = None,
) -> str:
    """组装最终的 Markdown 文件。

    screenshot_path: 截图本地路径；若提供且文件名用于 md 引用（一般同目录），
    则在头部 --- 后、正文前插入「整页长截图」引用块（需求 §5.1）。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# {title}",
        "",
        f"> 📅 剪藏时间：{now}",
        f"> 🔗 来源：[{url}]({url})",
        "> 🔧 抓取方式：⚡ 直接抓取",
        f"> 📁 领域：{category}",
        "> 🏷️ 来源类型：web",
        f"> ✅ 抓取状态：{status}",
        "",
        "---",
        "",
    ]
    if screenshot_path:
        ss_name = Path(screenshot_path).name
        lines += [
            "## 🖼️ 整页长截图",
            "",
            f"![长截图]({ss_name})",
            "",
        ]
    lines += [
        body,
        "",
        "---",
        "",
        "## 📋 元数据",
        "",
        f"- **原始链接**：{url}",
        f"- **剪藏时间**：{now}",
        "- **来源类型**：web",
        f"- **领域**：{category}",
        f"- **抓取状态**：{status}",
    ]

    if warnings:
        lines.append("\n## ⚠️ 警告\n")
        for w in warnings:
            lines.append(f"- {w}")

    return "\n".join(lines)


def _build_placeholder_md(
    title: str,
    url: str,
    reason: str,
    partial_info: list[str],
    fetch_method: str = "未知",
    category: str = "其他收藏",
    status: str = "失败",
    screenshot_path: str | None = None,
) -> str:
    """构建失败占位 Markdown（需求 6.4）。

    status: 失败 / 部分失败
    partial_info: 已获取信息条目列表[str]
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# {title}",
        "",
        f"> 📅 剪藏时间：{now}",
        f"> 🔗 来源：[{url}]({url})",
        "> 🏷️ 来源类型：web",
        f"> 📁 领域：{category}",
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
    if screenshot_path:
        lines += [
            "## 🖼️ 长截图",
            "",
            f"![长截图]({Path(screenshot_path).name})",
            "",
        ]
    lines += [
        "---",
        "",
        "## 📋 元数据",
        "",
        f"- **原始链接**：{url}",
        f"- **剪藏时间**：{now}",
        "- **来源类型**：web",
        f"- **领域**：{category}",
        f"- **抓取状态**：{status}",
        f"- **抓取方式**：{fetch_method}",
    ]
    return "\n".join(lines)
