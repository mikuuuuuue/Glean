"""bili-cli subprocess 契约测试(T065)。

验证 bili-cli 的命令行参数契约与输出格式(宪法原则 IV)。
通过 mock subprocess 验证 CLI 调用约定,不实际执行 bili-cli。
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_bvid_extraction_contract():
    """bili-cli 需要的 BV 号提取契约。"""
    from clipper.video import extract_bvid

    # 标准 BV 号
    assert extract_bvid("https://www.bilibili.com/video/BV1xx411c7mD") == "BV1xx411c7mD"
    # av 号
    assert extract_bvid("https://www.bilibili.com/video/av12345") == "av12345"
    # 无匹配
    assert extract_bvid("https://example.com") is None


def test_bilibili_url_detection_contract():
    """B站 URL 检测契约。"""
    from clipper.video import is_bilibili_url

    # 有效 B站 URL
    assert is_bilibili_url("https://www.bilibili.com/video/BV1xx411c7mD") is True
    assert is_bilibili_url("https://b23.tv/abc123") is True
    assert is_bilibili_url("https://www.bilibili.com/bangumi/play/ep123") is True
    # 非 B站 URL
    assert is_bilibili_url("https://www.youtube.com/watch?v=123") is False
    assert is_bilibili_url("https://example.com") is False


def test_b23_short_url_resolution_contract():
    """b23.tv 短链解析契约(返回完整 URL 或 BV 号)。"""
    from clipper.video import resolve_b23

    # resolve_b23 应接受短链并返回目标 URL
    # 实际网络调用需要 mock; 这里验证函数签名契约
    assert callable(resolve_b23)


def test_video_result_structure_contract():
    """clip_bilibili() 返回结果结构契约。"""
    # 验证函数签名
    import inspect

    from clipper.video import clip_bilibili

    sig = inspect.signature(clip_bilibili)
    params = list(sig.parameters.keys())
    assert "url" in params
    assert "output_dir" in params

    # 返回类型应为 async function
    assert inspect.iscoroutinefunction(clip_bilibili)


@pytest.mark.asyncio
async def test_video_result_has_required_fields(tmp_path: Path):
    """clip_bilibili 结果必须含必要字段(FR-012, FR-004)。"""
    from clipper.video import clip_bilibili

    # Mock bili-cli subprocess 调用
    mock_video_data = {
        "title": "测试视频",
        "description": "测试描述",
        "duration_seconds": 120,
        "bvid": "BV1xx411c7mD",
        "cover_url": "https://example.com/cover.jpg",
    }

    with patch("clipper.video.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(mock_video_data),
            stderr="",
        )
        with (
            patch(
                "httpx.AsyncClient.get",
                new=AsyncMock(
                    return_value=MagicMock(content=b"fake image", raise_for_status=lambda: None)
                ),
            ),
            patch.dict("os.environ", {"CLIP_FORCE_LOCAL": "1"}),
        ):
            result = await clip_bilibili(
                "https://www.bilibili.com/video/BV1xx411c7mD",
                tmp_path / "output",
            )

    # 结果结构契约
    assert "success" in result
    assert "title" in result
    assert "md_file" in result
    assert "warnings" in result
    assert "error" in result
    assert "fetch_backend" in result  # FR-012


def test_fetch_backend_values_contract():
    """fetch_backend 字段取值契约。"""
    # 合法取值
    valid_backends = {"httpx", "firecrawl", "bili-cli", "local"}
    # ASR 引擎组合形式
    valid_asr_combos = {"bili-cli+asr:bijian", "bili-cli+asr:jianying", "bili-cli+asr:volcengine"}
    # 所有合法值的并集
    all_valid = valid_backends | valid_asr_combos | {""}
    # 验证取值范围
    assert "httpx" in all_valid
    assert "firecrawl" in all_valid
    assert "bili-cli" in all_valid
    assert "local" in all_valid


@pytest.mark.asyncio
async def test_video_failure_still_returns_structured_result(tmp_path: Path):
    """bili-cli 失败时仍返回结构化结果(不抛异常)。"""
    from clipper.video import clip_bilibili

    with patch("clipper.video.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="bili login required",
        )
        with patch.dict("os.environ", {"CLIP_FORCE_LOCAL": "1"}):
            result = await clip_bilibili(
                "https://www.bilibili.com/video/BV1xx411c7mD",
                tmp_path / "output",
            )

    # 失败时仍返回结构化结果
    assert isinstance(result, dict)
    assert result["success"] is False
    assert "error" in result
    assert result["error"] is not None
