"""整页长截图模块单元测试(T062 覆盖补充)。

验证 clipper.screenshot.take_fullpage_screenshot:
  - 成功路径(mock playwright,截图落盘)
  - 失败路径(playwright 抛异常,返回 {success:False})
  - store_screenshot=False 时截图不落盘但 success=True
  - full_page 配置项(整页 vs 首屏)
  - playwright 未安装时回退
  - 配置关闭(enabled=false / engine=off)
  - mock 路径(CLIP_SCREENSHOT_MOCK / CLIP_SCREENSHOT_MOCK_FAIL)
"""

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clipper.screenshot import take_fullpage_screenshot

# ── 配置 fixture ────────────────────────────────────────────


def _write_screenshot_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool = True,
    engine: str = "auto",
    full_page: bool = True,
    store_screenshot: bool = True,
) -> Path:
    """写入临时配置并注入。"""
    import yaml

    cfg = {
        "storage": {"base_dir": str(tmp_path / "clipped_pages"), "index_file": "_index.json"},
        "categories": ["科技与AI", "其他收藏"],
        "category_keywords": {"科技与AI": ["python"], "其他收藏": []},
        "screenshot": {
            "enabled": enabled,
            "engine": engine,
            "timeout": 30,
            "user_agent": "",
            "full_page": full_page,
            "store_screenshot": store_screenshot,
        },
        "limits": {"max_file_size_mb": 20, "max_video_duration_min": 15},
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr("clipper.config._CONFIG_CACHE", None)
    monkeypatch.setattr("clipper.config._DEFAULT_CONFIG_PATH", cfg_path)
    for key in ("CLIP_SCREENSHOT_MOCK", "CLIP_SCREENSHOT_MOCK_FAIL"):
        monkeypatch.delenv(key, raising=False)
    return cfg_path


@pytest.fixture
def screenshot_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """注入临时配置(启用 playwright,store_screenshot=True,full_page=True)。"""
    return _write_screenshot_config(tmp_path, monkeypatch)


# ── fake playwright 模块注入 ─────────────────────────────────


def _build_mock_chain(target: Path, *, goto_side_effect=None, screenshot_fn=None):
    """构造 playwright mock 链并返回 async_playwright 入口(异步上下文管理器)。

    Args:
        target: 截图目标路径(用于默认 screenshot 落盘)
        goto_side_effect: page.goto 的 side_effect(None 表示成功)
        screenshot_fn: 自定义 page.screenshot 实现(签名 async (path, full_page) -> None)
    """
    if screenshot_fn is None:

        async def _default_screenshot(*, path=None, full_page=True):
            Path(path).write_bytes(b"\x89PNG fake screenshot bytes")

        screenshot_fn = _default_screenshot

    mock_page = MagicMock()
    mock_page.screenshot = screenshot_fn
    mock_page.goto = AsyncMock(
        side_effect=goto_side_effect if goto_side_effect else None,
        return_value=None if not goto_side_effect else None,
    )
    mock_page.evaluate = AsyncMock(return_value=None)
    mock_page.wait_for_load_state = AsyncMock(return_value=None)
    mock_page.wait_for_timeout = AsyncMock(return_value=None)
    mock_page.wait_for_function = AsyncMock(return_value=None)

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock(return_value=None)
    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_playwright = MagicMock()
    mock_playwright.chromium = mock_chromium

    mock_async_pw = MagicMock()
    mock_async_pw.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_async_pw.__aexit__ = AsyncMock(return_value=None)
    return mock_async_pw


def _install_fake_playwright(mock_async_pw):
    """返回 sys.modules 注入字典:fake playwright.async_api.async_playwright。"""
    fake_api = types.ModuleType("playwright.async_api")
    fake_api.async_playwright = lambda: mock_async_pw
    fake_pkg = types.ModuleType("playwright")
    fake_pkg.__path__ = []  # 标记为包
    return {"playwright": fake_pkg, "playwright.async_api": fake_api}


# ── 环境变量清理(autouse) ────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_screenshot_env(monkeypatch: pytest.MonkeyPatch):
    """每个测试前后确保截图相关环境变量被清理。"""
    for key in ("CLIP_SCREENSHOT_MOCK", "CLIP_SCREENSHOT_MOCK_FAIL"):
        monkeypatch.delenv(key, raising=False)
    yield


# ── 成功路径 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_screenshot_success(screenshot_config, tmp_path: Path):
    """playwright 正常截图:返回 success=True 与本地文件路径。"""
    output_dir = tmp_path / "out"
    target = output_dir / "screenshot.png"
    mock_async_pw = _build_mock_chain(target)

    with patch.dict(sys.modules, _install_fake_playwright(mock_async_pw)):
        result = await take_fullpage_screenshot("https://example.com/article", output_dir)

    assert result["success"] is True
    assert result["screenshot_file"] == str(target)
    assert result["error"] is None
    assert result["method"] == "playwright"
    assert Path(result["screenshot_file"]).exists()


@pytest.mark.asyncio
async def test_screenshot_success_with_explicit_timeout(screenshot_config, tmp_path: Path):
    """显式传入 timeout / user_agent 时优先使用调用方参数。"""
    output_dir = tmp_path / "out"
    target = output_dir / "screenshot.png"
    mock_async_pw = _build_mock_chain(target)

    with patch.dict(sys.modules, _install_fake_playwright(mock_async_pw)):
        result = await take_fullpage_screenshot(
            "https://example.com/article",
            output_dir,
            timeout=15,
            user_agent="Mozilla/5.0 Test UA",
        )

    assert result["success"] is True


# ── 失败路径 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_screenshot_failure_returns_not_success(screenshot_config, tmp_path: Path):
    """playwright 抛异常时返回 success=False 与错误信息。"""
    output_dir = tmp_path / "out"
    mock_async_pw = _build_mock_chain(
        output_dir / "screenshot.png",
        goto_side_effect=RuntimeError("navigation timeout"),
    )

    with patch.dict(sys.modules, _install_fake_playwright(mock_async_pw)):
        result = await take_fullpage_screenshot("https://example.com/article", output_dir)

    assert result["success"] is False
    assert result["error"] is not None
    assert "Playwright 截图失败" in result["error"]
    assert "navigation timeout" in result["error"]
    assert result["method"] == "playwright"
    assert result["screenshot_file"] is None


@pytest.mark.asyncio
async def test_screenshot_failure_cleans_partial_file(screenshot_config, tmp_path: Path):
    """截图失败时清理已产生的半成品文件。"""
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "screenshot.png"
    target.write_bytes(b"partial")  # 模拟半成品

    mock_async_pw = _build_mock_chain(target, goto_side_effect=RuntimeError("boom"))

    with patch.dict(sys.modules, _install_fake_playwright(mock_async_pw)):
        result = await take_fullpage_screenshot("https://example.com/article", output_dir)

    assert result["success"] is False
    assert not target.exists()  # 失败产物已清理


# ── store_screenshot=False ──────────────────────────────────


@pytest.mark.asyncio
async def test_screenshot_store_screenshot_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """store_screenshot=False 时截图成功但不落盘文件。"""
    _write_screenshot_config(tmp_path, monkeypatch, store_screenshot=False)
    output_dir = tmp_path / "out"
    target = output_dir / "screenshot.png"

    # screenshot 不应被调用(因 store_screenshot=False 提前 return)
    async def _no_screenshot(**kwargs):
        raise AssertionError("不应调用 screenshot")

    mock_async_pw = _build_mock_chain(target, screenshot_fn=_no_screenshot)

    with patch.dict(sys.modules, _install_fake_playwright(mock_async_pw)):
        result = await take_fullpage_screenshot("https://example.com/article", output_dir)

    assert result["success"] is True
    assert result["method"] == "playwright"
    assert result["screenshot_file"] is None
    assert not target.exists()


# ── full_page 配置(首屏 vs 整页) ────────────────────────────


@pytest.mark.asyncio
async def test_screenshot_full_page_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """full_page=False 时 page.screenshot 收到 full_page=False(首屏截图)。"""
    _write_screenshot_config(tmp_path, monkeypatch, full_page=False)
    output_dir = tmp_path / "out"
    captured: dict = {}

    async def fake_screenshot(*, path=None, full_page=True):
        captured["full_page"] = full_page
        Path(path).write_bytes(b"png")

    mock_async_pw = _build_mock_chain(output_dir / "screenshot.png", screenshot_fn=fake_screenshot)

    with patch.dict(sys.modules, _install_fake_playwright(mock_async_pw)):
        result = await take_fullpage_screenshot("https://example.com/article", output_dir)

    assert result["success"] is True
    assert captured["full_page"] is False


@pytest.mark.asyncio
async def test_screenshot_full_page_true_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """full_page=True(默认)时 page.screenshot 收到 full_page=True(整页)。"""
    _write_screenshot_config(tmp_path, monkeypatch, full_page=True)
    output_dir = tmp_path / "out"
    captured: dict = {}

    async def fake_screenshot(*, path=None, full_page=True):
        captured["full_page"] = full_page
        Path(path).write_bytes(b"png")

    mock_async_pw = _build_mock_chain(output_dir / "screenshot.png", screenshot_fn=fake_screenshot)

    with patch.dict(sys.modules, _install_fake_playwright(mock_async_pw)):
        result = await take_fullpage_screenshot("https://example.com/article", output_dir)

    assert result["success"] is True
    assert captured["full_page"] is True


# ── 配置关闭 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_screenshot_disabled_by_enabled_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """screenshot.enabled=False 时跳过截图,返回 method=none。"""
    _write_screenshot_config(tmp_path, monkeypatch, enabled=False)

    result = await take_fullpage_screenshot("https://example.com/article", tmp_path / "out")

    assert result["success"] is False
    assert result["method"] == "none"
    assert result["error"] is not None


@pytest.mark.asyncio
async def test_screenshot_disabled_by_engine_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """screenshot.engine='off' 时跳过截图,返回 method=none。"""
    _write_screenshot_config(tmp_path, monkeypatch, engine="off")

    result = await take_fullpage_screenshot("https://example.com/article", tmp_path / "out")

    assert result["success"] is False
    assert result["method"] == "none"


# ── playwright 未安装回退 ────────────────────────────────────


@pytest.mark.asyncio
async def test_screenshot_playwright_not_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """playwright 未安装时返回 method=none 与安装提示。

    真实环境未装 playwright,故不注入 fake 模块,触发 ImportError。
    patch.dict 自动还原 sys.modules,无需手动清理。
    """
    _write_screenshot_config(tmp_path, monkeypatch)

    result = await take_fullpage_screenshot("https://example.com/article", tmp_path / "out")

    assert result["success"] is False
    assert result["method"] == "none"
    assert "playwright 未安装" in result["error"]


# ── mock 路径环境变量 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_screenshot_mock_env_copies_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """CLIP_SCREENSHOT_MOCK 指向已有 png 时复制为目标截图。"""
    _write_screenshot_config(tmp_path, monkeypatch)

    src_png = tmp_path / "src.png"
    src_png.write_bytes(b"fake png content")
    monkeypatch.setenv("CLIP_SCREENSHOT_MOCK", str(src_png))

    output_dir = tmp_path / "out"
    result = await take_fullpage_screenshot("https://example.com/article", output_dir)

    assert result["success"] is True
    assert result["method"] == "mock"
    assert result["screenshot_file"] == str(output_dir / "screenshot.png")
    assert Path(result["screenshot_file"]).read_bytes() == b"fake png content"


@pytest.mark.asyncio
async def test_screenshot_mock_fail_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """CLIP_SCREENSHOT_MOCK_FAIL=1 强制截图失败(验证降级)。"""
    _write_screenshot_config(tmp_path, monkeypatch)
    monkeypatch.setenv("CLIP_SCREENSHOT_MOCK_FAIL", "1")

    result = await take_fullpage_screenshot("https://example.com/article", tmp_path / "out")

    assert result["success"] is False
    assert result["method"] == "mock"
    assert "mock强制失败" in result["error"]


@pytest.mark.asyncio
async def test_screenshot_mock_env_missing_file_falls_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """CLIP_SCREENSHOT_MOCK 指向不存在文件时回退到真实 playwright 路径。"""
    _write_screenshot_config(tmp_path, monkeypatch)
    monkeypatch.setenv("CLIP_SCREENSHOT_MOCK", str(tmp_path / "nonexistent.png"))

    output_dir = tmp_path / "out"
    target = output_dir / "screenshot.png"
    mock_async_pw = _build_mock_chain(target)

    with patch.dict(sys.modules, _install_fake_playwright(mock_async_pw)):
        result = await take_fullpage_screenshot("https://example.com/article", output_dir)

    # mock 文件不存在 → 回退真实 playwright 路径 → 成功
    assert result["success"] is True
    assert result["method"] == "playwright"
