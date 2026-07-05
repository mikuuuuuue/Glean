"""多平台适配器单元测试(T062 覆盖补充)。

验证:
  - PlatformAdapter 为抽象基类,不可实例化
  - BilibiliAdapter.platform_name 返回 "bilibili"
  - BilibiliAdapter.matches() 匹配 B站 URL / 拒绝非 B站 URL
  - BilibiliAdapter.clip() 委托给 clip_bilibili(mock 验证调用)
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from clipper.platform_base import PlatformAdapter
from clipper.platform_bilibili import BilibiliAdapter

# ── PlatformAdapter 抽象基类 ────────────────────────────────


def test_platform_adapter_is_abstract():
    """PlatformAdapter 是抽象基类,不能直接实例化。"""
    with pytest.raises(TypeError):
        PlatformAdapter()  # type: ignore[abstract]


def test_platform_adapter_subclass_must_implement_all_abstract():
    """子类未实现全部抽象成员时不能实例化。"""

    # 缺少 matches / clip 实现
    class IncompleteAdapter(PlatformAdapter):
        @property
        def platform_name(self) -> str:
            return "incomplete"

    with pytest.raises(TypeError):
        IncompleteAdapter()  # type: ignore[abstract]


# ── BilibiliAdapter.platform_name ──────────────────────────


def test_bilibili_adapter_platform_name():
    """platform_name 返回 "bilibili"。"""
    adapter = BilibiliAdapter()
    assert adapter.platform_name == "bilibili"


# ── BilibiliAdapter.matches ─────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "https://www.bilibili.com/video/av12345",
        "https://b23.tv/abc123",
        "https://www.bilibili.com/bangumi/play/ep12345",
    ],
)
def test_bilibili_adapter_matches_bilibili_urls(url: str):
    """B站 URL 匹配成功。"""
    adapter = BilibiliAdapter()
    assert adapter.matches(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/article",
        "https://www.youtube.com/watch?v=abc",
        "https://www.zhihu.com/question/123",
        "not a url",
        "",
    ],
)
def test_bilibili_adapter_matches_non_bilibili_urls(url: str):
    """非 B站 URL 不匹配。"""
    adapter = BilibiliAdapter()
    assert adapter.matches(url) is False


# ── BilibiliAdapter.clip ────────────────────────────────────


@pytest.mark.asyncio
async def test_bilibili_adapter_clip_delegates_to_clip_bilibili(tmp_path: Path):
    """clip() 委托给 clip_bilibili,并原样返回其结果。"""
    url = "https://www.bilibili.com/video/BV1xx411c7mD"
    expected_result = {
        "success": True,
        "title": "测试视频",
        "md_file": str(tmp_path / "video.md"),
        "has_subtitle": True,
        "subtitle_source": "official",
    }

    with patch(
        "clipper.platform_bilibili.clip_bilibili",
        new=AsyncMock(return_value=expected_result),
    ) as mock_clip:
        adapter = BilibiliAdapter()
        result = await adapter.clip(
            url, tmp_path, category="视频与影音", category_fn=lambda t, d: "视频与影音"
        )

    # 验证委托调用:正确传递 url / output_dir / kwargs
    mock_clip.assert_awaited_once()
    call_args = mock_clip.call_args
    assert call_args.args[0] == url
    assert call_args.args[1] == tmp_path
    assert call_args.kwargs.get("category") == "视频与影音"
    # 返回值原样透传
    assert result == expected_result
    assert result["success"] is True


@pytest.mark.asyncio
async def test_bilibili_adapter_clip_passes_category_fn(tmp_path: Path):
    """clip() 将 category_fn 透传给 clip_bilibili。"""
    url = "https://www.bilibili.com/video/BV1xx411c7mD"
    captured: dict = {}

    async def fake_clip(url_, out_dir, **kwargs):
        captured["url"] = url_
        captured["out_dir"] = out_dir
        captured["kwargs"] = kwargs
        return {"success": True, "subtitle_source": None}

    cat_fn = lambda t, d: "视频与影音"  # noqa: E731

    with patch("clipper.platform_bilibili.clip_bilibili", new=fake_clip):
        adapter = BilibiliAdapter()
        await adapter.clip(url, tmp_path, category_fn=cat_fn)

    assert captured["url"] == url
    assert captured["out_dir"] == tmp_path
    assert captured["kwargs"]["category_fn"] is cat_fn


@pytest.mark.asyncio
async def test_bilibili_adapter_clip_propagates_failure(tmp_path: Path):
    """clip_bilibili 返回失败结果时,adapter 原样透传(success=False)。"""
    url = "https://www.bilibili.com/video/BV1xx411c7mD"
    fail_result = {
        "success": False,
        "title": "未知视频",
        "md_file": None,
        "error": "bili-cli 执行失败",
        "subtitle_source": None,
    }

    with patch(
        "clipper.platform_bilibili.clip_bilibili",
        new=AsyncMock(return_value=fail_result),
    ):
        adapter = BilibiliAdapter()
        result = await adapter.clip(url, tmp_path)

    assert result == fail_result
    assert result["success"] is False
    assert result["error"] == "bili-cli 执行失败"
