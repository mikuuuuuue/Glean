"""ASR 分级回退模块单元测试(T062 覆盖补充)。

补充 clipper/asr.py 未覆盖的分支:
  - _ASRProxy.get / transcribe_with_fallback(委托 FallbackChain)
  - videocaptioner_available(安装/未安装)
  - _clear_proxy_env
  - transcribe_with_videocaptioner(成功/未安装/未知引擎/超时/异常)
  - _guess_audio_format(各扩展名)
  - transcribe_with_volcengine(未配置/URL 供给失败/提交成功+轮询成功/提交失败)
  - provision_audio_url(各 method 分发)
  - _serve_local_http(无配置/成功)
  - _upload_to_tos(未配置/SDK 未装/成功/失败)
  - _serve_via_tunnel(隧道失败)
"""

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clipper.asr import (
    _ASRProxy,
    _clear_proxy_env,
    _guess_audio_format,
    _serve_local_http,
    _serve_via_tunnel,
    _upload_to_tos,
    provision_audio_url,
    transcribe_with_fallback,
    transcribe_with_videocaptioner,
    transcribe_with_volcengine,
    videocaptioner_available,
)

# ── _ASRProxy ───────────────────────────────────────────────


def test_asr_proxy_get_returns_config_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """_ASRProxy.get 从 asr 子节取值。"""
    import yaml

    cfg = {
        "asr": {"enabled": True, "keep_audio": False, "fallback_chain": ["bijian"]},
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg), encoding="utf-8")
    monkeypatch.setattr("clipper.config._CONFIG_CACHE", None)
    monkeypatch.setattr("clipper.config._DEFAULT_CONFIG_PATH", cfg_path)

    proxy = _ASRProxy()
    assert proxy.get("enabled") is True
    assert proxy.get("keep_audio") is False
    assert proxy.get("fallback_chain") == ["bijian"]


def test_asr_proxy_get_returns_default_for_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """缺失键返回默认值。"""
    import yaml

    cfg = {"asr": {"enabled": True}}
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg), encoding="utf-8")
    monkeypatch.setattr("clipper.config._CONFIG_CACHE", None)
    monkeypatch.setattr("clipper.config._DEFAULT_CONFIG_PATH", cfg_path)

    proxy = _ASRProxy()
    assert proxy.get("nonexistent", "default_val") == "default_val"


def test_asr_proxy_get_returns_default_when_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """asr 子节中值为 None 时返回默认值。"""
    import yaml

    cfg = {"asr": {"enabled": None}}
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg), encoding="utf-8")
    monkeypatch.setattr("clipper.config._CONFIG_CACHE", None)
    monkeypatch.setattr("clipper.config._DEFAULT_CONFIG_PATH", cfg_path)

    proxy = _ASRProxy()
    assert proxy.get("enabled", "fallback") == "fallback"


# ── transcribe_with_fallback ───────────────────────────────


@pytest.mark.asyncio
async def test_transcribe_with_fallback_delegates_to_chain(tmp_path: Path):
    """transcribe_with_fallback 委托给 FallbackChain.transcribe。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    expected = {
        "success": True,
        "text": "转写文本",
        "engine": "bijian",
        "transcript_file": str(tmp_path / "transcript.txt"),
        "warnings": [],
    }

    mock_chain = MagicMock()
    mock_chain.transcribe = AsyncMock(return_value=expected)

    with patch("clipper.asr_fallback.build_default_chain", return_value=mock_chain):
        result = await transcribe_with_fallback(audio, tmp_path, language="zh")

    assert result == expected
    mock_chain.transcribe.assert_awaited_once_with(audio, "zh")


@pytest.mark.asyncio
async def test_transcribe_with_fallback_default_language(tmp_path: Path):
    """未传 language 时默认 "auto"。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")

    mock_chain = MagicMock()
    mock_chain.transcribe = AsyncMock(return_value={"success": False, "warnings": []})

    with patch("clipper.asr_fallback.build_default_chain", return_value=mock_chain):
        await transcribe_with_fallback(audio, tmp_path)

    mock_chain.transcribe.assert_awaited_once_with(audio, "auto")


# ── videocaptioner_available ───────────────────────────────


def test_videocaptioner_available_when_installed(monkeypatch: pytest.MonkeyPatch):
    """videocaptioner 已安装时返回 True。"""
    fake_mod = types.ModuleType("videocaptioner")
    # 临时注入 sys.modules 让 import 成功
    monkeypatch.setitem(sys.modules, "videocaptioner", fake_mod)
    assert videocaptioner_available() is True


def test_videocaptioner_available_when_not_installed(monkeypatch: pytest.MonkeyPatch):
    """videocaptioner 未安装时返回 False。"""
    # 确保不存在
    monkeypatch.delitem(sys.modules, "videocaptioner", raising=False)

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "videocaptioner":
            raise ImportError("No module named 'videocaptioner'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert videocaptioner_available() is False


# ── _clear_proxy_env ───────────────────────────────────────


def test_clear_proxy_env_removes_proxy_vars(monkeypatch: pytest.MonkeyPatch):
    """_clear_proxy_env 清除所有代理环境变量。"""
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(k, "http://proxy:8080")
    monkeypatch.delenv("NO_PROXY", raising=False)

    _clear_proxy_env()

    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        assert k not in __import__("os").environ
    assert __import__("os").environ.get("NO_PROXY") == "*"


# ── _guess_audio_format ────────────────────────────────────


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("audio.wav", "wav"),
        ("audio.mp3", "mp3"),
        ("audio.ogg", "ogg"),
        ("audio.m4a", "mp4"),
        ("audio.mp4", "mp4"),
        ("audio.m4r", "mp4"),
        ("audio.flac", "mp4"),  # 未知扩展名默认 mp4
        ("audio", "mp4"),  # 无扩展名默认 mp4
        ("AUDIO.WAV", "wav"),  # 大小写不敏感
        ("audio.M4A", "mp4"),
    ],
)
def test_guess_audio_format(filename: str, expected: str):
    """_guess_audio_format 根据扩展名返回火山引擎 audio.format。"""
    assert _guess_audio_format(Path(filename)) == expected


# ── transcribe_with_videocaptioner ─────────────────────────


@pytest.mark.asyncio
async def test_videocaptioner_not_installed(tmp_path: Path):
    """videocaptioner 未安装时返回失败。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    with patch("clipper.asr.videocaptioner_available", return_value=False):
        ok, text, warns = await transcribe_with_videocaptioner(audio, "bijian", 60)
    assert ok is False
    assert text == ""
    assert any("未安装" in w for w in warns)


@pytest.mark.asyncio
async def test_videocaptioner_unknown_engine(tmp_path: Path):
    """未知引擎名时返回失败。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    with patch("clipper.asr.videocaptioner_available", return_value=True):
        ok, text, warns = await transcribe_with_videocaptioner(audio, "unknown_engine", 60)
    assert ok is False
    assert any("未知 ASR 引擎" in w for w in warns)


@pytest.mark.asyncio
async def test_videocaptioner_success(tmp_path: Path):
    """VideoCaptioner 转写成功:读取 bytes 调用引擎返回文本。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio bytes")

    # 构造 fake ASR 引擎模块
    fake_result = MagicMock()
    fake_result.to_txt.return_value = "识别出的字幕文本"
    fake_asr_instance = MagicMock()
    fake_asr_instance.run.return_value = fake_result
    fake_asr_class = MagicMock(return_value=fake_asr_instance)
    fake_module = types.ModuleType("videocaptioner.core.asr.bcut")
    fake_module.BcutASR = fake_asr_class

    with (
        patch("clipper.asr.videocaptioner_available", return_value=True),
        patch("importlib.import_module", return_value=fake_module),
    ):
        ok, text, warns = await transcribe_with_videocaptioner(audio, "bijian", 60)

    assert ok is True
    assert text == "识别出的字幕文本"
    assert warns == []
    # 验证传入了音频 bytes
    fake_asr_class.assert_called_once_with(b"audio bytes")


@pytest.mark.asyncio
async def test_videocaptioner_exception(tmp_path: Path):
    """转写过程异常时返回失败。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")

    fake_asr_class = MagicMock(side_effect=RuntimeError("ASR engine error"))
    fake_module = types.ModuleType("videocaptioner.core.asr.bcut")
    fake_module.BcutASR = fake_asr_class

    with (
        patch("clipper.asr.videocaptioner_available", return_value=True),
        patch("importlib.import_module", return_value=fake_module),
    ):
        ok, text, warns = await transcribe_with_videocaptioner(audio, "bijian", 60)

    assert ok is False
    assert text == ""
    assert any("转写失败" in w for w in warns)
    assert any("ASR engine error" in w for w in warns)


@pytest.mark.asyncio
async def test_videocaptioner_timeout(tmp_path: Path):
    """转写超时时返回失败(line 146-149)。

    注: Python 3.10 上 asyncio.TimeoutError 与 builtins.TimeoutError 不同类,
    asr.py 用 ``except TimeoutError`` 捕获 builtins.TimeoutError。
    这里直接 mock asyncio.wait_for 抛 builtins.TimeoutError 以覆盖超时分支。
    """
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")

    with (
        patch("clipper.asr.videocaptioner_available", return_value=True),
        patch("asyncio.wait_for", side_effect=TimeoutError()),
    ):
        ok, text, warns = await transcribe_with_videocaptioner(audio, "bijian", 60)

    assert ok is False
    assert text == ""
    assert any("超时" in w for w in warns)


# ── transcribe_with_volcengine ──────────────────────────────


@pytest.mark.asyncio
async def test_volcengine_not_configured(tmp_path: Path):
    """未配置 appid/token/cluster 时返回失败。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    ok, text, warns = await transcribe_with_volcengine(audio, {})
    assert ok is False
    assert any("未配置" in w for w in warns)


@pytest.mark.asyncio
async def test_volcengine_url_provision_failed(tmp_path: Path):
    """音频 URL 供给失败时返回失败。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    vc_cfg = {
        "appid": "app",
        "token": "tok",
        "cluster": "cl",
        "audio_url": {"method": "local_http"},
    }
    with patch("clipper.asr.provision_audio_url", new=AsyncMock(return_value=(None, ["URL 失败"]))):
        ok, text, warns = await transcribe_with_volcengine(audio, vc_cfg)
    assert ok is False
    assert any("供给失败" in w for w in warns)


@pytest.mark.asyncio
async def test_volcengine_submit_failed(tmp_path: Path):
    """提交任务 code!=1000 时返回失败。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    vc_cfg = {
        "appid": "app",
        "token": "tok",
        "cluster": "cl",
        "audio_url": {"method": "local_http", "local_http": {"public_base": "http://x"}},
    }

    mock_submit_resp = MagicMock()
    mock_submit_resp.json.return_value = {"resp": {"code": 1001, "message": "invalid"}}

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_submit_resp)

    with (
        patch(
            "clipper.asr.provision_audio_url",
            new=AsyncMock(return_value=("http://x/audio.m4a", [])),
        ),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        ok, text, warns = await transcribe_with_volcengine(audio, vc_cfg)

    assert ok is False
    assert any("提交失败" in w for w in warns)


@pytest.mark.asyncio
async def test_volcengine_success(tmp_path: Path):
    """提交成功 + 轮询成功(code=1000)返回文本。"""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    vc_cfg = {
        "appid": "app",
        "token": "tok",
        "cluster": "cl",
        "audio_url": {"method": "local_http", "local_http": {"public_base": "http://x"}},
        "poll_interval": 0,  # 立即轮询
    }

    mock_submit_resp = MagicMock()
    mock_submit_resp.json.return_value = {"resp": {"code": 1000, "id": "task123"}}

    mock_query_resp = MagicMock()
    mock_query_resp.json.return_value = {"resp": {"code": 1000, "text": "火山识别文本"}}

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=[mock_submit_resp, mock_query_resp])

    with (
        patch(
            "clipper.asr.provision_audio_url",
            new=AsyncMock(return_value=("http://x/audio.wav", [])),
        ),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        ok, text, warns = await transcribe_with_volcengine(audio, vc_cfg)

    assert ok is True
    assert text == "火山识别文本"
    assert warns == []


@pytest.mark.asyncio
async def test_volcengine_success_empty_text(tmp_path: Path):
    """轮询成功但 text 为空时返回失败。"""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    vc_cfg = {
        "appid": "app",
        "token": "tok",
        "cluster": "cl",
        "audio_url": {"method": "local_http", "local_http": {"public_base": "http://x"}},
        "poll_interval": 0,
    }

    mock_submit_resp = MagicMock()
    mock_submit_resp.json.return_value = {"resp": {"code": 1000, "id": "task123"}}
    mock_query_resp = MagicMock()
    mock_query_resp.json.return_value = {"resp": {"code": 1000, "text": "  "}}

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=[mock_submit_resp, mock_query_resp])

    with (
        patch(
            "clipper.asr.provision_audio_url",
            new=AsyncMock(return_value=("http://x/audio.wav", [])),
        ),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        ok, text, warns = await transcribe_with_volcengine(audio, vc_cfg)

    assert ok is False
    assert any("text 为空" in w for w in warns)


@pytest.mark.asyncio
async def test_volcengine_query_error(tmp_path: Path):
    """轮询返回错误 code(<2000)时返回失败。"""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    vc_cfg = {
        "appid": "app",
        "token": "tok",
        "cluster": "cl",
        "audio_url": {"method": "local_http", "local_http": {"public_base": "http://x"}},
        "poll_interval": 0,
    }

    mock_submit_resp = MagicMock()
    mock_submit_resp.json.return_value = {"resp": {"code": 1000, "id": "task123"}}
    mock_query_resp = MagicMock()
    mock_query_resp.json.return_value = {"resp": {"code": 1500, "message": "audio error"}}

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=[mock_submit_resp, mock_query_resp])

    with (
        patch(
            "clipper.asr.provision_audio_url",
            new=AsyncMock(return_value=("http://x/audio.wav", [])),
        ),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        ok, text, warns = await transcribe_with_volcengine(audio, vc_cfg)

    assert ok is False
    assert any("识别失败" in w for w in warns)


@pytest.mark.asyncio
async def test_volcengine_processing_then_success(tmp_path: Path):
    """轮询先返回处理中(2000)再返回成功。"""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    vc_cfg = {
        "appid": "app",
        "token": "tok",
        "cluster": "cl",
        "audio_url": {"method": "local_http", "local_http": {"public_base": "http://x"}},
        "poll_interval": 0,
    }

    mock_submit_resp = MagicMock()
    mock_submit_resp.json.return_value = {"resp": {"code": 1000, "id": "task123"}}
    mock_processing_resp = MagicMock()
    mock_processing_resp.json.return_value = {"resp": {"code": 2000}}
    mock_success_resp = MagicMock()
    mock_success_resp.json.return_value = {"resp": {"code": 1000, "text": "最终文本"}}

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(
        side_effect=[mock_submit_resp, mock_processing_resp, mock_success_resp]
    )

    with (
        patch(
            "clipper.asr.provision_audio_url",
            new=AsyncMock(return_value=("http://x/audio.wav", [])),
        ),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        ok, text, warns = await transcribe_with_volcengine(audio, vc_cfg)

    assert ok is True
    assert text == "最终文本"


@pytest.mark.asyncio
async def test_volcengine_http_exception(tmp_path: Path):
    """httpx 异常时返回失败。"""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    vc_cfg = {
        "appid": "app",
        "token": "tok",
        "cluster": "cl",
        "audio_url": {"method": "local_http", "local_http": {"public_base": "http://x"}},
    }

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(side_effect=RuntimeError("connection refused"))
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch(
            "clipper.asr.provision_audio_url",
            new=AsyncMock(return_value=("http://x/audio.wav", [])),
        ),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        ok, text, warns = await transcribe_with_volcengine(audio, vc_cfg)

    assert ok is False
    assert any("异常" in w for w in warns)


# ── provision_audio_url ────────────────────────────────────


@pytest.mark.asyncio
async def test_provision_audio_url_no_method(tmp_path: Path):
    """未配置 method 时返回 None + 警告。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    url, warns = await provision_audio_url(audio, {})
    assert url is None
    assert any("未配置" in w for w in warns)


@pytest.mark.asyncio
async def test_provision_audio_url_local_http(tmp_path: Path):
    """method=local_http 委托给 _serve_local_http。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    with patch(
        "clipper.asr._serve_local_http", new=AsyncMock(return_value=("http://x/audio.m4a", ["ok"]))
    ):
        url, warns = await provision_audio_url(
            audio, {"method": "local_http", "local_http": {"public_base": "http://x"}}
        )
    assert url == "http://x/audio.m4a"
    assert "ok" in warns


@pytest.mark.asyncio
async def test_provision_audio_url_tos(tmp_path: Path):
    """method=tos 委托给 _upload_to_tos。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    with patch(
        "clipper.asr._upload_to_tos", new=AsyncMock(return_value=("http://tos/audio.m4a", []))
    ):
        url, warns = await provision_audio_url(audio, {"method": "tos", "tos": {"bucket": "b"}})
    assert url == "http://tos/audio.m4a"


@pytest.mark.asyncio
async def test_provision_audio_url_tunnel(tmp_path: Path):
    """method=tunnel 委托给 _serve_via_tunnel。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    with patch(
        "clipper.asr._serve_via_tunnel", new=AsyncMock(return_value=("http://tunnel/audio.m4a", []))
    ):
        url, warns = await provision_audio_url(
            audio, {"method": "tunnel", "tunnel": {"binary": "cloudflared"}}
        )
    assert url == "http://tunnel/audio.m4a"


# ── _serve_local_http ───────────────────────────────────────


@pytest.mark.asyncio
async def test_serve_local_http_no_public_base(tmp_path: Path):
    """未配置 public_base 时返回 None + 警告。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    url, warns = await _serve_local_http(audio, {})
    assert url is None
    assert any("public_base" in w for w in warns)


@pytest.mark.asyncio
async def test_serve_local_http_success(tmp_path: Path):
    """配置完整时启动本地 HTTP 服务并返回 URL。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    url, warns = await _serve_local_http(
        audio, {"public_base": "http://192.168.1.100:8765", "port": 9876}
    )
    assert url is not None
    assert "audio.m4a" in url
    assert "192.168.1.100:8765" in url
    assert any("HTTP" in w for w in warns)


# ── _serve_via_tunnel ───────────────────────────────────────


@pytest.mark.asyncio
async def test_serve_via_tunnel_failure(tmp_path: Path):
    """cloudflared 隧道启动失败时返回 None + 警告。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")

    # mock subprocess.Popen 返回无 URL 的输出
    mock_proc = MagicMock()
    mock_proc.stdout = MagicMock()
    mock_proc.stdout.readline = MagicMock(return_value="")  # 空输出
    mock_proc.kill = MagicMock()

    with patch("clipper.asr.subprocess.Popen", return_value=mock_proc):
        url, warns = await _serve_via_tunnel(audio, {"binary": "cloudflared"})

    assert url is None
    assert any("隧道" in w for w in warns)
    mock_proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_serve_via_tunnel_exception(tmp_path: Path):
    """Popen 抛异常时返回 None。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")

    with patch(
        "clipper.asr.subprocess.Popen", side_effect=FileNotFoundError("cloudflared not found")
    ):
        url, warns = await _serve_via_tunnel(audio, {"binary": "cloudflared"})

    assert url is None
    assert any("隧道" in w for w in warns)


# ── _upload_to_tos ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_to_tos_not_configured(tmp_path: Path):
    """未配置 access_key/secret_key/bucket 时返回 None。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    url, warns = await _upload_to_tos(audio, {})
    assert url is None
    assert any("未配置" in w for w in warns)


@pytest.mark.asyncio
async def test_upload_to_tos_sdk_not_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TOS SDK 未安装时返回 None。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "tos":
            raise ImportError("No module named 'tos'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    monkeypatch.delitem(sys.modules, "tos", raising=False)

    url, warns = await _upload_to_tos(
        audio, {"access_key": "ak", "secret_key": "sk", "bucket": "b"}
    )
    assert url is None
    assert any("SDK 未安装" in w for w in warns)


@pytest.mark.asyncio
async def test_upload_to_tos_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TOS 上传成功返回 presigned URL。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")

    mock_client = MagicMock()
    mock_client.put_object_from_file = MagicMock(return_value=None)
    mock_client.pre_signed_url = MagicMock(
        return_value="https://tos.example.com/audio.m4a?signed=xxx"
    )

    fake_tos = types.ModuleType("tos")
    fake_tos.TosClientV2 = MagicMock(return_value=mock_client)
    monkeypatch.setitem(sys.modules, "tos", fake_tos)

    url, warns = await _upload_to_tos(
        audio,
        {"access_key": "ak", "secret_key": "sk", "bucket": "b"},
    )
    assert url == "https://tos.example.com/audio.m4a?signed=xxx"
    assert warns == []


@pytest.mark.asyncio
async def test_upload_to_tos_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TOS 上传抛异常时返回错误字符串(非 http 开头)。"""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")

    mock_client = MagicMock()
    mock_client.put_object_from_file = MagicMock(side_effect=RuntimeError("network error"))

    fake_tos = types.ModuleType("tos")
    fake_tos.TosClientV2 = MagicMock(return_value=mock_client)
    monkeypatch.setitem(sys.modules, "tos", fake_tos)

    url, warns = await _upload_to_tos(
        audio,
        {"access_key": "ak", "secret_key": "sk", "bucket": "b"},
    )
    assert url is None
    assert any("上传失败" in w for w in warns)
    assert any("network error" in w for w in warns)
