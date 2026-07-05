"""ASR 分级回退集成测试(T028)。

mock 三个 ASRBackend,验证回退顺序与每级日志记录(FR-005)。
"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from clipper.asr_backend import ASRBackend
from clipper.asr_fallback import FallbackChain


class MockBackend(ASRBackend):
    """Mock ASRBackend for testing."""

    def __init__(self, name, available=True, supports_lang=True, result=(False, "", [])):
        self._name = name
        self._available = available
        self._supports_lang = supports_lang
        # AsyncMock 以实例属性形式覆盖 transcribe,提供 .assert_not_called() 等断言
        self.transcribe = AsyncMock(return_value=result)

    @property
    def name(self) -> str:
        return self._name

    def available(self) -> bool:
        return self._available

    def supports_language(self, lang: str) -> bool:
        return self._supports_lang


# 绕过 ABC 抽象方法检查:transcribe 由实例属性 AsyncMock 提供
MockBackend.__abstractmethods__ = frozenset()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_fallback_first_success(tmp_path, tmp_config):
    """第一个 backend 成功,不尝试后续。"""
    audio = tmp_path / "test.wav"
    audio.write_bytes(b"fake audio")
    b1 = MockBackend("bijian", result=(True, "hello world", []))
    b2 = MockBackend("jianying")
    b3 = MockBackend("volcengine")
    chain = FallbackChain([b1, b2, b3])
    result = await chain.transcribe(audio, "auto")
    assert result["success"] is True
    assert result["engine"] == "bijian"
    assert result["text"] == "hello world"
    b2.transcribe.assert_not_called()
    b3.transcribe.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_second_after_first_fail(tmp_path, tmp_config):
    """第一个失败,第二个成功。"""
    audio = tmp_path / "test.wav"
    audio.write_bytes(b"fake audio")
    b1 = MockBackend("bijian", result=(False, "", ["bijian error"]))
    b2 = MockBackend("jianying", result=(True, "hello", []))
    b3 = MockBackend("volcengine")
    chain = FallbackChain([b1, b2, b3])
    result = await chain.transcribe(audio, "auto")
    assert result["success"] is True
    assert result["engine"] == "jianying"
    assert "bijian error" in result["warnings"]


@pytest.mark.asyncio
async def test_fallback_all_fail(tmp_path, tmp_config):
    """全部失败时返回错误。"""
    audio = tmp_path / "test.wav"
    audio.write_bytes(b"fake audio")
    b1 = MockBackend("bijian", result=(False, "", ["bijian fail"]))
    b2 = MockBackend("jianying", result=(False, "", ["jianying fail"]))
    b3 = MockBackend("volcengine", result=(False, "", ["volc fail"]))
    chain = FallbackChain([b1, b2, b3])
    result = await chain.transcribe(audio, "auto")
    assert result["success"] is False
    assert result["error"] == "ASR 全部回退失败"
    assert len(result["warnings"]) == 3


@pytest.mark.asyncio
async def test_fallback_skip_unavailable(tmp_path, tmp_config):
    """跳过 unavailable 的 backend。"""
    audio = tmp_path / "test.wav"
    audio.write_bytes(b"fake audio")
    b1 = MockBackend("bijian", available=False)
    b2 = MockBackend("jianying", result=(True, "text", []))
    chain = FallbackChain([b1, b2])
    result = await chain.transcribe(audio, "auto")
    assert result["success"] is True
    assert result["engine"] == "jianying"
    b1.transcribe.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_skip_unsupported_language(tmp_path, tmp_config):
    """跳过不支持指定语言的 backend。"""
    audio = tmp_path / "test.wav"
    audio.write_bytes(b"fake audio")
    b1 = MockBackend("bijian", supports_lang=False)  # 不支持日语
    b2 = MockBackend("volcengine", result=(True, "text", []))
    chain = FallbackChain([b1, b2])
    result = await chain.transcribe(audio, "ja")
    assert result["success"] is True
    assert result["engine"] == "volcengine"
    b1.transcribe.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_no_audio_file(tmp_config):
    """音频文件不存在时返回错误。"""
    chain = FallbackChain([MockBackend("bijian")])
    result = await chain.transcribe(Path("/nonexistent/audio.wav"), "auto")
    assert result["success"] is False
    assert "不存在" in result["error"]


@pytest.mark.asyncio
async def test_fallback_transcript_saved(tmp_path, tmp_config):
    """成功时保存 transcript.txt。"""
    audio = tmp_path / "test.wav"
    audio.write_bytes(b"fake audio")
    b1 = MockBackend("bijian", result=(True, "transcribed text", []))
    chain = FallbackChain([b1])
    result = await chain.transcribe(audio, "auto")
    assert result["transcript_file"] is not None
    assert Path(result["transcript_file"]).exists()
    assert Path(result["transcript_file"]).read_text() == "transcribed text"
