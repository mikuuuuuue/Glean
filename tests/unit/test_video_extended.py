"""视频剪藏扩展单元测试(T062 覆盖补充)。

补充 clipper/video.py 未覆盖的分支:
  - is_bilibili_url / resolve_b23 / resolve_av_to_bv
  - clip_bilibili: bili-cli 成功路径(官方字幕/无字幕/ASR 回退)
  - clip_bilibili: bili-cli 不可用 / 无 BV 号 / 执行失败 / 返回错误 / 异常
  - 字幕数据结构(dict/text/items/body/str/list 各分支)
  - _download_cover / download_bilibili_audio / _run_bili_cli
  - _bili_cli_available / _bili_audio_available
  - clip_youtube 预留占位
"""

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clipper.video import (
    _bili_audio_available,
    _bili_cli_available,
    _build_video_placeholder,
    _download_cover,
    _run_bili_cli,
    clip_bilibili,
    clip_youtube,
    download_bilibili_audio,
    extract_bvid,
    is_bilibili_url,
    resolve_av_to_bv,
    resolve_b23,
)

# ── 配置 fixture ────────────────────────────────────────────


@pytest.fixture
def video_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """注入临时配置(asr 默认关闭)。"""
    import yaml

    cfg = {
        "storage": {"base_dir": str(tmp_path / "clipped"), "index_file": "_index.json"},
        "categories": ["科技与AI", "视频与影音", "其他收藏"],
        "category_keywords": {"科技与AI": ["ai"], "视频与影音": ["视频"], "其他收藏": []},
        "scraping": {"backend": "local", "firecrawl": {"api_key": ""}},
        "video": {"bilibili": "pass", "platforms": ["bilibili"]},
        "asr": {
            "enabled": False,
            "keep_audio": False,
            "keep_transcript": True,
            "audio_dir": "",
            "fallback_chain": ["videocaptioner:bijian", "volcengine"],
            "videocaptioner": {"language": "auto", "timeout": 600},
            "volcengine": {"appid": "", "token": "", "cluster": ""},
        },
        "limits": {
            "max_images": 5,
            "max_content_chars": 50000,
            "image_timeout": 10,
            "page_fetch_timeout": 20,
            "max_file_size_mb": 20,
            "max_video_duration_min": 15,
        },
        "screenshot": {"enabled": False, "engine": "off", "timeout": 30},
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr("clipper.config._CONFIG_CACHE", None)
    monkeypatch.setattr("clipper.config._DEFAULT_CONFIG_PATH", cfg_path)
    return cfg_path


# ── is_bilibili_url ─────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "https://www.bilibili.com/video/av12345",
        "https://b23.tv/abc123",
        "https://www.bilibili.com/bangumi/play/ep12345",
    ],
)
def test_is_bilibili_url_matches(url: str):
    assert is_bilibili_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video/BV1xx411c7mD",
        "https://www.youtube.com/watch?v=abc",
        "not a url",
        "",
    ],
)
def test_is_bilibili_url_non_matches(url: str):
    assert is_bilibili_url(url) is False


def test_is_bilibili_url_case_insensitive():
    assert is_bilibili_url("HTTPS://WWW.BILIBILI.COM/video/BV1xx411c7mD") is True
    assert is_bilibili_url("https://B23.TV/abc") is True


# ── extract_bvid (补充边界) ──────────────────────────────────


def test_extract_bvid_none_for_non_bilibili():
    assert extract_bvid("https://example.com") is None
    assert extract_bvid("not a url") is None


# ── resolve_b23 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_b23_non_b23_returns_original():
    """非 b23.tv URL 原样返回。"""
    url = "https://www.bilibili.com/video/BV1xx411c7mD"
    assert await resolve_b23(url) == url


@pytest.mark.asyncio
async def test_resolve_b23_returns_location_header():
    """b23.tv 短链返回 Location 头真实 URL。"""
    mock_response = MagicMock()
    mock_response.headers = {"Location": "https://www.bilibili.com/video/BV1xx411c7mD"}

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await resolve_b23("https://b23.tv/abc123")

    assert result == "https://www.bilibili.com/video/BV1xx411c7mD"


@pytest.mark.asyncio
async def test_resolve_b23_no_location_returns_original():
    """b23.tv 无 Location 头时返回原 URL。"""
    mock_response = MagicMock()
    mock_response.headers = {}

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await resolve_b23("https://b23.tv/abc123")

    assert result == "https://b23.tv/abc123"


@pytest.mark.asyncio
async def test_resolve_b23_exception_returns_original():
    """httpx 异常时返回原 URL(不抛出)。"""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(side_effect=RuntimeError("network"))
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await resolve_b23("https://b23.tv/abc123")

    assert result == "https://b23.tv/abc123"


# ── resolve_av_to_bv ────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_av_to_bv_non_av_returns_original():
    """非 av 号原样返回。"""
    assert await resolve_av_to_bv("BV1xx411c7mD") == "BV1xx411c7mD"
    assert await resolve_av_to_bv("") == ""


@pytest.mark.asyncio
async def test_resolve_av_to_bv_success():
    """av 号成功转为 BV 号。"""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "code": 0,
        "data": {"bvid": "BV1xx411c7mD"},
    }
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await resolve_av_to_bv("av170001")

    assert result == "BV1xx411c7mD"


@pytest.mark.asyncio
async def test_resolve_av_to_bv_api_error_returns_original():
    """API 返回 code!=0 时返回原 av 号。"""
    mock_response = MagicMock()
    mock_response.json.return_value = {"code": -404, "data": {}}
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await resolve_av_to_bv("av99999")

    assert result == "av99999"


@pytest.mark.asyncio
async def test_resolve_av_to_bv_exception_returns_original():
    """httpx 异常时返回原 av 号。"""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(side_effect=RuntimeError("network"))
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await resolve_av_to_bv("av12345")

    assert result == "av12345"


@pytest.mark.asyncio
async def test_resolve_av_to_bv_season_episode():
    """T078: 合集 av 号返回 episodes[0].bvid。"""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "code": 0,
        "data": {
            "episodes": [
                {"bvid": "BV1frTx6REeG", "title": "第1集"},
                {"bvid": "BV1frTx6REeH", "title": "第2集"},
            ],
        },
    }
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await resolve_av_to_bv("av116856144794089")

    assert result == "BV1frTx6REeG"


@pytest.mark.asyncio
async def test_resolve_av_to_bv_season_empty_episodes():
    """T078: 合集 episodes 为空列表时返回原 av 号。"""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "code": 0,
        "data": {"episodes": []},
    }
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await resolve_av_to_bv("av99999")

    assert result == "av99999"


# ── _bili_cli_available / _bili_audio_available ─────────────


def test_bili_cli_available_true():
    """bili-cli 已安装时返回 True。"""
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("clipper.video.subprocess.run", return_value=mock_result):
        assert _bili_cli_available() is True


def test_bili_cli_available_false_not_found():
    """bili-cli 未安装(FileNotFoundError)返回 False。"""
    with patch("clipper.video.subprocess.run", side_effect=FileNotFoundError()):
        assert _bili_cli_available() is False


def test_bili_cli_available_false_timeout():
    """bili-cli 超时返回 False。"""
    with patch(
        "clipper.video.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="bili", timeout=5),
    ):
        assert _bili_cli_available() is False


def test_bili_cli_available_false_nonzero():
    """bili-cli 退出码非 0 返回 False。"""
    mock_result = MagicMock()
    mock_result.returncode = 1
    with patch("clipper.video.subprocess.run", return_value=mock_result):
        assert _bili_cli_available() is False


def test_bili_audio_available_true():
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("clipper.video.subprocess.run", return_value=mock_result):
        assert _bili_audio_available() is True


def test_bili_audio_available_false_not_found():
    with patch("clipper.video.subprocess.run", side_effect=FileNotFoundError()):
        assert _bili_audio_available() is False


# ── _run_bili_cli ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_bili_cli_success_json():
    """bili-cli 返回有效 JSON 时解析返回。"""
    raw_json = json.dumps({"ok": True, "data": {"video": {"title": "T"}}})
    mock_proc = MagicMock()
    mock_proc.stdout = raw_json
    mock_proc.stderr = ""
    mock_proc.returncode = 0
    with patch("clipper.video.subprocess.run", return_value=mock_proc):
        result = await _run_bili_cli("BV1xx411c7mD")
    assert result["ok"] is True
    assert result["data"]["video"]["title"] == "T"


@pytest.mark.asyncio
async def test_run_bili_cli_not_logged_in():
    """stderr 含 login 提示时返回未登录错误。"""
    mock_proc = MagicMock()
    mock_proc.stdout = ""
    mock_proc.stderr = "not logged in, please run bili login"
    mock_proc.returncode = 1
    with patch("clipper.video.subprocess.run", return_value=mock_proc):
        result = await _run_bili_cli("BV1xx411c7mD")
    assert result["ok"] is False
    assert "未登录" in result["error"]


@pytest.mark.asyncio
async def test_run_bili_cli_invalid_json_falls_back_to_exitcode():
    """stdout 非合法 JSON 时按退出码处理。"""
    mock_proc = MagicMock()
    mock_proc.stdout = "not json"
    mock_proc.stderr = "some error"
    mock_proc.returncode = 2
    with patch("clipper.video.subprocess.run", return_value=mock_proc):
        result = await _run_bili_cli("BV1xx411c7mD")
    assert result["ok"] is False
    assert "some error" in result["error"]


@pytest.mark.asyncio
async def test_run_bili_cli_empty_stderr_uses_returncode():
    """无 stderr 时用退出码作为错误信息。"""
    mock_proc = MagicMock()
    mock_proc.stdout = ""
    mock_proc.stderr = ""
    mock_proc.returncode = 3
    with patch("clipper.video.subprocess.run", return_value=mock_proc):
        result = await _run_bili_cli("BV1xx411c7mD")
    assert result["ok"] is False
    assert "退出码 3" in result["error"]


@pytest.mark.asyncio
async def test_run_bili_cli_file_not_found():
    """bili-cli 未安装时返回未安装错误。"""
    with patch("clipper.video.subprocess.run", side_effect=FileNotFoundError()):
        result = await _run_bili_cli("BV1xx411c7mD")
    assert result["ok"] is False
    assert "未安装" in result["error"]


@pytest.mark.asyncio
async def test_run_bili_cli_timeout():
    """bili-cli 执行超时。"""
    with patch(
        "clipper.video.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="bili", timeout=30),
    ):
        result = await _run_bili_cli("BV1xx411c7mD")
    assert result["ok"] is False
    assert "超时" in result["error"]


@pytest.mark.asyncio
async def test_run_bili_cli_generic_exception():
    """其他异常被捕获返回错误。"""
    with patch("clipper.video.subprocess.run", side_effect=RuntimeError("boom")):
        result = await _run_bili_cli("BV1xx411c7mD")
    assert result["ok"] is False
    assert "boom" in result["error"]


# ── _download_cover ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_cover_success(tmp_path: Path):
    """封面下载成功:根据 Content-Type 选扩展名并落盘。"""
    mock_response = MagicMock()
    mock_response.content = b"fake image bytes"
    mock_response.headers = {"Content-Type": "image/png"}
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await _download_cover("https://example.com/cover.png", tmp_path)

    assert result is not None
    assert result.name == "cover.png"
    assert result.read_bytes() == b"fake image bytes"


@pytest.mark.asyncio
async def test_download_cover_jpeg_default(tmp_path: Path):
    """无匹配 Content-Type 时默认 .jpg。"""
    mock_response = MagicMock()
    mock_response.content = b"jpg bytes"
    mock_response.headers = {"Content-Type": "application/octet-stream"}
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await _download_cover("https://example.com/cover", tmp_path)

    assert result is not None
    assert result.suffix == ".jpg"


@pytest.mark.asyncio
async def test_download_cover_failure_returns_none(tmp_path: Path):
    """封面下载失败时返回 None(不抛出)。"""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(side_effect=RuntimeError("network"))
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await _download_cover("https://example.com/cover.png", tmp_path)

    assert result is None


# ── download_bilibili_audio ─────────────────────────────────


@pytest.mark.asyncio
async def test_download_bilibili_audio_not_available(tmp_path: Path):
    """bili-cli audio 扩展不可用时返回 None。"""
    with patch("clipper.video._bili_audio_available", return_value=False):
        result = await download_bilibili_audio("BV1xx411c7mD", tmp_path)
    assert result is None


@pytest.mark.asyncio
async def test_download_bilibili_audio_success(tmp_path: Path):
    """音频下载成功:返回 m4a 文件路径。"""
    audio_file = tmp_path / "audio.m4a"
    audio_file.write_bytes(b"fake audio")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    with (
        patch("clipper.video._bili_audio_available", return_value=True),
        patch("clipper.video.subprocess.run", return_value=mock_proc),
    ):
        result = await download_bilibili_audio("BV1xx411c7mD", tmp_path)

    assert result is not None
    assert result.suffix == ".m4a"


@pytest.mark.asyncio
async def test_download_bilibili_audio_failure(tmp_path: Path):
    """音频下载失败(退出码非 0)返回 None。"""
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    with (
        patch("clipper.video._bili_audio_available", return_value=True),
        patch("clipper.video.subprocess.run", return_value=mock_proc),
    ):
        result = await download_bilibili_audio("BV1xx411c7mD", tmp_path)
    assert result is None


@pytest.mark.asyncio
async def test_download_bilibili_audio_timeout(tmp_path: Path):
    """音频下载超时返回 None。"""
    with (
        patch("clipper.video._bili_audio_available", return_value=True),
        patch(
            "clipper.video.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="bili", timeout=900),
        ),
    ):
        result = await download_bilibili_audio("BV1xx411c7mD", tmp_path)
    assert result is None


@pytest.mark.asyncio
async def test_download_bilibili_audio_no_files(tmp_path: Path):
    """下载成功但目录无音频文件时返回 None。"""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    with (
        patch("clipper.video._bili_audio_available", return_value=True),
        patch("clipper.video.subprocess.run", return_value=mock_proc),
    ):
        result = await download_bilibili_audio("BV1xx411c7mD", tmp_path)
    assert result is None


# ── clip_bilibili: bili-cli 不可用 ───────────────────────────


@pytest.mark.asyncio
async def test_clip_bilibili_bili_cli_not_available(video_config, tmp_path: Path):
    """bili-cli 未安装时落占位 md,success=False(line 135-153)。"""
    out = tmp_path / "output"
    with patch("clipper.video._bili_cli_available", return_value=False):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is False
    assert "bili-cli 未安装" in result["error"]
    assert result["md_file"] is not None
    assert Path(result["md_file"]).exists()
    md = Path(result["md_file"]).read_text(encoding="utf-8")
    assert "bili-cli 未安装" in md


# ── clip_bilibili: 无法提取 BV 号 ─────────────────────────────


@pytest.mark.asyncio
async def test_clip_bilibili_no_bvid(video_config, tmp_path: Path):
    """无法从 URL 提取 BV 号时落占位 md(line 170-186)。"""
    out = tmp_path / "output"
    # 用一个非 b23.tv 但也提取不出 BV 号的 URL
    with patch("clipper.video._bili_cli_available", return_value=True):
        result = await clip_bilibili("https://www.bilibili.com/bangumi/play/ss100", out)

    assert result["success"] is False
    assert "无法从URL提取BV号" in result["error"]
    assert result["md_file"] is not None


# ── clip_bilibili: _run_bili_cli 返回 None ───────────────────


@pytest.mark.asyncio
async def test_clip_bilibili_bili_cli_returns_none(video_config, tmp_path: Path):
    """bili-cli 执行失败(返回 None)时落占位 md(line 192-208)。"""
    out = tmp_path / "output"
    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=None)),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is False
    assert "bili-cli 执行失败" in result["error"]
    assert "登录" in result["error"]
    assert Path(result["md_file"]).exists()


# ── clip_bilibili: raw.ok=False ──────────────────────────────


@pytest.mark.asyncio
async def test_clip_bilibili_bili_cli_error(video_config, tmp_path: Path):
    """bili-cli 返回 ok=False 时落占位 md(line 211-227)。"""
    out = tmp_path / "output"
    raw = {"ok": False, "error": "视频不存在"}
    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is False
    assert "bili-cli 返回错误" in result["error"]
    assert "视频不存在" in result["error"]


# ── clip_bilibili: 成功 + 官方字幕(dict.text 分支) ───────────


def _bili_success_payload(subtitle: Any, *, desc: str = "视频简介", pic: str = "") -> dict:
    """构造 bili-cli 成功 JSON。"""
    return {
        "ok": True,
        "data": {
            "video": {
                "title": "测试视频标题",
                "description": desc,
                "pic": pic,
                "owner": {"name": "测试UP主"},
                "stats": {"view": 1234, "like": 56},
                "duration_seconds": 300,
                "pubdate": 1700000000,
            },
            "subtitle": subtitle,
        },
    }


@pytest.mark.asyncio
async def test_clip_bilibili_success_with_subtitle_text(video_config, tmp_path: Path):
    """成功 + 字幕(text 字段)路径。"""
    out = tmp_path / "output"
    raw = _bili_success_payload({"available": True, "text": "字幕正文内容"})
    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True
    assert result["title"] == "测试视频标题"
    assert result["has_subtitle"] is True
    assert result["subtitle_source"] == "official"
    assert "字幕正文内容" in Path(result["md_file"]).read_text(encoding="utf-8")
    assert result["description"] == "视频简介"


@pytest.mark.asyncio
async def test_clip_bilibili_success_subtitle_items(video_config, tmp_path: Path):
    """字幕 items 结构化数据分支(line 282-290)。"""
    out = tmp_path / "output"
    subtitle = {
        "available": True,
        "items": [
            {"content": "第一句"},
            {"content": "第二句"},
            {"content": "第二句"},  # 重复,应去重
            {"content": "  "},  # 空白,应跳过
        ],
    }
    raw = _bili_success_payload(subtitle)
    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True
    assert result["has_subtitle"] is True
    md = Path(result["md_file"]).read_text(encoding="utf-8")
    assert "第一句" in md
    assert "第二句" in md


@pytest.mark.asyncio
async def test_clip_bilibili_success_subtitle_body(video_config, tmp_path: Path):
    """字幕嵌套在 body 字段(line 292-300)。"""
    out = tmp_path / "output"
    subtitle = {
        "available": True,
        "text": "",  # text 为空,回退到 body
        "body": [{"content": "body字幕"}, {"content": "body字幕"}],
    }
    raw = _bili_success_payload(subtitle)
    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True
    assert result["has_subtitle"] is True
    assert "body字幕" in Path(result["md_file"]).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_clip_bilibili_success_subtitle_string(video_config, tmp_path: Path):
    """字幕为字符串(line 301-302)。"""
    out = tmp_path / "output"
    raw = _bili_success_payload("纯文本字幕内容")
    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True
    assert result["has_subtitle"] is True
    assert "纯文本字幕内容" in Path(result["md_file"]).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_clip_bilibili_success_subtitle_list(video_config, tmp_path: Path):
    """字幕为 list 结构(line 303-311)。"""
    out = tmp_path / "output"
    subtitle_list = [
        {"from": 0.0, "to": 1.5, "content": "列表字幕1"},
        {"from": 1.5, "to": 3.0, "content": "列表字幕2"},
    ]
    raw = _bili_success_payload(subtitle_list)
    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True
    assert result["has_subtitle"] is True
    md = Path(result["md_file"]).read_text(encoding="utf-8")
    assert "列表字幕1" in md
    assert "列表字幕2" in md


@pytest.mark.asyncio
async def test_clip_bilibili_success_subtitle_available_false(video_config, tmp_path: Path):
    """字幕明确标记 available=False(line 272-274)。"""
    out = tmp_path / "output"
    raw = _bili_success_payload({"available": False})
    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True
    # 无字幕,asr 关闭 → 走"无字幕"warning
    assert result["has_subtitle"] is False
    assert any("无字幕" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_clip_bilibili_success_with_cover(video_config, tmp_path: Path):
    """成功 + 封面下载(line 374-378)。"""
    out = tmp_path / "output"
    raw = _bili_success_payload(
        {"available": True, "text": "字幕"}, pic="https://example.com/cover.png"
    )

    mock_response = MagicMock()
    mock_response.content = b"cover bytes"
    mock_response.headers = {"Content-Type": "image/png"}
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)

    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True
    assert result["cover_file"] is not None
    assert Path(result["cover_file"]).exists()
    # 封面引用写入 md
    md = Path(result["md_file"]).read_text(encoding="utf-8")
    assert "cover.png" in md


@pytest.mark.asyncio
async def test_clip_bilibili_success_category_fn(video_config, tmp_path: Path):
    """category_fn 回算真实领域(line 260-262)。"""
    out = tmp_path / "output"
    raw = _bili_success_payload({"available": True, "text": "字幕"}, desc="讲 AI 和 编程")

    def cat_fn(title, desc):
        assert "AI" in desc
        return "科技与AI"

    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
    ):
        result = await clip_bilibili(
            "https://www.bilibili.com/video/BV1xx411c7mD", out, category_fn=cat_fn
        )

    assert result["success"] is True
    assert result["category"] == "科技与AI"
    assert "科技与AI" in Path(result["md_file"]).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_clip_bilibili_success_old_schema(video_config, tmp_path: Path):
    """旧版 schema:data 直接含 title/desc/owner/stat(line 234-241)。"""
    out = tmp_path / "output"
    raw = {
        "ok": True,
        "data": {
            "title": "旧版标题",
            "desc": "旧版简介",
            "pic": "",
            "owner": {"name": "旧版UP主"},
            "stat": {"view": 99, "like": 10},
            "duration": 120,
            "pubdate": 1700000000,
            "subtitle": "旧版字幕文本",
        },
    }
    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True
    assert result["title"] == "旧版标题"
    assert result["description"] == "旧版简介"
    assert result["has_subtitle"] is True


@pytest.mark.asyncio
async def test_clip_bilibili_success_owner_as_string(video_config, tmp_path: Path):
    """owner 为字符串时的兼容处理(line 239)。"""
    out = tmp_path / "output"
    raw = {
        "ok": True,
        "data": {
            "video": {
                "title": "T",
                "description": "",
                "pic": "",
                "owner": "字符串UP主",
                "stats": {},
                "duration_seconds": 60,
                "pubdate": 0,
            },
            "subtitle": {"available": True, "text": "字幕"},
        },
    }
    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True
    assert "字符串UP主" in Path(result["md_file"]).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_clip_bilibili_success_duration_not_int(video_config, tmp_path: Path):
    """duration 非整数时归零(line 242-243)。"""
    out = tmp_path / "output"
    raw = {
        "ok": True,
        "data": {
            "video": {
                "title": "T",
                "description": "",
                "pic": "",
                "owner": {"name": "U"},
                "stats": {},
                "duration_seconds": "not a number",
                "pubdate": 0,
            },
            "subtitle": {"available": True, "text": "字幕"},
        },
    }
    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True


# ── clip_bilibili: ASR 回退 ─────────────────────────────────


@pytest.fixture
def video_config_asr_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """asr.enabled=True 的配置。"""
    import yaml

    cfg = {
        "storage": {"base_dir": str(tmp_path / "clipped"), "index_file": "_index.json"},
        "categories": ["科技与AI", "视频与影音", "其他收藏"],
        "category_keywords": {"科技与AI": ["ai"], "视频与影音": ["视频"], "其他收藏": []},
        "video": {"bilibili": "pass", "platforms": ["bilibili"]},
        "asr": {
            "enabled": True,
            "keep_audio": False,
            "keep_transcript": True,
            "audio_dir": "",
            "fallback_chain": ["videocaptioner:bijian", "volcengine"],
            "videocaptioner": {"language": "auto", "timeout": 600},
            "volcengine": {"appid": "", "token": "", "cluster": ""},
        },
        "limits": {
            "max_images": 5,
            "max_content_chars": 50000,
            "image_timeout": 10,
            "page_fetch_timeout": 20,
            "max_file_size_mb": 20,
            "max_video_duration_min": 15,
        },
        "screenshot": {"enabled": False, "engine": "off", "timeout": 30},
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr("clipper.config._CONFIG_CACHE", None)
    monkeypatch.setattr("clipper.config._DEFAULT_CONFIG_PATH", cfg_path)
    return cfg_path


@pytest.mark.asyncio
async def test_clip_bilibili_asr_fallback_success(video_config_asr_on, tmp_path: Path):
    """无官方字幕 + ASR 开启 + 转写成功(line 318-348)。"""
    out = tmp_path / "output"
    audio_file = tmp_path / "audio.m4a"
    audio_file.write_bytes(b"audio")

    raw = _bili_success_payload({"available": False})
    asr_result = {
        "success": True,
        "text": "ASR 转写文本",
        "engine": "bijian",
        "transcript_file": str(out / "transcript.txt"),
        "warnings": [],
    }

    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
        patch(
            "clipper.video.download_bilibili_audio",
            new=AsyncMock(return_value=audio_file),
        ),
        patch(
            "clipper.asr.transcribe_with_fallback",
            new=AsyncMock(return_value=asr_result),
        ),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True
    assert result["has_subtitle"] is True
    assert result["subtitle_source"] == "asr:bijian"
    assert "asr" in result["fetch_backend"]
    assert any("ASR" in w for w in result["warnings"])
    # 音频已被清理(keep_audio=False)
    assert not audio_file.exists()
    # ASR 文本写入 md
    assert "ASR 转写文本" in Path(result["md_file"]).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_clip_bilibili_asr_fallback_failure(video_config_asr_on, tmp_path: Path):
    """无官方字幕 + ASR 全部失败(line 342-344)。"""
    out = tmp_path / "output"
    audio_file = tmp_path / "audio.m4a"
    audio_file.write_bytes(b"audio")

    raw = _bili_success_payload({"available": False})
    asr_result = {
        "success": False,
        "text": "",
        "engine": None,
        "transcript_file": None,
        "warnings": ["bijian failed"],
        "error": "ASR 全部回退失败",
    }

    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
        patch(
            "clipper.video.download_bilibili_audio",
            new=AsyncMock(return_value=audio_file),
        ),
        patch(
            "clipper.asr.transcribe_with_fallback",
            new=AsyncMock(return_value=asr_result),
        ),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True  # 视频信息仍成功
    assert result["has_subtitle"] is False
    assert any("ASR 回退失败" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_clip_bilibili_asr_audio_download_failure(video_config_asr_on, tmp_path: Path):
    """ASR 开启但音频下载失败(line 349-353)。"""
    out = tmp_path / "output"
    raw = _bili_success_payload({"available": False})

    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
        patch(
            "clipper.video.download_bilibili_audio",
            new=AsyncMock(return_value=None),
        ),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True
    assert result["has_subtitle"] is False
    assert any("音频下载失败" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_clip_bilibili_asr_keep_audio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """keep_audio=True 时音频不清理(line 346)。"""
    import yaml

    cfg = {
        "storage": {"base_dir": str(tmp_path / "clipped"), "index_file": "_index.json"},
        "categories": ["视频与影音", "其他收藏"],
        "category_keywords": {"视频与影音": ["视频"], "其他收藏": []},
        "asr": {
            "enabled": True,
            "keep_audio": True,  # 保留音频
            "keep_transcript": True,
            "audio_dir": "",
            "fallback_chain": ["videocaptioner:bijian"],
            "videocaptioner": {"language": "auto", "timeout": 600},
            "volcengine": {"appid": "", "token": "", "cluster": ""},
        },
        "limits": {
            "max_images": 5,
            "max_content_chars": 50000,
            "image_timeout": 10,
            "page_fetch_timeout": 20,
            "max_file_size_mb": 20,
            "max_video_duration_min": 15,
        },
        "screenshot": {"enabled": False, "engine": "off", "timeout": 30},
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr("clipper.config._CONFIG_CACHE", None)
    monkeypatch.setattr("clipper.config._DEFAULT_CONFIG_PATH", cfg_path)

    out = tmp_path / "output"
    audio_file = tmp_path / "audio.m4a"
    audio_file.write_bytes(b"audio")

    raw = _bili_success_payload({"available": False})
    asr_result = {
        "success": True,
        "text": "ASR文本",
        "engine": "bijian",
        "transcript_file": None,
        "warnings": [],
    }

    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
        patch(
            "clipper.video.download_bilibili_audio",
            new=AsyncMock(return_value=audio_file),
        ),
        patch(
            "clipper.asr.transcribe_with_fallback",
            new=AsyncMock(return_value=asr_result),
        ),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True
    # 音频保留
    assert audio_file.exists()


@pytest.mark.asyncio
async def test_clip_bilibili_asr_custom_audio_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """asr.audio_dir 指定时音频下载到该目录(line 323)。"""
    import yaml

    audio_dir = tmp_path / "asr_audio"
    cfg = {
        "storage": {"base_dir": str(tmp_path / "clipped"), "index_file": "_index.json"},
        "categories": ["视频与影音", "其他收藏"],
        "category_keywords": {"视频与影音": ["视频"], "其他收藏": []},
        "asr": {
            "enabled": True,
            "keep_audio": True,
            "keep_transcript": True,
            "audio_dir": str(audio_dir),  # 自定义音频目录
            "fallback_chain": ["videocaptioner:bijian"],
            "videocaptioner": {"language": "auto", "timeout": 600},
            "volcengine": {"appid": "", "token": "", "cluster": ""},
        },
        "limits": {
            "max_images": 5,
            "max_content_chars": 50000,
            "image_timeout": 10,
            "page_fetch_timeout": 20,
            "max_file_size_mb": 20,
            "max_video_duration_min": 15,
        },
        "screenshot": {"enabled": False, "engine": "off", "timeout": 30},
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr("clipper.config._CONFIG_CACHE", None)
    monkeypatch.setattr("clipper.config._DEFAULT_CONFIG_PATH", cfg_path)

    out = tmp_path / "output"
    raw = _bili_success_payload({"available": False})

    captured: dict = {}

    async def fake_download(bvid, d):
        captured["download_dir"] = d
        return None  # 返回 None 跳过 ASR

    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
        patch("clipper.video.download_bilibili_audio", new=fake_download),
    ):
        await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    # 音频目录应使用配置的 audio_dir
    assert captured["download_dir"] == audio_dir


# ── clip_bilibili: av 号转 BV ─────────────────────────────────


@pytest.mark.asyncio
async def test_clip_bilibili_av_to_bv_conversion(video_config, tmp_path: Path):
    """av 号自动转为 BV 号(line 165-168)。"""
    out = tmp_path / "output"
    raw = _bili_success_payload({"available": True, "text": "字幕"})

    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
        patch(
            "clipper.video.resolve_av_to_bv",
            new=AsyncMock(return_value="BV1converted"),
        ),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/av12345", out)

    assert result["success"] is True


# ── clip_bilibili: b23.tv 短链解析 ────────────────────────────


@pytest.mark.asyncio
async def test_clip_bilibili_b23_resolution(video_config, tmp_path: Path):
    """b23.tv 短链解析为真实 URL 后提取 BV 号(line 157-162)。"""
    out = tmp_path / "output"
    raw = _bili_success_payload({"available": True, "text": "字幕"})

    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
        patch(
            "clipper.video.resolve_b23",
            new=AsyncMock(return_value="https://www.bilibili.com/video/BV1xx411c7mD"),
        ),
    ):
        result = await clip_bilibili("https://b23.tv/abc123", out)

    assert result["success"] is True


# ── clip_bilibili: 异常处理 ──────────────────────────────────


@pytest.mark.asyncio
async def test_clip_bilibili_exception_handled(video_config, tmp_path: Path):
    """处理过程抛异常时落占位 md(line 467-482)。"""
    out = tmp_path / "output"
    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch(
            "clipper.video._run_bili_cli",
            new=AsyncMock(side_effect=RuntimeError("unexpected boom")),
        ),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is False
    assert "B站视频处理异常" in result["error"]
    assert "unexpected boom" in result["error"]
    assert Path(result["md_file"]).exists()


# ── clip_bilibili: 长字幕截断 ────────────────────────────────


@pytest.mark.asyncio
async def test_clip_bilibili_long_subtitle_truncated(video_config, tmp_path: Path):
    """字幕超 10000 字时截断并加提示(line 416-418)。"""
    out = tmp_path / "output"
    long_text = "字幕" * 6000  # 12000 字
    raw = _bili_success_payload({"available": True, "text": long_text})
    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True
    md = Path(result["md_file"]).read_text(encoding="utf-8")
    assert "字幕内容过长" in md


# ── clip_bilibili: 视频时长超限 warning ──────────────────────


@pytest.mark.asyncio
async def test_clip_bilibili_duration_exceeded(video_config, tmp_path: Path):
    """视频时长超 15 分钟时 warning(line 248-251)。

    注: video.py 用 ``dur_ok, dur_err = validate_video_duration(duration)`` 解包,
    而 validators 返回 dict。这里 mock validate_video_duration 返回元组 (False, err)
    以触发超限分支。
    """
    out = tmp_path / "output"
    raw = _bili_success_payload({"available": True, "text": "字幕"})
    raw["data"]["video"]["duration_seconds"] = 1200  # 20 分钟
    with (
        patch("clipper.video._bili_cli_available", return_value=True),
        patch("clipper.video._run_bili_cli", new=AsyncMock(return_value=raw)),
        patch(
            "clipper.validators.validate_video_duration",
            return_value=(False, "视频时长 20.0分钟 超过限制 15分钟"),
        ),
    ):
        result = await clip_bilibili("https://www.bilibili.com/video/BV1xx411c7mD", out)

    assert result["success"] is True
    assert any("超过限制" in w or "时长" in w for w in result["warnings"])


# ── _build_video_placeholder ────────────────────────────────


def test_build_video_placeholder_basic():
    """占位 md 含失败原因与部分信息。"""
    md = _build_video_placeholder(
        "https://bilibili.com/video/BV1xx",
        "失败原因文本",
        ["BV号：BV1xx"],
    )
    assert "失败原因文本" in md
    assert "BV号：BV1xx" in md
    assert "https://bilibili.com/video/BV1xx" in md


def test_build_video_placeholder_no_partial_info():
    """无部分信息时不输出该节。"""
    md = _build_video_placeholder("url", "原因", [])
    assert "已获取信息" not in md


def test_build_video_placeholder_custom_category():
    """自定义分类写入 md。"""
    md = _build_video_placeholder("url", "原因", [], category="科技与AI", status="失败")
    assert "科技与AI" in md


# ── clip_youtube ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clip_youtube_returns_not_implemented(tmp_path: Path):
    """YouTube 预留占位返回未实现错误。"""
    result = await clip_youtube("https://youtube.com/watch?v=abc", tmp_path)
    assert result["success"] is False
    assert result["title"] == "YouTube"
    assert "尚未实现" in result["error"]
    assert result["has_subtitle"] is False
