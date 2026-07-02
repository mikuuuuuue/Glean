"""整页长截图模块 - 基于 Playwright headless chromium。

策略：
  优先本地 Playwright（headless chromium，无需显示器，NAS Linux 容器可用；
  page.screenshot(full_page=True) 抓整页）。
  未安装 playwright / 启动失败 / 超时 → 返回 {success:False}，
  由调用方决定是否回退到 Firecrawl 整页截图（见 clip.py::_capture_screenshot）。

本模块不抛异常给上层；任何错误都封装在返回 dict 里，确保截图失败不阻断正文剪藏。
"""

from pathlib import Path
from typing import Optional
import os
import shutil as _shutil


# ── 配置加载 ────────────────────────────────────────────
def _load_config():
    config_path = Path(__file__).parent.parent / "config.yaml"
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


_CONFIG = _load_config()


def _screenshot_config() -> dict:
    return _CONFIG.get("screenshot", {}) or {}


async def take_fullpage_screenshot(
    url: str,
    output_dir: Path,
    *,
    timeout: Optional[int] = None,
    user_agent: Optional[str] = None,
) -> dict:
    """对 url 做整页长截图，保存到 output_dir/screenshot.png。

    返回:
        dict: {success, screenshot_file, error, method}
            success: bool
            screenshot_file: str | None  本地路径
            error: str | None
            method: "playwright" | "none"
    """
    result = {
        "success": False,
        "screenshot_file": None,
        "error": None,
        "method": "playwright",
    }

    cfg = _screenshot_config()
    if cfg.get("enabled", True) is False or cfg.get("engine", "auto") == "off":
        result["method"] = "none"
        result["error"] = "截图已关闭 (screenshot.enabled=false或engine=off)"
        return result

    # 测试 mock：环境变量 CLIP_SCREENSHOT_MOCK=png路径 时，直接复制该文件为目标
    # 截图，跳过 Playwright（供 test_skill.py 在无真实浏览器环境验证截图接入用）。
    mock_png = os.environ.get("CLIP_SCREENSHOT_MOCK", "").strip()
    if mock_png:
        try:
            src = Path(mock_png)
            if src.exists():
                output_dir.mkdir(parents=True, exist_ok=True)
                target = Path(output_dir) / "screenshot.png"
                _shutil.copy(str(src), str(target))
                result["success"] = True
                result["screenshot_file"] = str(target)
                result["method"] = "mock"
                return result
        except Exception:
            pass  # mock 失败走真实路径
    # 测试 mock：CLIP_SCREENSHOT_MOCK_FAIL=1 强制截图失败（验证降级 warning）
    if os.environ.get("CLIP_SCREENSHOT_MOCK_FAIL", "").strip():
        result["method"] = "mock"
        result["error"] = "mock强制失败"
        return result

    # 参数默认从 config 取
    if timeout is None:
        timeout = int(cfg.get("timeout", 30))
    if user_agent is None:
        user_agent = cfg.get("user_agent", "") or None

    # Playwright 必须可选：未装则友好回退
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        result["method"] = "none"
        result["error"] = "playwright 未安装，请执行: pip install playwright && playwright install chromium"
        return result

    target = Path(output_dir) / "screenshot.png"
    try:
        async with async_playwright() as p:
            # headless chromium；不用 channel，NAS 容器不依赖桌面浏览器
            browser = await p.chromium.launch(headless=True)
            try:
                ctx_opts = {}
                if user_agent:
                    ctx_opts["user_agent"] = user_agent
                context = await browser.new_context(**ctx_opts)
                page = await context.new_page()
                # networkidle 对懒加载页面更稳；超时用配置值（毫秒）
                await page.goto(url, wait_until="networkidle",
                                timeout=timeout * 1000)
                output_dir.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(target), full_page=True)
                result["success"] = True
                result["screenshot_file"] = str(target)
            finally:
                await browser.close()
    except Exception as e:
        result["method"] = "playwright"
        result["error"] = f"Playwright 截图失败: {e}"
        # 失败产物清理
        try:
            if target.exists():
                target.unlink()
        except Exception:
            pass

    return result